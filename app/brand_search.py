"""Find one brand's outlets across a city or region.

The site score already calls Places Nearby Search and the Geocoding API with
the app's Google Maps key. This uses those same two endpoints.

Nearby Search only covers a circle, at most 50km, and about 60 places. A city
or a region such as Delhi NCR is larger than that, so the geocoded boundary
is split until each circle can cover its piece. Places are deduped and kept
only when the name matches the brand: the keyword parameter matches any text
Google has indexed, not just the place name.
"""

import time
from math import atan2, cos, radians, sin, sqrt

import requests

from app.brands import name_matches_brand_query

NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
MAX_RADIUS_METERS = 50000
PAGE_RESULT_CAP = 60


class PlacesLookupError(Exception):
    pass


def haversine_meters(lat1, lon1, lat2, lon2):
    radius = 6371000
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * radius * atan2(sqrt(a), sqrt(1 - a))


def _get_json(http, url, params):
    response = http.get(url, params=params, timeout=20)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise PlacesLookupError("Google returned an unreadable response.") from exc


def geocode_region(region, api_key, http):
    data = _get_json(http, GEOCODE_URL, {
        "address": region,
        "region": "in",
        "key": api_key,
    })
    status = data.get("status")
    if status != "OK":
        if status == "ZERO_RESULTS":
            raise PlacesLookupError("Could not find that city or region on Google Maps.")
        raise PlacesLookupError(f"Google could not resolve that place ({status or 'UNKNOWN'}).")

    top = (data.get("results") or [None])[0]
    geometry = (top or {}).get("geometry") or {}
    box = geometry.get("bounds") or geometry.get("viewport")
    location = geometry.get("location") or {}
    if not box or "lat" not in location or "lng" not in location:
        raise PlacesLookupError("Google did not return a boundary for that place.")
    return {
        "query": region,
        "name": top.get("formatted_address") or region,
        "lat": location["lat"],
        "lng": location["lng"],
        "sw": {"lat": box["southwest"]["lat"], "lng": box["southwest"]["lng"]},
        "ne": {"lat": box["northeast"]["lat"], "lng": box["northeast"]["lng"]},
    }


def _nearby(lat, lng, radius, keyword, api_key, http, sleep):
    data = _get_json(http, NEARBY_URL, {
        "location": f"{lat},{lng}",
        "radius": int(round(radius)),
        "keyword": keyword,
        "key": api_key,
    })
    status = data.get("status")
    if status not in ("OK", "ZERO_RESULTS"):
        raise PlacesLookupError(f"Google Places rejected the search ({status or 'UNKNOWN'}).")

    results = list(data.get("results") or [])
    token = data.get("next_page_token")
    pages = 1
    page_truncated = False
    while token and pages < 3:
        sleep(2)
        page = None
        for attempt in range(3):
            page = _get_json(http, NEARBY_URL, {"pagetoken": token, "key": api_key})
            if page.get("status") == "INVALID_REQUEST" and attempt < 2:
                sleep(1)
                continue
            break
        if page.get("status") not in ("OK", "ZERO_RESULTS"):
            page_truncated = True
            break
        results.extend(page.get("results") or [])
        token = page.get("next_page_token")
        pages += 1
    if token:
        page_truncated = True
    return results, page_truncated


def _covering_radius(sw, ne):
    center_lat = (sw["lat"] + ne["lat"]) / 2
    center_lng = (sw["lng"] + ne["lng"]) / 2
    corners = (
        (sw["lat"], sw["lng"]),
        (sw["lat"], ne["lng"]),
        (ne["lat"], sw["lng"]),
        (ne["lat"], ne["lng"]),
    )
    radius = max(haversine_meters(center_lat, center_lng, lat, lng) for lat, lng in corners)
    return center_lat, center_lng, radius


