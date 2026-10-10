"""Location Finder learning loop.

Snapshots, outcomes, and a pooled refit live under data/location.
A missing input file is data coming. A blank cell stays blank.
The live score uses the latest approved model. A refit stays proposed
until an owner approves it. Approval is stored in the database, not in
the JSON file, so a deploy does not wipe it.
"""

import csv
import json
import os
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app.food_courts import is_mall_food_court
from app.site_pattern import (
    DATA_COMING,
    FORMULA_FOR,
    blend,
    city_bucket,
    haversine_m,
)
from app.store_master import find_store, is_trading, load_rows

DENSITY_METRES = 3000
SITE_MATCH_METRES = 150
QUERY_CAP = 20
RIDERSHIP_METRES = 1000
RIDERSHIP_MIN_STORES = 8
MALL_MATCH_METRES = 250
ANCHOR_LIST_SIZE = 31
MIN_FORMAT_N = 8
MOVE_CAP = 0.20
DECILE = 0.10
MISS_DECILES = 1.5
DINE_IN_SOURCES = {"pos"}

FEATURE_KEYS = (
    "energy",
    "reviews",
    "transport",
    "premium",
    "diversity",
    "quality",
    "anchor",
    "restaurants",
    "residential",
    "aggregator",
    "aggregator_enabled",
    "mall_reviews",
    "anchors",
    "food_court",
    "distance",
    "ridership",
    "south_indian",
)

SNAPSHOT_COLUMNS = (
    "as_of",
    "store_id",
    "store",
    "city",
    "market",
    "format",
    "lat",
    "lng",
    "energy_of_6",
    "quality",
    "anchor",
    "diversity",
    "transport",
    "nearby_reviews",
    "classic_score",
    "energy",
    "reviews",
    "premium",
    "cuisine_types",
    "n_anchor_brands_500m",
    "n_fnb_chains_500m",
    "neighbour_brands",
    "aggregator_enabled",
    "mall_reviews",
    "anchors",
    "food_court",
    "restaurants",
    "residential",
    "aggregator",
    "competitor_count",
    "competitor_count_all",
    "south_indian_density",
    "density_capped",
    "google_rating",
)

OUTCOME_COLUMNS = (
    "as_of",
    "store_id",
    "store",
    "market",
    "format",
    "gross_per_trading_day",
    "dine_in_share",
    "aggregator_share",
    "trend_4w",
    "famepilot_rating",
    "bills_per_trading_day",
    "apb",
)

PREDICTION_COLUMNS = (
    "scored_at",
    "site_id",
    "site",
    "lat",
    "lng",
    "format",
    "model_version",
    "score",
    "breakdown",
)

OPENING_COLUMNS = ("site_id", "store_id", "open_date")


def _zeros():
    return {key: 0.0 for key in FEATURE_KEYS}


def prior_weights():
    """Study weights. A format with no term keeps that weight at 0."""
    high = _zeros()
    high.update({
        "energy": 0.35,
        "reviews": 0.15,
        "transport": 0.15,
        "premium": 0.15,
        "diversity": 0.10,
        "quality": 0.05,
    })
    mall = _zeros()
    mall.update({
        "aggregator_enabled": 0.30,
        "restaurants": 0.10,
        "residential": 0.10,
        "aggregator": 0.05,
        "mall_reviews": 0.20,
        "anchors": 0.15,
        "food_court": 0.05,
        "transport": 0.05,
    })
    cloud = _zeros()
    cloud.update({"restaurants": 0.40, "residential": 0.40, "aggregator": 0.20})
    metro = _zeros()
    metro.update({
        "distance": 0.20,
        "ridership": 0.20,
        "energy": 0.15,
        "reviews": 0.05,
        "transport": 0.15,
        "premium": 0.10,
        "diversity": 0.10,
        "quality": 0.05,
    })
    return {
        "high_street": high,
        "mall": mall,
        "cloud_kitchen": cloud,
        "metro": metro,
    }


def location_root():
    override = os.environ.get("LOCATION_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "data" / "location"


def inputs_dir():
    return location_root() / "inputs"


def _blank(value):
    return value is None or str(value).strip() == ""


def _float(value):
    if _blank(value):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float):
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return text
    return str(value)


def _read(path):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _cell(row.get(column)) for column in columns})
    return path


def _should_log():
    if os.environ.get("LOCATION_DATA_DIR", "").strip():
        return True
    return not os.environ.get("PYTEST_CURRENT_TEST")


def latest_sales_month():
    dates = []
    path = Path(__file__).resolve().parents[1] / "data" / "store_health" / "posist_daily.csv"
    for row in _read(path):
        text = (row.get("date") or "").strip()
        if len(text) >= 7:
            dates.append(text[:10])
    if not dates:
        return date.today().strftime("%Y-%m")
    return max(dates)[:7]


