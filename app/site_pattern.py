"""Format-aware site scores from the October 2026 site study.

A missing input is left out of the formula. It is never scored as zero.
Anchor is kept visible at weight 0 because it saturates and does not track sales.
"""

import csv
import math
import os
import re
from pathlib import Path

REPIN_METRES = 300
CANNIBAL_METRES = 2000
NEAR_STORE_METRES = 5000
PREMIUM_METRES = 300

DATA_COMING = "data coming"
NOT_USED = "not used"

FORMAT_LABELS = {
    "high_street": "High street",
    "mall": "Mall food court",
    "cloud_kitchen": "Cloud kitchen",
    "metro": "Metro / transit unit",
    "office_complex": "Office complex",
    "other_club": "Club",
    "other_truck": "Food truck",
}

# Office complexes use the high-street formula. Club and truck are not comparable.
# Shalimar Bagh is a metro-station unit: commuter footfall, not restaurant reviews.
FORMULA_FOR = {
    "high_street": "high_street",
    "office_complex": "high_street",
    "mall": "mall",
    "cloud_kitchen": "cloud_kitchen",
    "metro": "metro",
}
METRO_STORES = {"Shalimar Bagh (02/0015)"}

# Review energy is deliberately lighter than on a high street. Footfall is the station.
METRO_WEIGHTS = {
    "distance": 0.20,
    "ridership": 0.20,
    "energy": 0.15,
    "reviews": 0.05,
    "transport": 0.15,
    "premium": 0.10,
    "diversity": 0.10,
    "quality": 0.05,
    "anchor": 0,
}

# Longer names first so "cafe coffee day" is not also read as a short alias.
PREMIUM_BRANDS = (
    ("cafe coffee day", 0.15),
    ("blue tokai", 0.25),
    ("third wave", 0.25),
    ("burger king", 0.30),
    ("bikanervala", 0.25),
    ("haldiram", 0.25),
    ("starbucks", 0.35),
    ("mcdonald", 0.30),
    ("chaayos", 0.30),
    ("pvr", 0.20),
    ("inox", 0.20),
    ("ccd", 0.15),
)
MALL_ANCHOR_KEYS = ("mcdonald", "burger king", "starbucks", "pvr", "inox")

_CACHE = {}