def _quadrants(sw, ne):
    mid_lat = (sw["lat"] + ne["lat"]) / 2
    mid_lng = (sw["lng"] + ne["lng"]) / 2
    return [
        ({"lat": sw["lat"], "lng": sw["lng"]}, {"lat": mid_lat, "lng": mid_lng}),
        ({"lat": sw["lat"], "lng": mid_lng}, {"lat": mid_lat, "lng": ne["lng"]}),
        ({"lat": mid_lat, "lng": sw["lng"]}, {"lat": ne["lat"], "lng": mid_lng}),
        ({"lat": mid_lat, "lng": mid_lng}, {"lat": ne["lat"], "lng": ne["lng"]}),
    ]


def _split(sw, ne, keyword, api_key, http, sleep, budget, depth):
    found = []
    truncated = False
    for child_sw, child_ne in _quadrants(sw, ne):
        places, child_truncated = _collect(
            child_sw, child_ne, keyword, api_key, http, sleep, budget, depth + 1
        )
        found.extend(places)
        truncated = truncated or child_truncated
    return found, truncated


def _collect(sw, ne, keyword, api_key, http, sleep, budget, depth):
    center_lat, center_lng, radius = _covering_radius(sw, ne)
    span = max(abs(ne["lat"] - sw["lat"]), abs(ne["lng"] - sw["lng"]))
    if radius > MAX_RADIUS_METERS and depth < 4 and budget[0] >= 4:
        return _split(sw, ne, keyword, api_key, http, sleep, budget, depth)
    if budget[0] <= 0:
        return [], True

    budget[0] -= 1
    # A circle cannot cover a region bigger than 50km. If we still have to
    # search one, the result is incomplete.
    uncovered = radius > MAX_RADIUS_METERS
    search_radius = min(MAX_RADIUS_METERS, max(500, radius * 1.05))
    places, page_truncated = _nearby(
        center_lat, center_lng, search_radius, keyword, api_key, http, sleep
    )
    saturated = len(places) >= PAGE_RESULT_CAP
    if saturated and not uncovered and depth < 4 and span > 0.04 and budget[0] >= 4:
        return _split(sw, ne, keyword, api_key, http, sleep, budget, depth)

    truncated = page_truncated or uncovered or (
        saturated and (depth >= 4 or span <= 0.04 or budget[0] < 4)
    )
    return places, truncated


def _in_box(lat, lng, sw, ne, pad_ratio=0.03):
    lat_pad = abs(ne["lat"] - sw["lat"]) * pad_ratio
    lng_pad = abs(ne["lng"] - sw["lng"]) * pad_ratio
    return (
        (sw["lat"] - lat_pad) <= lat <= (ne["lat"] + lat_pad)
        and (sw["lng"] - lng_pad) <= lng <= (ne["lng"] + lng_pad)
    )


def find_brand_outlets(brand, region, api_key, http=None, sleep=None, max_requests=24):
    if http is None:
        http = requests
    if sleep is None:
        sleep = time.sleep

    brand = (brand or "").strip()
    region = (region or "").strip()
    if not brand or not region:
        raise PlacesLookupError("Enter both a brand and a city or region.")
    if not api_key:
        raise PlacesLookupError("Google Maps API key is not configured.")

    geo = geocode_region(region, api_key, http)
    raw, truncated = _collect(
        geo["sw"], geo["ne"], brand, api_key, http, sleep, [max_requests], 0
    )

    seen = set()
    places = []
    for place in raw:
        place_id = place.get("place_id")
        location = ((place.get("geometry") or {}).get("location") or {})
        lat = location.get("lat")
        lng = location.get("lng")
        if not place_id or place_id in seen or lat is None or lng is None:
            continue
        if not _in_box(lat, lng, geo["sw"], geo["ne"]):
            continue
        if not name_matches_brand_query(place.get("name") or "", brand):
            continue
        seen.add(place_id)
        places.append(place)

    places.sort(key=lambda place: (place.get("name") or "").lower())
    return {
        "brand": brand,
        "region": geo,
        "places": places,
        "truncated": truncated,
    }
