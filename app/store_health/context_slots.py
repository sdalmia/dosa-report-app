"""Holiday, local news, and weather for a store's city.

East is Kolkata. North is Delhi NCR. Dates, headlines, and temperatures are
shown only when a live response contains them. A failed fetch stays on the
disconnected sentence. Nothing here is filled from memory.
"""

import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from app.store_health.present import IST, business_today, format_date, format_ist


HOLIDAY_DISCONNECTED = "No holiday calendar is connected"
NEWS_DISCONNECTED = "No local news source is connected."
WEATHER_NO_CITY = "Weather is unavailable because this store has no city on file."
WEATHER_UNAVAILABLE = "Weather is unavailable."

_CACHE = {}
_SUCCESS_TTL = 30 * 60
_FAILURE_TTL = 2 * 60
_TIMEOUT = 8

# WMO weather interpretation codes, as published by Open-Meteo.
# The code number still comes from the forecast response.
_WMO = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

_CITIES = {
    "east": {
        "key": "kolkata",
        "place": "Kolkata",
        "holiday_url": "https://www.officeholidays.com/ics/india/west-bengal",
        "holiday_source": (
            "Office Holidays public holidays for West Bengal (Kolkata is in West Bengal). "
            "https://www.officeholidays.com/ics/india/west-bengal"
        ),
        "news_query": "Kolkata",
        "geocode_name": "Kolkata",
    },
    "north": {
        "key": "delhi-ncr",
        "place": "Delhi NCR",
        "holiday_url": "https://www.officeholidays.com/ics/india/delhi",
        "holiday_source": (
            "Office Holidays public holidays for Delhi, used for the North region (Delhi NCR). "
            "This is the Delhi list, not a separate Haryana or Uttar Pradesh list. "
            "https://www.officeholidays.com/ics/india/delhi"
        ),
        "news_query": "Delhi NCR",
        "geocode_name": "Delhi",
    },
}


def _blank_slot(message=""):
    return {
        "connected": False,
        "message": message,
        "place": "",
        "source": "",
        "fetched_at": "",
        "entries": [],
        "summary": "",
        "days": [],
    }


def build_context_slots(store, today=None):
    """Context slots for the selected store. No store leaves the slots untitled."""
    if store is None:
        return {
            "holiday": _blank_slot(),
            "news": _blank_slot(),
            "weather": _blank_slot(),
        }
    today = today or business_today()
    spec = _CITIES.get((store.region or "").strip().casefold())
    if spec is None:
        return {
            "holiday": _blank_slot(HOLIDAY_DISCONNECTED),
            "news": _blank_slot(NEWS_DISCONNECTED),
            "weather": _blank_slot(WEATHER_NO_CITY),
        }
    payload = fetch_city_context(spec)
    fetched_at = ""
    if payload and payload.get("fetched_at") is not None:
        fetched_at = format_ist(payload["fetched_at"])
    return {
        "holiday": _holiday_slot(spec, payload, today, fetched_at),
        "news": _news_slot(spec, payload, fetched_at),
        "weather": _weather_slot(spec, payload, fetched_at),
    }


def fetch_city_context(spec):
    """Fetch holiday, news, and weather for one city. Cached per city."""
    key = spec["key"]
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < hit[1]:
        return hit[2]
    with ThreadPoolExecutor(max_workers=3) as pool:
        holiday_job = pool.submit(_safe, _fetch_holidays, spec)
        news_job = pool.submit(_safe, _fetch_news, spec)
        weather_job = pool.submit(_safe, _fetch_weather, spec)
        holiday = holiday_job.result()
        news = news_job.result()
        weather = weather_job.result()
    payload = {
        "fetched_at": datetime.now(IST),
        "holiday": holiday,
        "news": news,
        "weather": weather,
    }
    ttl = _SUCCESS_TTL if any(value is not None for value in (holiday, news, weather)) else _FAILURE_TTL
    _CACHE[key] = (now, ttl, payload)
    return payload


def clear_context_cache():
    _CACHE.clear()


def _safe(func, spec):
    try:
        return func(spec)
    except Exception:
        return None