def _parse_day(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def cap_bounds(prior):
    """A weight may move 20% from its prior, and never below zero.

    A prior of 0 may rise by 0.20 so a new signal can enter.
    """
    prior = float(prior or 0)
    if prior <= 0:
        return 0.0, MOVE_CAP
    return max(0.0, prior * (1 - MOVE_CAP)), prior * (1 + MOVE_CAP)


_INDEX = {"key": None, "value": None}
_MALL = {"key": None, "value": None}


def clear_input_cache():
    _INDEX["key"] = None
    _INDEX["value"] = None
    _MALL["key"] = None
    _MALL["value"] = None


def _yes_no(value):
    """1, 0, or unknown. yes/no and 1/0 both count. A blank stays unknown."""
    text = str(value or "").strip().casefold()
    if text in {"1", "1.0", "yes", "y", "true"}:
        return 1.0
    if text in {"0", "0.0", "no", "n", "false"}:
        return 0.0
    return None


def _cluster_code(site_id):
    token = str(site_id or "").split()[0]
    if re.fullmatch(r"(?:NCR|KOL)-C\d+", token):
        return token
    return ""


def _mall_role(site_id):
    if str(site_id or "").startswith("REF-"):
        return "reference"
    if _cluster_code(site_id):
        return "candidate"
    return "store"


def mall_about():
    return (
        "Mall reviews are the mall's Google review count, on a log scale. "
        "A blank count is unknown, not zero. "
        "Anchors are how many of 31 national brands are inside the mall. "
        "Food court is yes or no only when a listing was found, and blank when it was not. "
        "Reference malls are on the map and are not scored."
    )


def _build_malls(path):
    if not path.is_file():
        return {"file": False, "rows": [], "by_store": {}, "review_band": (None, None)}
    from app.site_pattern import _log_band

    sites = input_index().get("sites") or []
    by_id = {site["site_id"]: site for site in sites}
    rows = []
    for raw in _read(path):
        site_id = (raw.get("site_id") or "").strip()
        if not site_id:
            continue
        role = _mall_role(site_id)
        store = find_store(site_id) if role == "store" else None
        cluster_id = _cluster_code(site_id) if role == "candidate" else ""
        cluster_site = by_id.get(site_id) if role == "candidate" else None
        rows.append({
            "site_id": site_id,
            "mall_name": (raw.get("mall_name") or "").strip(),
            "lat": _float(raw.get("lat")),
            "lng": _float(raw.get("lng")),
            "city": (raw.get("city") or "").strip(),
            "role": role,
            "store_id": "" if store is None else (store.get("store_id") or ""),
            "store_name": "" if store is None else (store.get("posist_name") or ""),
            "cluster_id": cluster_id,
            "cluster_site_id": "" if cluster_site is None else cluster_site["site_id"],
            "matched": bool(store) if role == "store" else bool(cluster_site) if role == "candidate" else True,
            "aggregator_enabled": _yes_no(raw.get("aggregator_enabled")),
            "review_count": _float(raw.get("mall_google_reviews")),
            "anchor_count": _float(raw.get("n_anchor_brands_inside")),
            "food_court": _yes_no(raw.get("food_court")),
            "rating": _float(raw.get("mall_google_rating")),
        })
    counts = [
        row["review_count"]
        for row in rows
        if row["role"] != "reference" and row["review_count"] is not None and row["review_count"] > 0
    ]
    band = _log_band(counts)
    for row in rows:
        count = row["anchor_count"]
        row["review_band"] = band
        row["anchor_unit"] = None if count is None else max(0.0, min(1.0, count / ANCHOR_LIST_SIZE))
    by_store = {}
    for row in rows:
        if row["role"] == "store" and row["store_name"]:
            by_store[row["store_name"]] = row
    return {"file": path.is_file(), "rows": rows, "by_store": by_store, "review_band": band}


def _mall_index():
    path = inputs_dir() / "mall_inputs.csv"
    stamp = path.stat().st_mtime if path.is_file() else None
    if _MALL.get("key") == stamp and _MALL.get("value") is not None:
        return _MALL["value"]
    value = _build_malls(path)
    _MALL["key"] = stamp
    _MALL["value"] = value
    return value


def mall_rows():
    """Every mall row. Re-reads the file when it changes, so a later drop replaces this one."""
    return list(_mall_index()["rows"])


def mall_for_store(name):
    return _mall_index()["by_store"].get(name or "")


def nearest_mall(lat, lon, max_metres=MALL_MATCH_METRES):
    """Nearest store or candidate mall. Reference malls are never a scoring match."""
    if lat is None or lon is None:
        return None
    best = None
    best_distance = None
    for row in _mall_index()["rows"]:
        if row["role"] == "reference" or row["lat"] is None or row["lng"] is None:
            continue
        distance = haversine_m(lat, lon, row["lat"], row["lng"])
        if distance > max_metres:
            continue
        if best_distance is None or distance < best_distance:
            best = row
            best_distance = distance
    return best


def mall_signals(row):
    """Feature values for one mall. Unknown stays missing, including a blank aggregator flag."""
    if not row or row.get("role") == "reference":
        return {}
    aggregator = row.get("aggregator_enabled")
    reviews = row.get("review_count")
    anchors = row.get("anchor_count")
    food = row.get("food_court")
    if aggregator is None:
        aggregator_detail = ""
    elif aggregator >= 1:
        aggregator_detail = "On Swiggy or Zomato"
    else:
        aggregator_detail = "POS only"
    if anchors is None:
        anchor_detail = ""
    else:
        anchor_detail = f"{int(anchors)} of {ANCHOR_LIST_SIZE} anchor brands"
    if food is None:
        food_detail = ""
    elif food >= 1:
        food_detail = "Yes"
    else:
        food_detail = "No"
    return {
        "aggregator_enabled": aggregator,
        "aggregator_detail": aggregator_detail,
        "mall_reviews": reviews,
        "mall_reviews_detail": "" if reviews is None else f"{int(reviews):,} Google reviews",
        "mall_review_band": row.get("review_band") or (None, None),
        "mall_anchors": row.get("anchor_unit"),
        "mall_anchor_detail": anchor_detail,
        "food_court": food,
        "food_court_detail": food_detail,
        "mall_file": True,
    }


def _google_query(source):
    match = re.search(r"search '([^']+)'", source or "")
    return match.group(1).casefold() if match else ""


def _period_key(period):
    text = (period or "").casefold()
    if "jun 2026" in text:
        return (2026, 6)
    if "sep 2025" in text:
        return (2025, 9)
    if "fy2023" in text:
        return (2024, 3)
    if "oct 2023" in text:
        return (2023, 10)
    return (0, 0)


def _within_city_percentile(value, population):
    """0 is the low end of this city. A real zero stays zero."""
    if value is None or not population:
        return None
    count = len(population)
    if count == 1:
        return 0.5
    below = sum(1 for other in population if other < value)
    equal = sum(1 for other in population if other == value)
    rank = below + (equal - 1) / 2 if equal else below
    return max(0.0, min(1.0, rank / (count - 1)))


def _understatement(text):
    folded = " ".join(str(text or "").casefold().replace("-", " ").split())
    reasons = []
    if "new town" in folded or "newtown" in folded:
        reasons.append("New Town")
    if "greater noida west" in folded:
        reasons.append("Greater Noida West")
    sectors = [int(number) for number in re.findall(r"(?:sector|sec)\s*(\d+)", folded)]
    if any(65 <= number <= 85 for number in sectors):
        reasons.append("Gurgaon sectors 65–85")
    if any(132 <= number <= 150 for number in sectors):
        reasons.append("Noida sectors 132–150")
    return reasons


def _public_site(site_id):
    text = re.sub(r"^Dosa Coffee\s*-\s*", "", site_id or "")
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    folded = text.casefold()
    if "swim" in folded:
        return "Swimming Club"
    if folded.startswith("connaught"):
        return "CP"
    return text or site_id


def _within(lat, lon, rows, limit, with_figure=False):
    found = []
    if lat is None or lon is None:
        return found
    for row in rows:
        if row.get("lat") is None or row.get("lng") is None:
            continue
        if with_figure and row.get("daily") is None:
            continue
        distance = haversine_m(lat, lon, row["lat"], row["lng"])
        if distance <= limit:
            found.append((distance, row))
    found.sort(key=lambda item: item[0])
    return found


def _nearest(lat, lon, rows, limit=None):
    best = None
    best_distance = None
    if lat is None or lon is None:
        return None, None
    for row in rows:
        if row.get("lat") is None or row.get("lng") is None:
            continue
        distance = haversine_m(lat, lon, row["lat"], row["lng"])
        if limit is not None and distance > limit:
            continue
        if best_distance is None or distance < best_distance:
            best = row
            best_distance = distance
    return best, best_distance


def _density_at(lat, lon, competitors):
    nearby = []
    for row in competitors:
        if haversine_m(lat, lon, row["lat"], row["lng"]) <= DENSITY_METRES:
            nearby.append(row)
    strict = [row for row in nearby if not row["haldiram"]]
    queries = {}
    for row in nearby:
        if row["google"] and row["query"]:
            queries[row["query"]] = queries.get(row["query"], 0) + 1
    known = [row["reviews"] for row in strict if row["reviews"] is not None]
    return {
        "count": len(strict),
        "all_count": len(nearby),
        "capped": any(count >= QUERY_CAP for count in queries.values()),
        "reviews_known": len(known),
        "reviews_blank": sum(1 for row in strict if row["reviews"] is None),
    }


def _build_index():
    root = inputs_dir()
    competitor_path = root / "competitors.csv"
    delivery_path = root / "delivery_inputs.csv"
    metro_path = root / "metro_ridership.csv"
    site_path = root / "sites.csv"
    competitors = []
    if competitor_path.is_file():
        for raw in _read(competitor_path):
            lat = _float(raw.get("lat"))
            lon = _float(raw.get("lng"))
            if lat is None or lon is None:
                continue
            brand = (raw.get("brand") or "").strip()
            source = raw.get("source") or ""
            competitors.append({
                "brand": brand,
                "haldiram": "haldiram" in brand.casefold(),
                "lat": lat,
                "lng": lon,
                "city": (raw.get("city") or "").strip(),
                "reviews": _float(raw.get("reviews")),
                "query": _google_query(source),
                "google": "google maps" in source.casefold(),
            })
    sites = []
    if site_path.is_file():
        for raw in _read(site_path):
            lat = _float(raw.get("lat"))
            lon = _float(raw.get("lng"))
            site_id = (raw.get("site_id") or "").strip()
            if not site_id or lat is None or lon is None:
                continue
            sites.append({
                "site_id": site_id,
                "site_type": (raw.get("site_type") or "").strip(),
                "lat": lat,
                "lng": lon,
                "city": (raw.get("city") or "").strip(),
                "note": (raw.get("note") or "").strip(),
            })
    delivery_rows = []
    if delivery_path.is_file():
        for raw in _read(delivery_path):
            lat = _float(raw.get("lat"))
            lon = _float(raw.get("lng"))
            site_id = (raw.get("site_id") or "").strip()
            if lat is None or lon is None:
                continue
            delivery_rows.append({
                "site_id": site_id,
                "lat": lat,
                "lng": lon,
                "city": (raw.get("city") or "").strip(),
                "restaurants": _float(raw.get("delivering_restaurants_3km")),
                "residential": _float(raw.get("residential_density")),
                "note": (raw.get("note") or "").strip(),
            })
    stations = {}
    if metro_path.is_file():
        for raw in _read(metro_path):
            name = (raw.get("station") or "").strip()
            lat = _float(raw.get("lat"))
            lon = _float(raw.get("lng"))
            if not name or lat is None or lon is None:
                continue
            period = (raw.get("period") or "").strip()
            row = {
                "station": name,
                "city": (raw.get("city") or "").strip(),
                "line": (raw.get("line") or "").strip(),
                "lat": lat,
                "lng": lon,
                "daily": _float(raw.get("daily_ridership")),
                "period": period,
            }
            key = (name.casefold(), row["city"].casefold())
            current = stations.get(key)
            if current is None or _period_key(period) > _period_key(current["period"]):
                stations[key] = row
    station_rows = list(stations.values())
    by_site = {site["site_id"]: site for site in sites}
    for site in sites:
        stats = _density_at(site["lat"], site["lng"], competitors) if competitors else {
            "count": None, "all_count": None, "capped": False, "reviews_known": 0, "reviews_blank": 0,
        }
        site.update(stats)
        site["understated"] = _understatement(f"{site['site_id']} {site['note']}")
    for row in delivery_rows:
        site = by_site.get(row["site_id"])
        if site is None:
            site, _distance = _nearest(row["lat"], row["lng"], sites, SITE_MATCH_METRES)
        row["understated"] = list(site["understated"]) if site else _understatement(f"{row['site_id']} {row['note']}")
        if site and not row["city"]:
            row["city"] = site["city"]
    for city_rows, key in (
        (_city_groups(sites), "count"),
        (_city_groups(delivery_rows), "restaurants"),
        (_city_groups(delivery_rows), "residential"),
    ):
        for grouped in city_rows.values():
            population = [row[key] for row in grouped if row.get(key) is not None]
            unit_key = {
                "count": "unit",
                "restaurants": "restaurants_unit",
                "residential": "residential_unit",
            }[key]
            for row in grouped:
                row[unit_key] = _within_city_percentile(row.get(key), population)
    ridership_stores = []
    for site in sites:
        if site["site_type"] != "store":
            continue
        figured = _within(site["lat"], site["lng"], station_rows, RIDERSHIP_METRES, with_figure=True)
        if not figured:
            continue
        distance, station = figured[0]
        ridership_stores.append({
            "site_id": site["site_id"],
            "name": _public_site(site["site_id"]),
            "station": station["station"],
            "metres": round(distance),
            "daily": station["daily"],
            "period": station["period"],
        })
    return {
        "competitors_file": competitor_path.is_file(),
        "delivery_file": delivery_path.is_file(),
        "metro_file": metro_path.is_file(),
        "sites_file": site_path.is_file(),
        "competitors": competitors,
        "sites": sites,
        "delivery": delivery_rows,
        "stations": station_rows,
        "ridership_stores": ridership_stores,
    }


def _city_groups(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row.get("city") or "", []).append(row)
    return grouped


def input_index():
    root = inputs_dir()
    stamps = []
    for name in ("sites.csv", "competitors.csv", "delivery_inputs.csv", "metro_ridership.csv"):
        path = root / name
        stamps.append((str(path), path.stat().st_mtime if path.is_file() else None))
    key = tuple(stamps)
    if _INDEX["key"] == key and _INDEX["value"] is not None:
        return _INDEX["value"]
    value = _build_index()
    _INDEX["key"] = key
    _INDEX["value"] = value
    return value


def review_stats(rows=None):
    """Mean of known review counts. A blank is skipped, never filled in as zero."""
    if rows is None:
        rows = input_index()["competitors"]
    known = [row["reviews"] for row in rows if row.get("reviews") is not None]
    blank = sum(1 for row in rows if row.get("reviews") is None)
    mean_known = sum(known) / len(known) if known else None
    mean_if_blank_were_zero = sum(known) / len(rows) if rows else None
    return {
        "known": len(known),
        "blank": blank,
        "mean_known": mean_known,
        "mean_if_blank_were_zero": mean_if_blank_were_zero,
    }


def metro_stations():
    if not input_index()["metro_file"]:
        return []
    return list(input_index()["stations"])


def ridership_coverage():
    index = input_index()
    stores = list(index["ridership_stores"])
    return {
        "stores": stores,
        "count": len(stores),
        "minimum": RIDERSHIP_MIN_STORES,
        "open": len(stores) >= RIDERSHIP_MIN_STORES,
        "stations_with_figure": sum(1 for row in index["stations"] if row.get("daily") is not None),
    }


def _density_detail(stats):
    detail = (
        f"{stats['count']} strict, {stats['all_count']} including Haldiram's, within 3 km"
    )
    if stats["capped"]:
        detail += ". Capped"
    return detail


def _competitor_about():
    return (
        "Strict South Indian density leaves out Haldiram's, which is brand-level only. "
        "The all-in count keeps those outlets. Blank review counts are unknown, not zero. "
        "Google returns at most 20 results a page, so a dense area is undercounted and marked capped."
    )


def _delivery_about(reasons):
    note = (
        "Delivering restaurants are an OpenStreetMap proxy, used only as a percentile within the city. "
        "Residential density is WorldPop 2020, in people per square kilometre."
    )
    if reasons:
        note += " WorldPop 2020 understates this area (" + ", ".join(reasons) + ")."
    return note


def _metro_about():
    coverage = ridership_coverage()
    names = [store["name"] for store in coverage["stores"]]
    if len(names) == 1:
        listed = names[0]
    elif names:
        listed = ", ".join(names[:-1]) + " and " + names[-1]
    else:
        listed = "none"
    return (
        "Station ridership uses the latest published period for each station. "
        f"Only {coverage['count']} stores have a figure within 1 km ({listed}), "
        f"so footfall stays at the prior weight and is data coming until {coverage['minimum']} stores do."
    )


def south_indian_signal(lat, lon):
    index = input_index()
    empty = {
        "file": False,
        "count": None,
        "all_count": None,
        "unit": None,
        "capped": False,
        "detail": "",
        "about": "",
    }
    if not index["competitors_file"]:
        return empty
    if lat is None or lon is None:
        return {**empty, "file": True, "about": _competitor_about()}
    site, _distance = _nearest(lat, lon, index["sites"], SITE_MATCH_METRES)
    if site is not None and site.get("count") is not None:
        stats = site
        city = site["city"]
    else:
        stats = _density_at(lat, lon, index["competitors"])
        nearest, _distance = _nearest(lat, lon, index["sites"])
        city = nearest["city"] if nearest else ""
        population = [row["count"] for row in index["sites"] if row["city"] == city and row.get("count") is not None]
        stats = {**stats, "unit": _within_city_percentile(stats["count"], population)}
    return {
        "file": True,
        "count": stats["count"],
        "all_count": stats["all_count"],
        "unit": stats.get("unit"),
        "capped": bool(stats.get("capped")),
        "detail": _density_detail(stats),
        "about": _competitor_about(),
    }


def _delivery_from_row(row):
    if row is None or row.get("restaurants") is None:
        return None
    reasons = row.get("understated") or []
    residential = row.get("residential")
    residential_detail = ""
    if residential is not None:
        residential_detail = f"{int(round(residential)):,} people per km², WorldPop 2020"
        if reasons:
            residential_detail += ". WorldPop 2020 understates this area"
    raw = row["restaurants"]
    restaurant_detail = (
        f"{int(raw)} OpenStreetMap restaurants within 3 km, as a percentile within the city"
    )
    return {
        "file": True,
        "restaurants": row.get("restaurants_unit"),
        "residential": row.get("residential_unit"),
        "restaurant_detail": restaurant_detail,
        "residential_detail": residential_detail,
        "about": _delivery_about(reasons),
        "raw_restaurants": raw,
        "understated": reasons,
    }


def delivery_signal(lat, lon, name=""):
    index = input_index()
    empty = {
        "file": False,
        "restaurants": None,
        "residential": None,
        "restaurant_detail": "",
        "residential_detail": "",
        "about": "",
        "raw_restaurants": None,
    }
    if not index["delivery_file"]:
        return empty
    row, _distance = _nearest(lat, lon, index["delivery"], SITE_MATCH_METRES)
    built = _delivery_from_row(row)
    if built is None:
        return {**empty, "file": True}
    return built


def delivery_for_site(site_id):
    if not site_id or not input_index()["delivery_file"]:
        return None
    for row in input_index()["delivery"]:
        if row["site_id"] == site_id:
            return _delivery_from_row(row)
    return None


def metro_signal(lat, lon):
    index = input_index()
    if not index["metro_file"]:
        return {"file": False}
    station, distance = _nearest(lat, lon, index["stations"])
    coverage = ridership_coverage()
    signal = {
        "file": True,
        "about": _metro_about(),
        "station_m": None if distance is None else round(distance),
        "station_detail": "",
        "ridership": None,
        "ridership_source": "",
    }
    if station is not None and distance is not None:
        signal["station_detail"] = f"{station['station']}, {round(distance)} m"
    if coverage["open"]:
        figured = _within(lat, lon, index["stations"], RIDERSHIP_METRES, with_figure=True)
        if figured:
            _figure_distance, figure = figured[0]
            signal["ridership"] = figure["daily"]
            signal["ridership_source"] = figure["period"]
    return signal


def optional_feature_signals(lat, lon, name=""):
    south = south_indian_signal(lat, lon)
    delivery = delivery_signal(lat, lon, name)
    metro = metro_signal(lat, lon)
    about = []
    extra = {
        "south_indian": None if not south["file"] else south["unit"],
        "south_indian_detail": south["detail"],
        "south_indian_file": south["file"],
        "south_indian_count": south["count"],
        "south_indian_capped": south["capped"],
        "delivery_file": delivery["file"],
    }
    if south.get("about"):
        about.append(south["about"])
    if delivery["file"] and delivery["restaurants"] is not None:
        extra["delivering_restaurants"] = delivery["restaurants"]
        extra["restaurants_scaled"] = True
        extra["restaurant_detail"] = delivery["restaurant_detail"]
    if delivery["file"] and delivery["residential"] is not None:
        extra["residential"] = delivery["residential"]
        extra["residential_detail"] = delivery["residential_detail"]
    if delivery.get("about"):
        about.append(delivery["about"])
    if metro.get("file"):
        extra["station_m"] = metro["station_m"]
        extra["station_detail"] = metro["station_detail"]
        extra["ridership"] = metro["ridership"]
        extra["ridership_source"] = metro["ridership_source"]
        if metro.get("about"):
            about.append(metro["about"])
    extra["about"] = about
    return extra


def finish_pattern(pattern, formula, signals):
    """Add competitor density and, once approved, the fitted weights."""
    parts = []
    for part in pattern.get("parts") or []:
        copy = {
            "key": part.get("key"),
            "label": part.get("label"),
            "weight": part.get("weight") or 0,
            "value": part.get("value"),
            "detail": part.get("detail") or "",
        }
        if part.get("status") == DATA_COMING:
            copy["status"] = DATA_COMING
        parts.append(copy)
    if not any(part["key"] == "south_indian" for part in parts):
        missing = not signals.get("south_indian_file")
        part = {
            "key": "south_indian",
            "label": "South Indian competitor density",
            "weight": 0,
            "value": None if missing else signals.get("south_indian"),
            "detail": signals.get("south_indian_detail") or "",
        }
        if missing:
            part["status"] = DATA_COMING
        parts.append(part)
    model = latest_approved()
    version = "prior"
    if model:
        version = model.get("version") or "prior"
        weights = (model.get("weights") or {}).get(formula) or {}
        for part in parts:
            if part["key"] in weights:
                part["weight"] = float(weights[part["key"]])
    blended = blend(parts)
    blended["model_label"] = version
    blended["model_version"] = version
    blended["about"] = list(signals.get("about") or [])
    return blended


def _part_value(pattern, key):
    for part in (pattern or {}).get("parts") or []:
        if part.get("key") == key:
            return part.get("value")
    return None


def snapshot_rows(month=None):
    from app.site_pattern import load_board

    month = month or latest_sales_month()
    board = {store["name"]: store for store in load_board()["stores"]}
    rows = []
    for master in load_rows():
        name = (master.get("posist_name") or "").strip()
        if not name or not is_trading(name):
            continue
        study = board.get(name) or {}
        lat = study.get("lat")
        lon = study.get("lon")
        south = south_indian_signal(lat, lon)
        pattern = study.get("pattern")
        market = city_bucket(master.get("region") or study.get("region") or "")
        fmt = FORMULA_FOR.get(study.get("format"), study.get("format") or "")
        energy_raw = study.get("energy_of_6")
        energy_unit = _part_value(pattern, "energy")
        if energy_unit is None and energy_raw is not None:
            energy_unit = max(0.0, min(1.0, float(energy_raw) / 6))
        rows.append({
            "as_of": month,
            "store_id": master.get("store_id") or "",
            "store": name,
            "city": master.get("city") or "",
            "market": market,
            "format": fmt,
            "lat": lat,
            "lng": lon,
            "energy_of_6": energy_raw,
            "quality": study.get("quality_raw"),
            "anchor": study.get("anchor_raw"),
            "diversity": study.get("diversity_raw"),
            "transport": study.get("transport_raw"),
            "nearby_reviews": study.get("nearby_reviews"),
            "classic_score": study.get("classic_score"),
            "energy": energy_unit,
            "reviews": _part_value(pattern, "reviews"),
            "premium": _part_value(pattern, "premium"),
            "cuisine_types": study.get("cuisine_types"),
            "n_anchor_brands_500m": study.get("n_anchor_brands_500m"),
            "n_fnb_chains_500m": study.get("n_fnb_chains_500m"),
            "neighbour_brands": study.get("neighbour_brands") or "",
            "aggregator_enabled": _part_value(pattern, "aggregator_enabled") if fmt == "mall" else None,
            "mall_reviews": _part_value(pattern, "mall_reviews") if fmt == "mall" else None,
            "anchors": _part_value(pattern, "anchors") if fmt == "mall" else None,
            "food_court": _part_value(pattern, "food_court") if fmt == "mall" else None,
            "restaurants": _part_value(study.get("delivery"), "restaurants") if fmt == "mall" else None,
            "residential": _part_value(study.get("delivery"), "residential") if fmt == "mall" else None,
            "aggregator": _part_value(study.get("delivery"), "aggregator") if fmt == "mall" else None,
            "competitor_count": south["count"],
            "competitor_count_all": south.get("all_count"),
            "south_indian_density": south["unit"],
            "density_capped": None if not south["file"] else ("yes" if south["capped"] else "no"),
            "google_rating": study.get("google_rating"),
        })
    rows.sort(key=lambda row: (row["market"], row["store"].casefold()))
    return rows


def write_snapshot(month=None):
    month = month or latest_sales_month()
    rows = snapshot_rows(month)
    path = location_root() / "store_features" / f"{month}.csv"
    return _write(path, SNAPSHOT_COLUMNS, rows)


def _channel_range_path():
    folder = Path(__file__).resolve().parents[1] / "data" / "channels"
    matches = sorted(folder.glob("channel_sales_range_*.csv"))
    return matches[-1] if matches else None


def _daily_rows():
    path = Path(__file__).resolve().parents[1] / "data" / "store_health" / "posist_daily.csv"
    return _read(path)


def _famepilot_rating(store_name):
    path = Path(__file__).resolve().parents[1] / "data" / "store_health" / "famepilot.csv"
    target = find_store(store_name)
    target_name = (target or {}).get("posist_name") or store_name
    for row in _read(path):
        label = (row.get("posist_store") or "").strip()
        if label == target_name or label == store_name:
            return _float(row.get("rating"))
    return None


def _store_key(label):
    row = find_store(label)
    if row is not None:
        return row.get("posist_name") or label
    return label


def outcome_rows(features):
    daily = _daily_rows()
    by_store = {}
    for row in daily:
        name = _store_key(row.get("store"))
        by_store.setdefault(name, []).append(row)
    channel_path = _channel_range_path()
    channels = {}
    for row in _read(channel_path) if channel_path else []:
        name = _store_key(row.get("store"))
        source = (row.get("source") or "").strip().casefold()
        gross = _float(row.get("gross"))
        if not source or source == "not shown" or gross is None:
            continue
        channels.setdefault(name, []).append((source, gross))
    dates = [day for row in daily if (day := _parse_day(row.get("date")))]
    end = max(dates) if dates else None
    built = []
    for feature in features:
        name = feature["store"]
        days = []
        for row in by_store.get(name, []):
            day = _parse_day(row.get("date"))
            gross = _float(row.get("gross"))
            bills = _float(row.get("bills"))
            if day is None:
                continue
            days.append({"date": day, "gross": gross, "bills": bills})
        gross_days = [row for row in days if row["gross"] is not None]
        bill_days = [row for row in days if row["bills"] is not None]
        gross_per = None
        if gross_days:
            gross_per = sum(row["gross"] for row in gross_days) / len(gross_days)
        mall = is_mall_food_court(name)
        bills_per = None
        apb = None
        if not mall and bill_days:
            bills_per = sum(row["bills"] for row in bill_days) / len(bill_days)
        if not mall and gross_per is not None and bills_per not in (None, 0):
            apb = gross_per / bills_per
        trend = _four_week_trend(days, end)
        grouped = channels.get(name) or []
        dine = sum(gross for source, gross in grouped if source in DINE_IN_SOURCES)
        total = sum(gross for _source, gross in grouped)
        dine_share = None
        aggregator_share = None
        if total > 0 and grouped:
            dine_share = dine / total
            aggregator_share = (total - dine) / total
        built.append({
            "as_of": feature["as_of"],
            "store_id": feature["store_id"],
            "store": name,
            "market": feature.get("market") or "",
            "format": feature.get("format") or "",
            "gross_per_trading_day": gross_per,
            "dine_in_share": dine_share,
            "aggregator_share": aggregator_share,
            "trend_4w": trend,
            "famepilot_rating": _famepilot_rating(name),
            "bills_per_trading_day": bills_per,
            "apb": apb,
        })
    return built


def _four_week_trend(days, end):
    if end is None:
        return None
    recent_start = end - timedelta(days=6)
    prior_start = end - timedelta(days=27)
    recent = [row["gross"] for row in days if row["gross"] is not None and recent_start <= row["date"] <= end]
    prior = [row["gross"] for row in days if row["gross"] is not None and prior_start <= row["date"] < recent_start]
    if not recent or not prior:
        return None
    prior_mean = sum(prior) / len(prior)
    if prior_mean == 0:
        return None
    return (sum(recent) / len(recent) - prior_mean) / prior_mean


def write_outcomes(month=None):
    month = month or latest_sales_month()
    features = snapshot_rows(month)
    path = location_root() / "outcomes" / f"{month}.csv"
    return _write(path, OUTCOME_COLUMNS, outcome_rows(features))


def _within_market_ranks(rows):
    grouped = {}
    for row in rows:
        if row.get("gross") is None or not row.get("market"):
            row["rank"] = None
            continue
        grouped.setdefault(row["market"], []).append(row)
    for group in grouped.values():
        if len(group) < 2:
            for row in group:
                row["rank"] = None
            continue
        ordered = sorted(group, key=lambda item: (item["gross"], item["store"].casefold()))
        last = len(ordered) - 1
        for index, row in enumerate(ordered):
            row["rank"] = index / last
    return rows


def learning_rows(features, outcomes):
    outcome_by_store = {row["store"]: row for row in outcomes}
    joined = []
    for feature in features:
        outcome = outcome_by_store.get(feature["store"])
        if outcome is None:
            continue
        fmt = FORMULA_FOR.get(feature.get("format"), feature.get("format"))
        if fmt not in prior_weights():
            continue
        vector = {}
        for key in FEATURE_KEYS:
            if key == "south_indian":
                vector[key] = feature.get("south_indian_density")
            elif key in {"energy", "reviews", "premium"}:
                vector[key] = feature.get(key)
            elif key == "transport":
                raw = feature.get("transport")
                vector[key] = None if raw is None else max(0.0, min(1.0, float(raw)))
            elif key in {"quality", "anchor", "diversity"}:
                raw = feature.get(key)
                vector[key] = None if raw is None else max(0.0, min(1.0, float(raw)))
            elif key in {
                "aggregator_enabled", "mall_reviews", "anchors", "food_court",
                "restaurants", "residential", "aggregator",
            }:
                vector[key] = feature.get(key)
            else:
                vector[key] = None
        joined.append({
            "store": feature["store"],
            "store_id": feature.get("store_id") or "",
            "market": feature.get("market") or "",
            "format": fmt,
            "gross": outcome.get("gross_per_trading_day"),
            "x": vector,
        })
    return _within_market_ranks(joined)


def _usable_keys(rows):
    keys = []
    for key in FEATURE_KEYS:
        if rows and all(row["x"].get(key) is not None for row in rows):
            keys.append(key)
    return keys


def fit_pooled(groups, priors, steps=800):
    """One non-negative ridge. Formats under 8 stores keep their prior weights."""
    fitting = {fmt: rows for fmt, rows in groups.items() if len(rows) >= MIN_FORMAT_N}
    frozen = sorted(fmt for fmt, rows in groups.items() if len(rows) < MIN_FORMAT_N)
    fitted = {fmt: dict(priors.get(fmt) or _zeros()) for fmt in groups}
    if not fitting:
        return fitted, frozen, []
    keys = _usable_keys([row for rows in fitting.values() for row in rows])
    if not keys:
        return fitted, frozen, keys
    weights = {}
    bounds = {}
    design = {}
    target = {}
    for fmt, rows in fitting.items():
        prior = priors.get(fmt) or _zeros()
        weights[fmt] = np.array([float(prior.get(key, 0.0)) for key in keys], dtype=float)
        bounds[fmt] = np.array([cap_bounds(prior.get(key, 0.0)) for key in keys], dtype=float)
        design[fmt] = np.array([[float(row["x"][key]) for key in keys] for row in rows], dtype=float)
        target[fmt] = np.array([float(row["rank"]) for row in rows], dtype=float)
    step = 0.05
    for _ in range(steps):
        mean = sum(weights.values()) / len(weights)
        updated = {}
        for fmt in fitting:
            residual = design[fmt] @ weights[fmt] - target[fmt]
            gradient = (design[fmt].T @ residual) / max(len(target[fmt]), 1)
            prior_vector = np.array([float((priors.get(fmt) or {}).get(key, 0.0)) for key in keys])
            gradient = gradient + (weights[fmt] - prior_vector) + (weights[fmt] - mean)
            updated[fmt] = np.clip(weights[fmt] - step * gradient, bounds[fmt][:, 0], bounds[fmt][:, 1])
        weights = updated
    for fmt in fitting:
        fitted[fmt] = dict(priors.get(fmt) or _zeros())
        for key, value in zip(keys, weights[fmt]):
            fitted[fmt][key] = round(float(value), 4)
    return fitted, frozen, keys


def _predict(vector, weights, keys):
    """Weighted sum on 0–1. A missing input is left out, not scored as zero."""
    if not keys:
        return None
    present = []
    missing_weight = 0.0
    for key in keys:
        weight = float(weights.get(key, 0.0) or 0.0)
        if weight <= 0:
            continue
        raw = vector.get(key)
        if raw is None:
            missing_weight += weight
            continue
        present.append((float(raw), weight))
    if not present:
        return None
    used = sum(weight for _value, weight in present)
    score = sum(value * weight for value, weight in present)
    if missing_weight and used > 0:
        score = score / used * (used + missing_weight)
    return max(0.0, min(1.0, score))


def _spearman(pairs):
    n = len(pairs)
    if n < 3:
        return None

    def ranks(values):
        order = sorted(range(n), key=lambda index: values[index])
        result = [0.0] * n
        index = 0
        while index < n:
            end = index
            while end + 1 < n and values[order[end + 1]] == values[order[index]]:
                end += 1
            average = (index + end) / 2 + 1
            for cursor in range(index, end + 1):
                result[order[cursor]] = average
            index = end + 1
        return result

    xs = [pair[0] for pair in pairs]
    ys = [pair[1] for pair in pairs]
    rx, ry = ranks(xs), ranks(ys)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    den_x = sum((a - mean_x) ** 2 for a in rx)
    den_y = sum((b - mean_y) ** 2 for b in ry)
    if den_x == 0 or den_y == 0:
        return None
    return round(num / (den_x * den_y) ** 0.5, 2)


def leave_one_out(ranked, priors):
    usable = [row for row in ranked if row.get("rank") is not None]
    backtest = []
    errors = []
    for held in usable:
        groups = {}
        for row in usable:
            if row["store"] == held["store"]:
                continue
            groups.setdefault(row["format"], []).append(row)
        for fmt in prior_weights():
            groups.setdefault(fmt, [])
        fitted, frozen, keys = fit_pooled(groups, priors, steps=400)
        weights = fitted.get(held["format"]) or {}
        # Mall stays on its prior until it has 8 stores. Score that prior on the
        # mall inputs, which the pooled fit never sees.
        if held["format"] == "mall" and held["format"] in frozen:
            predict_keys = list(weights)
        else:
            predict_keys = keys
        predicted = _predict(held["x"], weights, predict_keys)
        actual = held["rank"]
        gap = None if predicted is None else abs(predicted - actual)
        errors.append(gap)
        backtest.append({
            "store": held["store"],
            "store_id": held.get("store_id") or "",
            "market": held.get("market") or "",
            "format": held["format"],
            "actual_rank": round(actual, 4),
            "predicted_rank": None if predicted is None else round(predicted, 4),
            "decile_gap": None if gap is None else round(gap / DECILE, 2),
            "miss": gap is not None and gap > MISS_DECILES * DECILE,
        })
    present = [error for error in errors if error is not None]
    mae = None if not present else round(sum(present) / len(present), 4)
    return backtest, mae


def refit_model(features, outcomes, month=None, prior_version="prior", priors=None, version=None):
    month = month or (features[0]["as_of"] if features else latest_sales_month())
    priors = priors or prior_weights()
    ranked = [row for row in learning_rows(features, outcomes) if row.get("rank") is not None]
    groups = {}
    for row in ranked:
        groups.setdefault(row["format"], []).append(row)
    for fmt in priors:
        groups.setdefault(fmt, [])
    fitted, frozen, keys = fit_pooled(groups, priors, steps=800)
    pairs = []
    for row in ranked:
        predicted = _predict(row["x"], fitted.get(row["format"]) or {}, keys)
        if predicted is not None:
            pairs.append((predicted, row["rank"]))
    spearman = _spearman(pairs)
    backtest, mae = leave_one_out(ranked, priors)
    counts = {fmt: len(groups.get(fmt) or []) for fmt in priors}
    return {
        "version": version or f"v{month}",
        "status": "proposed",
        "as_of": month,
        "prior_version": prior_version,
        "n": len(ranked),
        "spearman": spearman,
        "loo_mae": mae,
        "min_format_n": MIN_FORMAT_N,
        "move_cap": MOVE_CAP,
        "format_counts": counts,
        "frozen_formats": frozen,
        "features_used": keys,
        "weights": fitted,
        "prior_weights": priors,
        "backtest": backtest,
        "approved_at": None,
    }


def model_dir():
    return location_root() / "models"


def model_path(version):
    name = version if str(version).startswith("v") else f"v{version}"
    return model_dir() / f"{name}.json"


def save_model(payload):
    path = model_path(payload["version"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_model(version):
    path = model_path(version)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_models():
    folder = model_dir()
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("v*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        found.append(payload)
    return found


WEIGHT_LABELS = {
    "energy": "Energy",
    "reviews": "Review volume",
    "transport": "Transport",
    "premium": "Premium brands",
    "diversity": "Diversity",
    "quality": "Quality",
    "anchor": "Anchor",
    "restaurants": "Delivering restaurants",
    "residential": "Residential density",
    "aggregator": "Nearest delivery sales",
    "aggregator_enabled": "Aggregator-enabled",
    "mall_reviews": "Mall reviews",
    "anchors": "In-mall anchors",
    "food_court": "Food court",
    "distance": "Distance to the station",
    "ridership": "Station ridership",
    "south_indian": "South Indian density",
}

FORMAT_WORD = {
    "high_street": "high-street",
    "mall": "mall",
    "metro": "metro",
    "cloud_kitchen": "cloud kitchen",
}

FORMAT_ORDER = ("high_street", "mall", "metro", "cloud_kitchen")


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _when(value):
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M UTC")


@contextmanager
def _db_context():
    from flask import has_app_context

    if has_app_context():
        yield
        return
    from app import create_app

    with create_app().app_context():
        yield


def _approval_query():
    from app.models import LocationModelApproval

    return LocationModelApproval.query.order_by(
        LocationModelApproval.approved_at.desc(),
        LocationModelApproval.id.desc(),
    )


def _current_approval():
    from app.models import LocationModelApproval

    return (
        LocationModelApproval.query.filter_by(status="approved")
        .order_by(LocationModelApproval.approved_at.desc(), LocationModelApproval.id.desc())
        .first()
    )


def _overlay_approval(payload, row):
    payload = dict(payload)
    payload["status"] = row.status
    payload["approved_at"] = "" if row.approved_at is None else row.approved_at.date().isoformat()
    payload["approved_by"] = row.approved_by or ""
    return payload


def latest_approved():
    """The live model. Read from the approval table, then the JSON for its weights."""
    with _db_context():
        row = _current_approval()
        if row is None:
            return None
        payload = load_model(row.version)
        if payload is None:
            return None
        return _overlay_approval(payload, row)


def latest_proposed():
    with _db_context():
        row = _current_approval()
        live = "" if row is None else row.version
    found = []
    for model in list_models():
        version = model.get("version") or ""
        if version and version == live:
            continue
        found.append(model)
    if not found:
        return None
    found.sort(key=lambda model: model.get("version") or "")
    return found[-1]


def current_model_label():
    model = latest_approved()
    if model is None:
        return "prior"
    return model.get("version") or "prior"


def clear_approvals():
    """Drop approval rows. Tests use this so one run does not leak into the next."""
    from app.extensions import db
    from app.models import LocationModelApproval

    with _db_context():
        LocationModelApproval.query.delete()
        db.session.commit()


def approve_model(version, email):
    """Record an approval. The JSON file is not rewritten."""
    payload = load_model(version)
    if payload is None or not str(email or "").strip():
        return None
    from app.extensions import db
    from app.models import LocationModelApproval

    version_name = payload.get("version") or version
    with _db_context():
        current = _current_approval()
        if current is not None and current.version == version_name:
            return _overlay_approval(payload, current)
        row = LocationModelApproval(
            version=version_name,
            status="approved",
            approved_by=str(email).strip(),
            approved_at=_utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        saved = _overlay_approval(payload, row)
    from app.site_pattern import clear_cache

    clear_cache()
    return saved


def revert_model(email):
    """Undo the live approval. The previous approval stays, or the prior weights."""
    if not str(email or "").strip():
        return None
    from app.extensions import db

    with _db_context():
        row = _current_approval()
        if row is None:
            return None
        row.status = "reverted"
        row.reverted_at = _utcnow()
        row.reverted_by = str(email).strip()
        db.session.commit()
        live = current_model_label()
        version = row.version
    from app.site_pattern import clear_cache

    clear_cache()
    return {"version": version, "live": live}


def approval_log():
    with _db_context():
        rows = list(_approval_query())
    events = []
    for row in rows:
        events.append({
            "action": "Approved",
            "version": row.version,
            "email": row.approved_by or "",
            "at": row.approved_at,
            "when": _when(row.approved_at),
        })
        if row.reverted_at is not None:
            events.append({
                "action": "Reverted",
                "version": row.version,
                "email": row.reverted_by or "",
                "at": row.reverted_at,
                "when": _when(row.reverted_at),
            })
    events.sort(key=lambda event: event["at"] or datetime.min, reverse=True)
    return events


def _pct(weight):
    value = float(weight or 0) * 100
    if abs(value - round(value)) < 0.05:
        return f"{round(value):.0f}%"
    return f"{value:.1f}%"


def spearman_words(value):
    if value is None:
        return "Spearman is not available yet."
    shown = f"{float(value):.2f}"
    magnitude = abs(float(value))
    if magnitude >= 0.7:
        how = "very well"
    elif magnitude >= 0.4:
        how = "moderately well"
    elif magnitude >= 0.2:
        how = "only loosely"
    else:
        how = "poorly"
    if float(value) < 0:
        return f"Spearman {shown} means the model ranks stores {how}, and in the wrong direction."
    return f"Spearman {shown} means the model ranks stores {how}."


def error_words(mae):
    if mae is None:
        return "There is no leave-one-store-out check yet."
    deciles = float(mae) / DECILE
    shown = f"{deciles:.0f}" if abs(deciles - round(deciles)) < 0.05 else f"{deciles:.1f}"
    return (
        f"Leave-one-store-out error {float(mae):.2f} is about {shown} rank-deciles, "
        "so a held-out store is usually that far off."
    )


def _format_phrase(keys):
    words = [FORMAT_WORD.get(key, key.replace("_", " ")) for key in keys]
    if not words:
        return "no sites"
    if len(words) == 1:
        return f"{words[0]} sites"
    if len(words) == 2:
        return f"{words[0]} and {words[-1]} sites"
    return ", ".join(words[:-1]) + f" and {words[-1]} sites"


def _short_store(name):
    text = re.sub(r"^Dosa Coffee\s*-?\s*", "", str(name or ""))
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = " ".join(text.split())
    folded = text.casefold()
    if "pacific" in folded:
        return "Pacific Mall"
    if "ideal plaza" in folded:
        return "Ideal Plaza"
    if "rosedale" in folded:
        return "Rosedale"
    return text


def _weight_rows(before, after, frozen):
    rows = []
    keys = list(WEIGHT_LABELS)
    for key in list(before or {}) + list(after or {}):
        if key not in keys:
            keys.append(key)
    for key in keys:
        old = float((before or {}).get(key, 0) or 0)
        new = float((after or {}).get(key, 0) or 0)
        if abs(old) < 1e-9 and abs(new) < 1e-9:
            continue
        rows.append({
            "key": key,
            "label": WEIGHT_LABELS.get(key, key.replace("_", " ")),
            "before": _pct(old),
            "after": _pct(new),
            "changed": abs(old - new) >= 0.0005,
            "frozen": frozen,
        })
    return rows


def _frozen_note(model):
    frozen = [key for key in FORMAT_ORDER if key in set(model.get("frozen_formats") or [])]
    if not frozen:
        return ""
    version = model.get("version") or "this model"
    note = f"{_format_phrase(frozen).replace(' sites', '').capitalize()} are frozen in {version}."
    if len(frozen) == 1:
        word = FORMAT_WORD.get(frozen[0], frozen[0])
        note = f"{word[:1].upper()}{word[1:]} is frozen in {version}."
    note += " Their weights stay at the prior because each format has fewer than 8 stores."
    if "mall" in frozen:
        misses = [
            row for row in (model.get("backtest") or [])
            if row.get("format") == "mall" and row.get("decile_gap") is not None
        ]
        misses.sort(key=lambda row: -float(row.get("decile_gap") or 0))
        names = []
        for row in misses:
            if not row.get("miss"):
                continue
            label = _short_store(row.get("store"))
            if label and label not in names:
                names.append(label)
            if len(names) == 3:
                break
        note += (
            " The mall score uses the prior weights, including aggregator-enabled, "
            "mall reviews and anchors."
        )
        if names:
            listed = _format_phrase_names(names)
            verb = "is" if len(names) == 1 else "are"
            note += f" {listed} {verb} the big misses."
    return note


def _format_phrase_names(names):
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _score_moves(model):
    from app.site_pattern import load_board

    weights = model.get("weights") or {}
    moves = []
    for store in load_board().get("stores") or []:
        formula = FORMULA_FOR.get(store.get("format"))
        pattern = store.get("pattern") or {}
        old = pattern.get("score")
        if not formula or formula not in weights or old is None:
            continue
        parts = []
        for part in pattern.get("parts") or []:
            key = part.get("key")
            copy = {
                "key": key,
                "label": part.get("label"),
                "weight": float((weights.get(formula) or {}).get(key, part.get("weight") or 0) or 0),
                "value": part.get("value"),
                "detail": part.get("detail") or "",
            }
            if part.get("status") == DATA_COMING and part.get("value") is None:
                copy["status"] = DATA_COMING
            parts.append(copy)
        new = blend(parts).get("score")
        if new is None:
            continue
        delta = round(float(new) - float(old), 1)
        if abs(delta) < 0.05:
            continue
        moves.append({
            "store": store.get("name") or "",
            "old": old,
            "new": new,
            "delta": delta,
            "delta_label": f"{delta:+.1f}",
        })
    up = sorted((row for row in moves if row["delta"] > 0), key=lambda row: -row["delta"])[:5]
    down = sorted((row for row in moves if row["delta"] < 0), key=lambda row: row["delta"])[:5]
    return up, down


def proposal_changes(model):
    """Before and after weights, the stores that move, and the confirm line."""
    if not model:
        return None
    frozen = set(model.get("frozen_formats") or [])
    before = model.get("prior_weights") or {}
    after = model.get("weights") or {}
    formats = []
    moving = []
    for key in FORMAT_ORDER:
        if key not in after and key not in before:
            continue
        is_frozen = key in frozen
        rows = _weight_rows(before.get(key), after.get(key), is_frozen)
        changed = any(row["changed"] for row in rows)
        if changed and not is_frozen:
            moving.append(key)
        formats.append({
            "key": key,
            "label": FORMAT_WORD.get(key, key.replace("_", " ")).capitalize() if key != "high_street" else "High street",
            "frozen": is_frozen,
            "rows": rows,
        })
    # High street label: "High street". cloud kitchen capitalize only first word via FORMAT_WORD title.
    for item in formats:
        if item["key"] == "cloud_kitchen":
            item["label"] = "Cloud kitchen"
        elif item["key"] == "metro":
            item["label"] = "Metro"
        elif item["key"] == "mall":
            item["label"] = "Mall"
    version = model.get("version") or "this model"
    if moving:
        confirm = (
            f"Approve {version}? Live scores will change for {_format_phrase(moving)}. You can undo this."
        )
    else:
        confirm = (
            f"Approve {version}? Live scores will not change, because every format is frozen. You can undo this."
        )
    up, down = _score_moves(model)
    return {
        "formats": formats,
        "moving": moving,
        "confirm": confirm,
        "spearman_words": spearman_words(model.get("spearman")),
        "error_words": error_words(model.get("loo_mae")),
        "frozen_note": _frozen_note(model),
        "up": up,
        "down": down,
    }


def write_refit(month=None, version=None):
    month = month or latest_sales_month()
    feature_path = location_root() / "store_features" / f"{month}.csv"
    outcome_path = location_root() / "outcomes" / f"{month}.csv"
    features = _read(feature_path)
    outcomes = _read(outcome_path)
    cleaned_features = []
    for row in features:
        cleaned = dict(row)
        for key in (
            "energy_of_6", "quality", "anchor", "diversity", "transport", "nearby_reviews",
            "classic_score", "energy", "reviews", "premium", "cuisine_types",
            "n_anchor_brands_500m", "n_fnb_chains_500m", "competitor_count",
            "south_indian_density", "google_rating", "lat", "lng",
            "aggregator_enabled", "mall_reviews", "anchors", "food_court",
            "restaurants", "residential", "aggregator",
        ):
            if key in cleaned:
                cleaned[key] = _float(cleaned.get(key))
        cleaned_features.append(cleaned)
    cleaned_outcomes = []
    for row in outcomes:
        cleaned = dict(row)
        cleaned["gross_per_trading_day"] = _float(row.get("gross_per_trading_day"))
        cleaned_outcomes.append(cleaned)
    approved = latest_approved()
    priors = prior_weights()
    prior_version = "prior"
    if approved and approved.get("weights"):
        priors = approved["weights"]
        prior_version = approved.get("version") or "prior"
    payload = refit_model(
        cleaned_features, cleaned_outcomes, month, prior_version, priors, version=version,
    )
    return save_model(payload)


def site_id_for(lat, lng, fmt):
    return f"{fmt}-{float(lat):.5f}-{float(lng):.5f}"


def log_prediction(site, lat, lng, fmt, model_version, score, parts):
    if not _should_log():
        return None
    bits = []
    for part in parts or []:
        status = part.get("status") or ""
        if status == "in" and part.get("points") is not None:
            bits.append(f"{part.get('label')}: {part.get('points')}")
        elif status:
            bits.append(f"{part.get('label')}: {status}")
    row = {
        "scored_at": datetime.now().replace(microsecond=0).isoformat(sep=" "),
        "site_id": site_id_for(lat, lng, fmt),
        "site": site or "",
        "lat": lat,
        "lng": lng,
        "format": fmt,
        "model_version": model_version or "prior",
        "score": score,
        "breakdown": "; ".join(bits),
    }
    path = location_root() / "predictions.csv"
    existed = path.is_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PREDICTION_COLUMNS), lineterminator="\n")
        if not existed:
            writer.writeheader()
        writer.writerow({column: _cell(row.get(column)) for column in PREDICTION_COLUMNS})
    return row


def _ensure_openings():
    path = location_root() / "openings.csv"
    if path.is_file():
        return path
    _write(path, OPENING_COLUMNS, [])
    return path


def opening_tracks():
    path = _ensure_openings()
    predictions = _read(location_root() / "predictions.csv")
    by_site = {}
    for row in predictions:
        by_site.setdefault(row.get("site_id") or "", []).append(row)
    daily = _daily_rows()
    tracks = []
    for opening in _read(path):
        site_id = (opening.get("site_id") or "").strip()
        store_id = (opening.get("store_id") or "").strip()
        opened = _parse_day(opening.get("open_date"))
        logged = by_site.get(site_id) or []
        prediction = logged[-1] if logged else None
        gross_per = None
        days_tracked = None
        if opened is not None and store_id:
            window_end = opened + timedelta(days=89)
            today = date.today()
            if today < window_end:
                window_end = today
            days_tracked = max((window_end - opened).days + 1, 0)
            master = next((row for row in load_rows() if row.get("store_id") == store_id), None)
            name = (master or {}).get("posist_name") or ""
            grosses = []
            for row in daily:
                if _store_key(row.get("store")) != name:
                    continue
                day = _parse_day(row.get("date"))
                gross = _float(row.get("gross"))
                if day is None or gross is None or day < opened or day > opened + timedelta(days=89):
                    continue
                grosses.append(gross)
            if grosses:
                gross_per = sum(grosses) / len(grosses)
        tracks.append({
            "site_id": site_id,
            "store_id": store_id,
            "open_date": "" if opened is None else opened.isoformat(),
            "site": "" if prediction is None else prediction.get("site") or "",
            "predicted_score": None if prediction is None else _float(prediction.get("score")),
            "model_version": "" if prediction is None else prediction.get("model_version") or "",
            "days_tracked": days_tracked,
            "gross_per_trading_day": gross_per,
        })
    return tracks


def _undo_target():
    with _db_context():
        rows = [row for row in _approval_query() if row.status == "approved"]
    if len(rows) < 2:
        return "the prior weights"
    return rows[1].version


def model_page():
    proposed = latest_proposed()
    approved = latest_approved()
    discussed = proposed or approved
    backtest = (discussed or {}).get("backtest") or []
    misses = [row for row in backtest if row.get("miss")]
    live = current_model_label()
    return {
        "live_label": live,
        "approved": approved,
        "proposed": proposed,
        "changes": proposal_changes(proposed) if proposed else None,
        "backtest": backtest,
        "misses": misses,
        "log": approval_log(),
        "undo_target": _undo_target() if approved else "the prior weights",
        "openings": opening_tracks(),
        "prediction_count": len(_read(location_root() / "predictions.csv")),
    }