def data_dir():
    override = os.getenv("SITE_PATTERN_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "data" / "site_pattern"


def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _blank(value):
    return value is None or str(value).strip() == ""


def _float(value):
    if _blank(value):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _read(path):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return sorted_values[int(position)]
    weight = position - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def scale_log(value, low_log, high_log):
    """Map a count onto 0–1 between two log10 anchors. Blank stays blank."""
    if value is None:
        return None
    if value <= 0:
        return 0.0
    if low_log is None or high_log is None or high_log <= low_log:
        return 1.0
    return max(0.0, min(1.0, (math.log10(value) - low_log) / (high_log - low_log)))


def _log_band(values):
    logs = sorted(math.log10(value) for value in values if value is not None and value > 0)
    if not logs:
        return None, None
    return _percentile(logs, 0.05), _percentile(logs, 0.95)


def blend(parts):
    """Weighted 0–10 score. Parts with value None are left out, not treated as zero."""
    included = [part for part in parts if part.get("value") is not None and part.get("weight", 0) > 0]
    weight_sum = sum(part["weight"] for part in included)
    score = None
    if weight_sum > 0:
        score = round(10 * sum(part["weight"] * part["value"] for part in included) / weight_sum, 1)
    shown = []
    for part in parts:
        copy = dict(part)
        if part.get("weight", 0) <= 0 and part.get("status") != DATA_COMING:
            copy["status"] = NOT_USED
            copy["points"] = None
        elif part.get("value") is None:
            copy["status"] = DATA_COMING
            copy["points"] = None
        else:
            copy["status"] = "in"
            copy["points"] = round(10 * part["weight"] * part["value"] / weight_sum, 1) if weight_sum else None
        copy["weight_pct"] = round(part.get("weight", 0) * 100)
        shown.append(copy)
    return {"score": score, "parts": shown, "weight_sum": weight_sum}


def _brand_key(name):
    text = str(name or "").casefold().replace("'", "").replace("’", "")
    for key, _weight in PREMIUM_BRANDS:
        if key in text:
            return key
    return ""


def premium_unit(names_within_range):
    """Sum of brand weights, capped at 1. Each brand counts once."""
    if names_within_range is None:
        return None
    seen = set()
    total = 0.0
    for name in names_within_range:
        key = _brand_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        total += dict(PREMIUM_BRANDS)[key]
    return min(1.0, total)


def mall_anchor_unit(names_within_range):
    if names_within_range is None:
        return None
    found = set()
    for name in names_within_range:
        key = _brand_key(name)
        if key in MALL_ANCHOR_KEYS:
            found.add(key)
    return min(1.0, len(found) / 4)


def parse_neighbour_brands(text, max_metres):
    """Names from 'Starbucks (154m); Subway (108m)'. Blank text is unknown, not empty."""
    if _blank(text):
        return None
    names = []
    for piece in str(text).split(";"):
        piece = piece.strip()
        if not piece:
            continue
        metres = None
        if piece.endswith(")") and "(" in piece:
            label, rest = piece.rsplit("(", 1)
            token = rest[:-1].strip().casefold().replace("m", "").replace(",", "")
            try:
                metres = float(token)
            except ValueError:
                metres = None
            piece = label.strip()
        if metres is None or metres <= max_metres:
            names.append(piece)
    return names


def city_bucket(region, location_name="", lat=None):
    region_text = str(region or "").casefold()
    if region_text in {"east", "kolkata"}:
        return "Kolkata"
    if region_text in {"north", "ncr", "delhi", "delhi ncr"}:
        return "NCR"
    text = str(location_name or "").casefold()
    if any(word in text for word in ("kolkata", "howrah", "bidhannagar", "salt lake")):
        return "Kolkata"
    if any(word in text for word in ("delhi", "gurgaon", "gurugram", "noida", "faridabad", "ghaziabad", "ncr")):
        return "NCR"
    if lat is not None and lat < 26:
        return "Kolkata"
    return "NCR"


def high_street_weights(bucket):
    # Kolkata frees 10 points of co-location and gives them to Energy.
    if bucket == "Kolkata":
        return {"energy": 0.45, "reviews": 0.15, "transport": 0.15, "premium": 0.05, "diversity": 0.10, "quality": 0.05, "anchor": 0}
    return {"energy": 0.35, "reviews": 0.15, "transport": 0.15, "premium": 0.15, "diversity": 0.10, "quality": 0.05, "anchor": 0}


def _part(key, label, weight, value, detail):
    return {"key": key, "label": label, "weight": weight, "value": value, "detail": detail}


def delivery_parts(restaurants, residential, aggregator_sales, sales_band):
    low, high = sales_band
    return [
        _part(
            "restaurants",
            "Delivering restaurants within 3 km",
            0.40,
            scale_log(restaurants, None, None) if restaurants is not None else None,
            None if restaurants is None else f"{int(restaurants)} restaurants",
        ),
        _part(
            "residential",
            "Residential density within 3 km",
            0.40,
            None if residential is None else max(0.0, min(1.0, residential)),
            None if residential is None else "Density on a 0–1 scale",
        ),
        _part(
            "aggregator",
            "Nearest store's delivery sales",
            0.20,
            scale_log(aggregator_sales, low, high),
            None if aggregator_sales is None else "Delivery sales at the nearest store",
        ),
    ]


def high_street_parts(signals, bucket, review_band):
    weights = high_street_weights(bucket)
    low, high = review_band
    return [
        _part("energy", "Energy", weights["energy"], signals.get("energy"), signals.get("energy_detail") or ""),
        _part("reviews", "Review volume within 300 m", weights["reviews"], scale_log(signals.get("reviews"), low, high), signals.get("reviews_detail") or ""),
        _part("transport", "Transport", weights["transport"], signals.get("transport"), signals.get("transport_detail") or ""),
        _part("premium", "Premium-brand co-location", weights["premium"], signals.get("premium"), signals.get("premium_detail") or ""),
        _part("diversity", "Diversity", weights["diversity"], signals.get("diversity"), signals.get("diversity_detail") or ""),
        _part("quality", "Quality", weights["quality"], signals.get("quality"), signals.get("quality_detail") or ""),
        _part("anchor", "Anchor", weights["anchor"], signals.get("anchor"), "Dropped. It is 1 for almost every store."),
    ]


def station_distance_unit(metres):
    """Closer to a station exit scores higher. Blank stays blank, not zero."""
    if metres is None:
        return None
    if metres <= 80:
        return 1.0
    if metres <= 200:
        return 0.8
    if metres <= 400:
        return 0.5
    if metres <= 800:
        return 0.25
    return 0.0


def metro_parts(signals, review_band):
    weights = METRO_WEIGHTS
    low, high = review_band
    ridership = signals.get("ridership")
    source = (signals.get("ridership_source") or "").strip()
    if ridership is None:
        ridership_detail = ""
    elif source:
        ridership_detail = f"{int(ridership):,} a day. Source: {source}"
    else:
        ridership_detail = f"{int(ridership):,} a day"
    return [
        _part(
            "distance",
            "Distance to the nearest metro or rail exit",
            weights["distance"],
            station_distance_unit(signals.get("station_m")),
            signals.get("station_detail") or "",
        ),
        _part(
            "ridership",
            "Station ridership",
            weights["ridership"],
            scale_log(ridership, *(signals.get("ridership_band") or (None, None))),
            ridership_detail,
        ),
        _part("energy", "Energy", weights["energy"], signals.get("energy"), signals.get("energy_detail") or ""),
        _part("reviews", "Review volume within 300 m", weights["reviews"], scale_log(signals.get("reviews"), low, high), signals.get("reviews_detail") or ""),
        _part("transport", "Transport", weights["transport"], signals.get("transport"), signals.get("transport_detail") or ""),
        _part("premium", "Premium-brand co-location", weights["premium"], signals.get("premium"), signals.get("premium_detail") or ""),
        _part("diversity", "Diversity", weights["diversity"], signals.get("diversity"), signals.get("diversity_detail") or ""),
        _part("quality", "Quality", weights["quality"], signals.get("quality"), signals.get("quality_detail") or ""),
        _part("anchor", "Anchor", weights["anchor"], signals.get("anchor"), "Dropped. It is 1 for almost every store."),
    ]


def mall_parts(signals, delivery):
    return [
        _part("aggregator_enabled", "Aggregator-enabled", 0.30, signals.get("aggregator_enabled"), signals.get("aggregator_detail") or ""),
        _part("delivery", "Delivery potential", 0.25, None if delivery["score"] is None else delivery["score"] / 10, ""),
        _part("mall_reviews", "Mall's own reviews", 0.20, scale_log(signals.get("mall_reviews"), *signals.get("mall_review_band", (None, None))), signals.get("mall_reviews_detail") or ""),
        _part("anchors", "In-mall anchors", 0.15, signals.get("mall_anchors"), signals.get("mall_anchor_detail") or ""),
        _part("transport", "Transport", 0.10, signals.get("transport"), signals.get("transport_detail") or ""),
    ]


def score_signals(fmt, signals, bucket, bands):
    """Return the format score, its breakdown, and the separate delivery score."""
    delivery = blend(delivery_parts(
        signals.get("delivering_restaurants"),
        signals.get("residential"),
        signals.get("nearest_delivery_sales"),
        bands["delivery"],
    ))
    formula = FORMULA_FOR.get(fmt)
    if formula == "high_street":
        pattern = blend(high_street_parts(signals, bucket, bands["reviews"]))
    elif formula == "mall":
        pattern = blend(mall_parts(signals, delivery))
    elif formula == "cloud_kitchen":
        pattern = delivery
    elif formula == "metro":
        pattern = blend(metro_parts(signals, bands["reviews"]))
    else:
        pattern = {"score": None, "parts": [], "weight_sum": 0}
    return {"pattern": pattern, "delivery": delivery, "bucket": bucket}


def _spearman(pairs):
    n = len(pairs)
    if n < 3:
        return None, n

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
    den = math.sqrt(sum((a - mean_x) ** 2 for a in rx) * sum((b - mean_y) ** 2 for b in ry))
    if den == 0:
        return None, n
    return round(num / den, 2), n


def _correlation(rows, key):
    pairs = [
        (row[key], row["gross_per_day"])
        for row in rows
        if row.get(key) is not None and row.get("gross_per_day") is not None
    ]
    rho, n = _spearman(pairs)
    return {"rho": rho, "n": n}


def _nearest_store(lat, lon, stores, skip_name=None, max_metres=None):
    best = None
    best_distance = None
    for store in stores:
        if skip_name and store["name"] == skip_name:
            continue
        if store.get("lat") is None or store.get("lon") is None:
            continue
        distance = haversine_m(lat, lon, store["lat"], store["lon"])
        if max_metres is not None and distance > max_metres:
            continue
        if best_distance is None or distance < best_distance:
            best = store
            best_distance = distance
    return best, best_distance


def _signals_from_row(row, stores, bands):
    names = parse_neighbour_brands(row.get("neighbour_brands"), PREMIUM_METRES)
    if row.get("lat") is None or row.get("lon") is None:
        nearest, distance = None, None
    else:
        nearest, distance = _nearest_store(row["lat"], row["lon"], stores, skip_name=row["name"], max_metres=NEAR_STORE_METRES)
    energy = _float(row.get("energy_of_6"))
    transport = _float(row.get("transport"))
    quality = _float(row.get("quality"))
    diversity = _float(row.get("diversity"))
    anchor = _float(row.get("anchor"))
    reviews = _float(row.get("nearby_reviews"))
    share = _float(row.get("aggregator_share"))
    nearest_sales = None if nearest is None else nearest.get("delivery_gross_per_day")
    return {
        "energy": None if energy is None else max(0.0, min(1.0, energy / 6)),
        "energy_detail": None if energy is None else f"{energy:g} / 6",
        "reviews": reviews,
        "reviews_detail": None if reviews is None else f"{int(reviews)} reviews",
        "transport": None if transport is None else max(0.0, min(1.0, transport)),
        "transport_detail": None if transport is None else f"{transport:g} / 1",
        "premium": None if names is None else premium_unit(names),
        "premium_detail": None if names is None else f"{len(names)} brands within 300 m",
        "diversity": None if diversity is None else max(0.0, min(1.0, diversity)),
        "diversity_detail": None if diversity is None else f"{diversity:g} / 1",
        "quality": None if quality is None else max(0.0, min(1.0, quality)),
        "quality_detail": None if quality is None else f"{quality:g} / 1",
        "anchor": None if anchor is None else max(0.0, min(1.0, anchor)),
        "aggregator_enabled": None if share is None else (1.0 if share > 0 else 0.0),
        "aggregator_detail": None if share is None else ("On Swiggy or Zomato" if share > 0 else "No Swiggy or Zomato sales"),
        "mall_reviews": None,
        "mall_reviews_detail": "",
        "mall_review_band": bands["reviews"],
        "mall_anchors": None if names is None else mall_anchor_unit(names),
        "mall_anchor_detail": "",
        "station_m": None,
        "station_detail": "",
        "ridership": None,
        "ridership_source": "",
        "ridership_band": bands.get("ridership", (None, None)),
        "delivering_restaurants": None,
        "residential": None,
        "nearest_delivery_sales": nearest_sales,
        "nearest_store": None if nearest is None else nearest["name"],
        "nearest_store_m": None if distance is None else round(distance),
    }


def _peer_rows(store, stores):
    formula = FORMULA_FOR.get(store["format"])
    if formula is None or store.get("pattern_score") is None:
        return []
    peers = []
    for other in stores:
        if other["name"] == store["name"]:
            continue
        if FORMULA_FOR.get(other["format"]) != formula:
            continue
        if other.get("pattern_score") is None:
            continue
        peers.append(other)
    peers.sort(key=lambda other: (abs(other["pattern_score"] - store["pattern_score"]), other["name"].casefold()))
    return peers[:3]


def load_board(directory=None):
    directory = Path(directory) if directory else data_dir()
    key = str(directory)
    stamps = []
    for name in (
        "site_pattern_matrix.csv",
        "lf_pin_check.csv",
        "candidate_clusters.csv",
        "neighbour_brand_outlets.csv",
        "location_finder_ncr.csv",
        "metro_ridership.csv",
    ):
        path = directory / name
        stamps.append(path.stat().st_mtime if path.is_file() else None)
    cached = _CACHE.get(key)
    if cached and cached[0] == tuple(stamps):
        return cached[1]
    board = _build_board(directory)
    _CACHE[key] = (tuple(stamps), board)
    return board


def clear_cache():
    _CACHE.clear()


def _leading_number(value):
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    return match.group(0)


def _earlier_score(note):
    match = re.search(r"earlier\s+[^.]*?scored\s+(\d+(?:\.\d+)?)", str(note or ""), re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _apply_ncr_scores(raw_rows, directory):
    """NCR classic scores come from the latest pin file, not the older study copy."""
    fresh = {}
    for row in _read(directory / "location_finder_ncr.csv"):
        name = (row.get("posist_store") or "").strip()
        if name:
            fresh[name] = row
    for row in raw_rows:
        update = fresh.get(row["name"])
        if not update:
            continue
        score = _float(update.get("score_out_of_10"))
        if score is not None:
            row["classic_score"] = score
        energy = _leading_number(update.get("Energy"))
        quality = _leading_number(update.get("Quality"))
        anchor = _leading_number(update.get("Anchor"))
        diversity = _leading_number(update.get("Diversity"))
        transport = _leading_number(update.get("Transport"))
        if energy is not None:
            row["energy_of_6"] = energy
        if quality is not None:
            row["quality"] = quality
        if anchor is not None:
            row["anchor"] = anchor
        if diversity is not None:
            row["diversity"] = diversity
        if transport is not None:
            row["transport"] = transport
        reviews = _float(update.get("Reviews"))
        if reviews is not None:
            row["nearby_reviews"] = reviews
        note = (update.get("note") or "").strip()
        row["score_note"] = note
        row["earlier_score"] = _earlier_score(note)
        if "exact google pin" in note.casefold():
            row["pin_m"] = 0
    for row in raw_rows:
        if row["name"] in METRO_STORES:
            row["format"] = "metro"


def load_ridership(directory):
    rows = []
    for raw in _read(Path(directory) / "metro_ridership.csv"):
        daily = _float(raw.get("daily_ridership"))
        station = (raw.get("station") or "").strip()
        if not station:
            continue
        rows.append({
            "station": station,
            "city": (raw.get("city") or "").strip(),
            "line": (raw.get("line") or "").strip(),
            "daily": daily,
            "source": (raw.get("source") or "").strip(),
            "as_of": (raw.get("as_of") or "").strip(),
        })
    return rows


def match_ridership(station_name, rows):
    text = " ".join(str(station_name or "").casefold().split())
    if not text:
        return None
    for row in rows:
        station = " ".join(row["station"].casefold().split())
        if station and station in text and row.get("daily") is not None:
            return row
    return None


def _build_board(directory):
    pins = {row["Store"]: _float(row.get("lf_pin_vs_actual_m")) for row in _read(directory / "lf_pin_check.csv")}
    raw_rows = []
    for raw in _read(directory / "site_pattern_matrix.csv"):
        raw_rows.append({
            "name": (raw.get("Store") or "").strip(),
            "region": (raw.get("Region") or "").strip(),
            "format": (raw.get("format") or "").strip(),
            "lat": _float(raw.get("lat")),
            "lon": _float(raw.get("lon")),
            "gross_30d": _float(raw.get("gross_30d")),
            "gross_per_day": _float(raw.get("gross_per_day")),
            "delivery_gross_per_day": _float(raw.get("delivery_gross_per_day")),
            "classic_score": _float(raw.get("location_score")),
            "google_rating": _float(raw.get("Google rating")),
            "neighbour_brands": raw.get("neighbour_brands") or "",
            "aggregator_share": _float(raw.get("aggregator_share")),
            "energy_of_6": raw.get("energy_of_6"),
            "quality": raw.get("quality"),
            "anchor": raw.get("anchor"),
            "diversity": raw.get("diversity"),
            "transport": raw.get("transport"),
            "nearby_reviews": raw.get("nearby_reviews"),
            "pin_m": pins.get((raw.get("Store") or "").strip()),
            "score_note": "",
            "earlier_score": None,
        })

    _apply_ncr_scores(raw_rows, directory)
    ridership_rows = load_ridership(directory)
    review_band = _log_band([_float(row["nearby_reviews"]) for row in raw_rows])
    delivery_band = _log_band([row["delivery_gross_per_day"] for row in raw_rows])
    ridership_band = _log_band([row["daily"] for row in ridership_rows])
    bands = {"reviews": review_band, "delivery": delivery_band, "ridership": ridership_band}

    stores = []
    for row in raw_rows:
        pin_m = row["pin_m"]
        repin = pin_m is not None and pin_m > REPIN_METRES
        bucket = city_bucket(row["region"])
        signals = _signals_from_row(row, raw_rows, bands)
        scored = score_signals(row["format"], signals, bucket, bands)
        if row["lat"] is None or row["lon"] is None:
            nearest, nearest_m = None, None
        else:
            nearest, nearest_m = _nearest_store(row["lat"], row["lon"], raw_rows, skip_name=row["name"])
        stores.append({
            "name": row["name"],
            "region": row["region"],
            "bucket": bucket,
            "format": row["format"],
            "format_label": FORMAT_LABELS.get(row["format"], row["format"] or "Store"),
            "lat": row["lat"],
            "lon": row["lon"],
            "gross_30d": row["gross_30d"],
            "gross_per_day": row["gross_per_day"],
            "delivery_gross_per_day": row["delivery_gross_per_day"],
            "classic_score": row["classic_score"],
            "google_rating": row["google_rating"],
            "pattern_score": scored["pattern"]["score"],
            "pattern": scored["pattern"],
            "delivery": scored["delivery"],
            "pin_m": None if pin_m is None else round(pin_m),
            "repin": repin,
            "comparable": row["format"] in FORMULA_FOR,
            "cannibal": nearest_m is not None and nearest_m <= CANNIBAL_METRES,
            "nearest_store": None if nearest is None else nearest["name"],
            "nearest_store_m": None if nearest_m is None else round(nearest_m),
            "brands_300": parse_neighbour_brands(row["neighbour_brands"], PREMIUM_METRES) or [],
            "score_note": row.get("score_note") or "",
            "earlier_score": row.get("earlier_score"),
        })
    for store in stores:
        store["peers"] = [
            {
                "name": peer["name"],
                "format_label": peer["format_label"],
                "pattern_score": peer["pattern_score"],
                "gross_per_day": peer["gross_per_day"],
            }
            for peer in _peer_rows(store, stores)
        ]

    high = [store for store in stores if store["format"] == "high_street"]
    malls = [store for store in stores if store["format"] == "mall"]
    correlations = {
        "high_street_classic": _correlation(high, "classic_score"),
        "high_street_classic_pinned": _correlation([store for store in high if not store["repin"]], "classic_score"),
        "high_street_new": _correlation(high, "pattern_score"),
        "mall_classic": _correlation(malls, "classic_score"),
        "mall_new": _correlation(malls, "pattern_score"),
        "cloud_kitchen_new": _correlation([store for store in stores if store["format"] == "cloud_kitchen"], "pattern_score"),
    }

    candidates = []
    for raw in _read(directory / "candidate_clusters.csv"):
        flag = (raw.get("flag") or "").strip()
        candidates.append({
            "city": (raw.get("city") or "").strip(),
            "area": (raw.get("candidate_area") or "").strip(),
            "anchor": (raw.get("anchor_example") or "").strip(),
            "lat": _float(raw.get("lat")),
            "lon": _float(raw.get("lon")),
            "brands": (raw.get("brands") or "").strip(),
            "brand_count": int(_float(raw.get("distinct_coloc_brands_500m")) or 0),
            "score": _float(raw.get("weighted_score")),
            "nearest": (raw.get("nearest_dosa_coffee") or "").strip(),
            "nearest_km": _float(raw.get("nearest_dc_km")),
            "airport": "airport" in flag.casefold(),
        })
    candidates.sort(key=lambda row: (-(row["score"] or 0), row["area"].casefold()))

    outlets = []
    brands = []
    seen_brands = set()
    for raw in _read(directory / "neighbour_brand_outlets.csv"):
        lat = _float(raw.get("lat"))
        lon = _float(raw.get("lon"))
        if lat is None or lon is None:
            continue
        brand = (raw.get("brand") or "").strip()
        if brand and brand not in seen_brands:
            seen_brands.add(brand)
            brands.append(brand)
        outlets.append({
            "brand": brand,
            "name": (raw.get("outlet_name") or "").strip(),
            "lat": lat,
            "lon": lon,
        })
    brands.sort(key=str.casefold)

    def best(city, limit):
        rows = [row for row in candidates if row["city"] == city and not row["airport"]]
        return rows[:limit]

    return {
        "stores": stores,
        "correlations": correlations,
        "candidates": candidates,
        "best_ncr": best("NCR", 5),
        "best_kolkata": best("Kolkata", 3),
        "outlets": outlets,
        "brands": brands,
        "bands": bands,
        "ridership": ridership_rows,
    }


def match_store(location_name, stores):
    text = " ".join(str(location_name or "").casefold().replace("-", " ").split())
    if not text:
        return None
    for store in stores:
        name = " ".join(store["name"].casefold().replace("-", " ").split())
        short = name.split("(")[0].strip()
        if len(short) >= 6 and short in text:
            return store
    return None


def score_live_site(lat, lng, fmt, location_name, classic, places):
    """Score a picked suggestion. A far pin for a known store withholds the verdict."""
    board = load_board()
    stores = board["stores"]
    bucket = city_bucket("", location_name, lat)
    matched = match_store(location_name, stores)
    repin = None
    if matched and matched.get("lat") is not None:
        distance = haversine_m(lat, lng, matched["lat"], matched["lon"])
        if distance > REPIN_METRES:
            repin = {"store": matched["name"], "metres": round(distance)}

    within = []
    for place in places or []:
        geometry = (place.get("geometry") or {}).get("location") or {}
        plat = geometry.get("lat", lat)
        plon = geometry.get("lng", lng)
        try:
            distance = haversine_m(lat, lng, float(plat), float(plon))
        except (TypeError, ValueError):
            distance = 0
        if distance <= PREMIUM_METRES:
            within.append(place)
    names = [place.get("name") or "" for place in within]
    reviews = sum(int(place.get("user_ratings_total") or 0) for place in within)
    energy = classic.get("energy_score")
    nearest, _nearest_m = _nearest_store(lat, lng, stores, max_metres=NEAR_STORE_METRES)
    nearest_sales = None if nearest is None else nearest.get("delivery_gross_per_day")
    ridership_hit = match_ridership(classic.get("nearest_station_name"), board.get("ridership") or [])
    signals = {
        "energy": None if energy is None else max(0.0, min(1.0, float(energy) / 6)),
        "energy_detail": None if energy is None else f"{energy:g} / 6",
        "reviews": reviews,
        "reviews_detail": f"{int(reviews)} reviews",
        "transport": classic.get("transport_score"),
        "transport_detail": "" if classic.get("transport_score") is None else f"{round(classic['transport_score'], 2):g} / 1",
        "premium": premium_unit(names),
        "premium_detail": f"{sum(1 for name in names if _brand_key(name))} premium brands within 300 m",
        "diversity": classic.get("diversity_score"),
        "diversity_detail": "" if classic.get("diversity_score") is None else f"{classic['diversity_score']:g} / 1",
        "quality": classic.get("quality_score"),
        "quality_detail": "" if classic.get("quality_score") is None else f"{classic['quality_score']:g} / 1",
        "anchor": classic.get("anchor_score"),
        "aggregator_enabled": None,
        "aggregator_detail": "Needs a site visit",
        "mall_reviews": None,
        "mall_review_band": board["bands"]["reviews"],
        "mall_anchors": mall_anchor_unit(names),
        "mall_anchor_detail": "",
        "station_m": classic.get("nearest_station_m"),
        "station_detail": classic.get("nearest_station_name") or "",
        "ridership": None if ridership_hit is None else ridership_hit.get("daily"),
        "ridership_source": "" if ridership_hit is None else ridership_hit.get("source") or "",
        "ridership_band": board["bands"].get("ridership", (None, None)),
        "delivering_restaurants": None,
        "residential": None,
        "nearest_delivery_sales": nearest_sales,
    }
    chosen = fmt if fmt in FORMULA_FOR else "high_street"
    scored = score_signals(chosen, signals, bucket, board["bands"])
    other, other_m = _nearest_store(lat, lng, stores)
    pattern_score = scored["pattern"]["score"]
    peers = []
    if pattern_score is not None:
        same = [
            store for store in stores
            if FORMULA_FOR.get(store["format"]) == FORMULA_FOR.get(chosen) and store.get("pattern_score") is not None
        ]
        same.sort(key=lambda store: (abs(store["pattern_score"] - pattern_score), store["name"].casefold()))
        peers = [
            {
                "name": store["name"],
                "format_label": store["format_label"],
                "pattern_score": store["pattern_score"],
                "gross_per_day": store["gross_per_day"],
            }
            for store in same[:3]
        ]
    return {
        "pattern": scored["pattern"],
        "delivery": scored["delivery"],
        "bucket": bucket,
        "format": chosen,
        "format_label": FORMAT_LABELS.get(chosen, "High street"),
        "repin": repin,
        "nearest_store": None if other is None else other["name"],
        "nearest_store_m": None if other_m is None else round(other_m),
        "cannibal": other_m is not None and other_m <= CANNIBAL_METRES,
        "brands_300": [name for name in names if _brand_key(name)],
        "peers": peers,
    }