def _http_text(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "DosaStoreHealth/1.0 (store health context)"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        raw = response.read()
    return raw.decode("utf-8", "replace")


def _fetch_holidays(spec):
    text = _http_text(spec["holiday_url"])
    events = parse_holiday_ics(text)
    if not events:
        return None
    return events


def _fetch_news(spec):
    query = urllib.parse.urlencode(
        {"q": f"{spec['news_query']} when:7d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    )
    feed_url = f"https://news.google.com/rss/search?{query}"
    items = [item for item in parse_news_rss(_http_text(feed_url)) if published_within_days(item["published"])]
    if not items:
        return None
    return {"feed_url": feed_url, "items": items[:3]}


def published_within_days(published, days=7, now=None):
    """True when an RSS pubDate is within the last `days` days."""
    now = now or datetime.now(timezone.utc)
    try:
        parsed = parsedate_to_datetime(published)
    except (TypeError, ValueError, IndexError, OverflowError):
        return False
    if parsed is None:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = now - parsed.astimezone(timezone.utc)
    return timedelta(hours=-12) <= delta <= timedelta(days=days)


def _fetch_weather(spec):
    name = urllib.parse.quote(spec["geocode_name"])
    geocode_url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={name}&count=1&language=en&format=json"
    )
    geocode = json.loads(_http_text(geocode_url))
    results = geocode.get("results") or []
    if not results:
        return None
    place = results[0]
    if (place.get("country_code") or "").upper() != "IN":
        return None
    latitude = place.get("latitude")
    longitude = place.get("longitude")
    if latitude is None or longitude is None:
        return None
    forecast_url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,weather_code,precipitation",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum",
                "timezone": "Asia/Kolkata",
                "forecast_days": 3,
            }
        )
    )
    forecast = json.loads(_http_text(forecast_url))
    return weather_from_payload(place, forecast, forecast_url)


def parse_holiday_ics(text):
    """Return {date, name} events from an iCalendar body."""
    events = []
    current = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current and current.get("date") and current.get("name"):
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            key = key.split(";", 1)[0].upper()
            if key == "SUMMARY":
                name = value.strip()
                if name:
                    current["name"] = name
            elif key == "DTSTART":
                parsed = _ics_date(value)
                if parsed is not None:
                    current["date"] = parsed
    unique = []
    seen = set()
    for event in events:
        token = (event["date"], event["name"])
        if token in seen:
            continue
        seen.add(token)
        unique.append({"date": event["date"], "name": event["name"]})
    return unique


def _unfold_ics(text):
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in normalised.split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _ics_date(value):
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def parse_news_rss(text):
    """Dated items only. An item with no pubDate is dropped."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    items = []
    for element in root.iter():
        if not str(element.tag).endswith("item"):
            continue
        title = ""
        published = ""
        for child in list(element):
            name = str(child.tag).split("}")[-1]
            if name == "title" and child.text:
                title = child.text.strip()
            elif name == "pubDate" and child.text:
                published = child.text.strip()
        if not title or not published:
            continue
        headline = title
        publisher = ""
        if " - " in title:
            headline, publisher = title.rsplit(" - ", 1)
            headline = headline.strip()
            publisher = publisher.strip()
        if "|" in headline:
            left, right = headline.rsplit("|", 1)
            if left.strip():
                headline = left.strip()
                if not publisher and right.strip():
                    publisher = right.strip()
        items.append(
            {
                "title": headline.strip(),
                "publisher": publisher.strip(),
                "published": published,
            }
        )
    return items


def weather_from_payload(place, forecast, source_url):
    """Build display fields from an Open-Meteo geocode result and forecast.

    A null measurement stays None. It is not stored as zero.
    """
    current = forecast.get("current") or {}
    daily = forecast.get("daily") or {}
    timezone = forecast.get("timezone") or place.get("timezone") or ""
    observed = current.get("time")
    name_bits = [place.get("name") or "", place.get("admin1") or "", place.get("country") or ""]
    api_place = ", ".join(bit for bit in name_bits if bit)
    days = []
    dates = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    rains = daily.get("precipitation_sum") or []
    codes = daily.get("weather_code") or []
    for index, raw_day in enumerate(dates):
        days.append(
            {
                "date": raw_day,
                "high_c": _measure(highs, index),
                "low_c": _measure(lows, index),
                "precipitation_mm": _measure(rains, index),
                "weather": _wmo_name(_measure(codes, index)),
            }
        )
    return {
        "api_place": api_place,
        "timezone": timezone,
        "observed_at": observed if observed else None,
        "temperature_c": _plain_number(current.get("temperature_2m")),
        "precipitation_mm": _plain_number(current.get("precipitation")),
        "weather": _wmo_name(_plain_number(current.get("weather_code"))),
        "days": days,
        "source_url": source_url,
    }


def _measure(values, index):
    if index >= len(values):
        return None
    return _plain_number(values[index])


def _plain_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, float):
            return format(value, "f").rstrip("0").rstrip(".") or "0"
        return str(value)
    text = str(value).strip()
    return text or None


def _wmo_name(code_text):
    if code_text is None:
        return None
    try:
        code = int(code_text)
    except (TypeError, ValueError):
        return f"weather code {code_text}"
    return _WMO.get(code, f"weather code {code}")


def _holiday_slot(spec, payload, today, fetched_at):
    events = None if not payload else payload.get("holiday")
    if not events:
        return _blank_slot(HOLIDAY_DISCONNECTED)
    upcoming = [event for event in events if event["date"] >= today]
    upcoming.sort(key=lambda event: (event["date"], event["name"]))
    items = [
        {"date": format_date(event["date"]), "name": event["name"]}
        for event in upcoming[:6]
    ]
    message = ""
    if not items:
        message = f"No holiday on or after {format_date(today)} is listed in this feed."
    return {
        "connected": True,
        "message": message,
        "place": spec["place"],
        "source": spec["holiday_source"],
        "fetched_at": fetched_at,
        "entries": items,
        "summary": "",
        "days": [],
    }


def _news_slot(spec, payload, fetched_at):
    news = None if not payload else payload.get("news")
    items = (news or {}).get("items") if news else None
    if not items:
        return _blank_slot(NEWS_DISCONNECTED)
    lines = []
    for item in items[:3]:
        parts = [item["title"]]
        if item.get("publisher"):
            parts.append(item["publisher"])
        parts.append(item["published"])
        lines.append({"line": " — ".join(parts)})
    return {
        "connected": True,
        "message": "",
        "place": spec["place"],
        "source": f"Google News RSS for {spec['place']}. {news['feed_url']}",
        "fetched_at": fetched_at,
        "entries": lines,
        "summary": "",
        "days": [],
    }


def _weather_slot(spec, payload, fetched_at):
    weather = None if not payload else payload.get("weather")
    if not weather:
        return _blank_slot(WEATHER_UNAVAILABLE)
    sentences = [f"Place: {weather['api_place']}. Store region city: {spec['place']}."]
    if weather.get("observed_at"):
        zone = weather.get("timezone") or "the source timezone"
        sentences.append(f"Observation time: {weather['observed_at']} ({zone}).")
    else:
        sentences.append("Observation time is blank.")
    if weather.get("temperature_c") is not None:
        sentences.append(f"Temperature: {weather['temperature_c']}°C.")
    else:
        sentences.append("Temperature is blank, not zero.")
    if weather.get("weather"):
        sentences.append(f"Conditions: {weather['weather']}.")
    else:
        sentences.append("Conditions are blank.")
    if weather.get("precipitation_mm") is not None:
        sentences.append(f"Precipitation: {weather['precipitation_mm']} mm.")
    else:
        sentences.append("Precipitation is blank, not zero.")
    source = weather.get("source_url") or "https://api.open-meteo.com"
    sentences.append(f"Source: Open-Meteo ({source}). Fetched {fetched_at}.")
    days = []
    for day in weather.get("days") or []:
        days.append({"line": _weather_day_line(day)})
    return {
        "connected": True,
        "message": "",
        "place": spec["place"],
        "source": f"Open-Meteo ({source})",
        "fetched_at": fetched_at,
        "entries": [],
        "summary": " ".join(sentences),
        "days": days,
    }


def _weather_day_line(day):
    bits = [str(day.get("date") or "")]
    if day.get("weather"):
        bits.append(day["weather"])
    if day.get("high_c") is not None and day.get("low_c") is not None:
        bits.append(f"high {day['high_c']}°C, low {day['low_c']}°C")
    elif day.get("high_c") is not None:
        bits.append(f"high {day['high_c']}°C. Low is blank, not zero")
    elif day.get("low_c") is not None:
        bits.append(f"low {day['low_c']}°C. High is blank, not zero")
    else:
        bits.append("high and low are blank, not zero")
    if day.get("precipitation_mm") is not None:
        bits.append(f"precipitation {day['precipitation_mm']} mm")
    else:
        bits.append("precipitation is blank, not zero")
    return ", ".join(bit for bit in bits if bit)

