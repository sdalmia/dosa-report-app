# location_finder.py – Updated to accept Google Maps URL instead of lat/lng

from flask import Blueprint, jsonify, render_template, request, url_for

from app.fragments import html_fragment, matches, query_offset, query_text, slice_rows
from app.page_cache import remember
import requests
import os

from app.brand_search import PlacesLookupError, find_brand_outlets
from app.brands import (
    annotate_place,
    build_positioning,
    known_brand_choices,
    site_verdict,
)
from app.site_pattern import DATA_COMING, load_board, score_live_site
from app.store_health.present import format_owner_rupee

location_finder_bp = Blueprint('location_finder', __name__)

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

from math import radians, sin, cos, sqrt, atan2

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371e3  # meters
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)

    a = sin(dphi/2)**2 + cos(phi1) * cos(phi2) * sin(dlambda/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def fetch_places_by_type(lat, lng, radius, place_type, keyword=None):
    url = (
        "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        f"?location={lat},{lng}&radius={radius}&type={place_type}&key={GOOGLE_API_KEY}"
    )
    if keyword:
        url += f"&keyword={keyword}"

    res = requests.get(url).json()
    return res.get("results", [])

def compute_metro_score(lat, lng):
    metros = fetch_places_by_type(lat, lng, 1000, "transit_station", keyword="metro")
    if not metros:
        return 0

    nearest = min(
        haversine_distance(lat, lng, m["geometry"]["location"]["lat"], m["geometry"]["location"]["lng"])
        for m in metros
    )

    if nearest <= 200: return 1
    if nearest <= 500: return 0.8
    if nearest <= 800: return 0.5
    return 0

def compute_bus_score(lat, lng):
    buses = fetch_places_by_type(lat, lng, 600, "bus_station")
    if not buses:
        return 0

    nearest = min(
        haversine_distance(lat, lng, b["geometry"]["location"]["lat"], b["geometry"]["location"]["lng"])
        for b in buses
    )

    if nearest <= 100: return 1
    if nearest <= 300: return 0.6
    if nearest <= 500: return 0.3
    return 0

def compute_road_score(lat, lng):
    roads = fetch_places_by_type(lat, lng, 300, "route")
    if not roads:
        return 0
    
    names = [r.get("name", "").lower() for r in roads]

    if any("highway" in n or "expressway" in n or "national highway" in n for n in names):
        return 1
    if any("main" in n or "arterial" in n or "road" in n for n in names):
        return 0.6
    return 0.3


def get_cuisine(place):
    """
    Classifies cuisine using name + types.
    Very basic heuristic but works well for Indian markets.
    """
    print("Inside get_cusine()\n")

    text = (place.get("name", "") + " " + " ".join(place.get("types", []))).lower()

    if "south" in text or "dosa" in text or "idli" in text:
        return "South Indian"
    if "north" in text or "punjabi" in text or "tandoor" in text:
        return "North Indian"
    if "biryani" in text or "rice" in text:
        return "Biryani"
    if "pizza" in text:
        return "Pizza"
    if "burger" in text:
        return "Burgers"
    if "chinese" in text or "schezwan" in text or "asian" in text:
        return "Asian"
    if "cafe" in text or "coffee" in text or "tea" in text:
        return "Cafe"
    if "bakery" in text or "cake" in text:
        return "Bakery"
    if "roll" in text or "kathi" in text:
        return "Rolls"
    if "Bengali" in text:
        return "Bengali"
    if "seafood" in text:
        return "Seafood"
    if "fast food" in text or "chicken wings" in text or "fries" in text:
        return "Fast Food"

    return "Other"




import time


FNB_TYPES = ["restaurant", "cafe", "bakery", "meal_takeaway", "meal_delivery"]

def fetch_eateries(lat, lng, radius):
    all_places = []

    for place_type in FNB_TYPES:
        url = (
            "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
            f"?location={lat},{lng}&radius={radius}&type={place_type}&key={GOOGLE_API_KEY}"
        )

        res = requests.get(url).json()
        results = res.get("results", [])
        all_places.extend(results)

        next_page_token = res.get("next_page_token")

        while next_page_token:
            time.sleep(2)
            paginated_url = (
                "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
                f"?pagetoken={next_page_token}&key={GOOGLE_API_KEY}"
            )
            res = requests.get(paginated_url).json()
            all_places.extend(res.get("results", []))
            next_page_token = res.get("next_page_token")

    # Remove duplicates by place_id
    unique = {p["place_id"]: p for p in all_places}
    return list(unique.values())

def get_location_name(lat, lng):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={GOOGLE_API_KEY}"
    res = requests.get(url).json()

    if res["status"] == "OK" and len(res["results"]) > 0:
        return res["results"][0].get("formatted_address", "Unknown Location")

    return "Unknown Location"


def compute_new_score(places, lat, lng, radius):
    # Food signals are zero when Google returns no eateries. Transport is
    # still scored from the same factors. An early `return 0` used to crash
    # the result page, which expects this dict.
    places = places or []

    # --------------------------------------
    # 1. ENERGY SCORE (0 – 8 points)
    # --------------------------------------
    # Total reviews of the area = total food activity
    total_reviews = sum(p.get("user_ratings_total", 0) for p in places)

    TARGET_REVIEWS = 50 * radius  # healthy area threshold
    print("target reviews : ",TARGET_REVIEWS)
    print("total reviews : ",total_reviews)
    energy_score = min(total_reviews / TARGET_REVIEWS, 1.0) * 6
    print("Energy score: ",energy_score)


    # --------------------------------------
    # 2. QUALITY SCORE (0 – 1 points)
    # --------------------------------------
    rated_places = [p for p in places if "rating" in p and p.get("user_ratings_total", 0) > 0]

    if rated_places:
        # Weighted average rating (rating × reviews)
        weighted_sum = sum(
            p["rating"] * p.get("user_ratings_total", 0) for p in rated_places
        )
        avg_rating = weighted_sum / sum(p.get("user_ratings_total", 0) for p in rated_places)

        if avg_rating >= 4.2:
            quality_score = 1
        elif avg_rating >= 3.8:
            quality_score = 0.5
        else:
            quality_score = 0
    else:
        quality_score = 0


    # --------------------------------------
    # 3. ANCHOR SCORE (0 – 1 point)
    # --------------------------------------
    anchor_brands = [
        "starbucks", "mcdonald", "kfc", "domino", "pizza hut",
        "chai point", "ccd", "haldiram", "wow momo", "biryani blues", "OM Sweets"
    ]

    has_anchor = any(
        any(anchor in p.get("name", "").lower() for anchor in anchor_brands)
        for p in places
    )

    anchor_score = 1 if has_anchor else 0


    # --------------------------------------
    # 4. DIVERSITY SCORE (0 – 1 point)
    # --------------------------------------
    # Google place "types" sometimes contain cuisine cues
    def classify(p):
        text = (p.get("name", "") + " " + " ".join(p.get("types", []))).lower()
        if "cafe" in text: return "Cafe"
        if "south" in text or "dosa" in text: return "South Indian"
        if "north indian" in text: return "North Indian"
        if "pizza" in text: return "Pizza"
        if "chinese" in text: return "Chinese"
        if "biryani" in text: return "Biryani"
        if "bakery" in text: return "Bakery"
        if "fast food" in text: return "Fast Food"
        return None

    cuisine_tags = [classify(p) for p in places]
    cuisine_tags = [c for c in cuisine_tags if c]   # remove None

    unique_cuisines = len(set(cuisine_tags))
    diversity_score = 1 if unique_cuisines >= 5 else 0

    metro_score = compute_metro_score(lat, lng)
    station_m, station_name = nearest_station(lat, lng)
    bus_score = compute_bus_score(lat, lng)
    road_score = compute_road_score(lat, lng)

    transport_score = (metro_score + bus_score + road_score) / 3


    # --------------------------------------
    # FINAL SCORE (0 – 10)
    # --------------------------------------
    final_score = energy_score + quality_score + anchor_score + diversity_score + transport_score
    final_score = round(min(final_score, 10), 1)

    # Return score + diagnostics (optional)
    return {
        "score": final_score,
        "energy_score": round(energy_score, 1),
        "quality_score": quality_score,
        "anchor_score": anchor_score,
        "diversity_score": diversity_score,
        "total_reviews": total_reviews,
        "unique_cuisines": unique_cuisines,
        "transport_score": transport_score,
        "nearest_station_m": station_m,
        "nearest_station_name": station_name,
    }


def nearest_station(lat, lng):
    """Metres to the nearest metro or rail exit, and that station's name.

    An empty result means the search ran and nothing was inside 1 km.
    A failed search returns no distance, which the score leaves out.
    """
    places = []
    try:
        for keyword in ("metro", "railway station"):
            places.extend(fetch_places_by_type(lat, lng, 1000, "transit_station", keyword=keyword) or [])
    except Exception:
        return None, ""
    usable = []
    for place in places:
        loc = (place.get("geometry") or {}).get("location") or {}
        if loc.get("lat") is None or loc.get("lng") is None:
            continue
        usable.append(place)
    if not usable:
        return 1000.0, ""

    def distance(place):
        loc = place["geometry"]["location"]
        return haversine_distance(lat, lng, loc["lat"], loc["lng"])

    nearest = min(usable, key=distance)
    return distance(nearest), nearest.get("name") or ""


def _money(value):
    if value is None:
        return ""
    return format_owner_rupee(value)


def _pattern_answer(view):
    repin = view.get("repin")
    if repin:
        metres = repin["metres"]
        far = f"{metres / 1000:.1f} km" if metres >= 1000 else f"{metres} m"
        return (
            f"Re-pin needed. This suggestion is {far} from the store's Google pin, "
            "so there is no verdict."
        )
    score = view["pattern"]["score"]
    label = view["format_label"].lower()
    if score is None:
        return "Not enough inputs are in yet for a verdict."
    if score >= 9:
        lead = f"Yes. This is a strong {label} site."
    elif score >= 7:
        lead = f"Yes. This looks like a strong {label} site."
    elif score >= 5:
        lead = f"Maybe. This is a possible {label} site, not a standout."
    else:
        lead = f"No. This looks like a weak {label} site."
    if any(part["status"] == DATA_COMING and part.get("weight", 0) > 0 for part in view["pattern"]["parts"]):
        lead += " Some inputs are still data coming, so they are left out of the score."
    return lead


def _render_form(**extra):
    context = {
        "GOOGLE_MAPS_API_KEY": GOOGLE_API_KEY,
        "known_brands": known_brand_choices(),
        "error": None,
        "brand": "",
        "region": "",
        "money": _money,
        "model_label": "prior",
    }
    context.update(extra)
    if context.get("board") is None:
        context["board"] = load_board()
    from app.location_model import current_model_label

    context["model_label"] = current_model_label()
    return render_template("location_finder_form.html", **context)


def _with_logos(places):
    for place in places:
        annotate_place(place)
        logo = place.get("logo")
        place["logo_url"] = url_for("static", filename=logo) if logo else None
    return places


# -----------------------------
# Main route
# -----------------------------
@location_finder_bp.route('/location-finder', methods=['GET', 'POST'])
def location_finder():
    if request.method == 'POST':

        print("Inside POST of location_finder()\n\n\n")

        try:
            lat = float(request.form.get("latitude"))
            lng = float(request.form.get("longitude"))
        except (TypeError, ValueError):
            return _render_form(error="Choose a location from the suggestions so the site can be scored.")

        try:
            radius = int(request.form.get("radius", 500))
        except (TypeError, ValueError):
            radius = 500
        radius = min(max(radius, 50), 5000)

        print("lat and lng extracted\n")
        print("latitude: ",lat,"\n")
        print("longitude: ",lng,"\n")

        location_name = get_location_name(lat, lng)

        places = fetch_eateries(lat, lng, radius)
        places = sorted(
            places,
            key=lambda p: p.get("user_ratings_total", 0),
            reverse=True
        )

        for p in places:
            p["cuisine"] = get_cuisine(p)
        if places:
            print("cuisine list: \n", places[-1]["cuisine"])

        # Same 0–10 factors as before. A higher score is a stronger restaurant site.
        result = compute_new_score(places, lat, lng, radius)
        score = result["score"]
        fmt = (request.form.get("site_format") or "high_street").strip()
        if fmt not in {"high_street", "mall", "cloud_kitchen", "metro"}:
            fmt = "high_street"
        pattern = score_live_site(lat, lng, fmt, location_name, result, places)
        from app.location_model import log_prediction

        log_prediction(
            location_name,
            lat,
            lng,
            pattern.get("format"),
            pattern.get("model_version"),
            (pattern.get("pattern") or {}).get("score"),
            (pattern.get("pattern") or {}).get("parts"),
        )
        _with_logos(places)
        positioning = build_positioning(places)
        verdict = site_verdict(score, result)

        return render_template(
            "location_finder_result.html",
            score=score,
            breakdown=result,
            verdict=verdict,
            pattern=pattern,
            pattern_answer=_pattern_answer(pattern),
            money=_money,
            positioning=positioning,
            places=places,
            latitude=lat,
            longitude=lng,
            location_name=location_name,
            GOOGLE_MAPS_API_KEY=GOOGLE_API_KEY
        )

    # GET request → show form
    return _render_form(board=remember(("location-board",), load_board))


def _board():
    return remember(("location-board",), load_board)


def _candidate_page():
    board = _board()
    query = query_text()
    rows = [row for row in board.get("candidates") or [] if matches(row, query, ("area", "city", "nearest"))]
    chunk, nxt, total = slice_rows(rows, query_offset())
    more = None
    if nxt is not None:
        more = url_for("location_finder.location_candidates", offset=nxt, q=query or None, rows=1)
    return board, chunk, total, more


@location_finder_bp.route("/location-finder/map.json")
def location_map_json():
    board = _board()
    response = jsonify({
        "candidates": board.get("candidates") or [],
        "outlets": board.get("outlets") or [],
        "malls": board.get("malls") or [],
    })
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@location_finder_bp.route("/location-finder/fragment/candidates")
def location_candidates():
    board, rows, total, more = _candidate_page()
    if request.args.get("rows") == "1" or query_offset():
        body = render_template(
            "location_finder_candidate_rows.html",
            rows=rows,
            total=total,
            more=more,
        )
    else:
        body = render_template(
            "location_finder_candidates.html",
            rows=rows,
            total=total,
            more=more,
            malls=board.get("malls") or [],
            candidate_count=len(board.get("candidates") or []),
        )
    return html_fragment(body)


@location_finder_bp.route("/location-finder/fragment/stores")
def location_stores():
    board = _board()
    query = query_text()
    rows = [row for row in board.get("stores") or [] if matches(row, query, ("name", "format_label"))]
    chunk, nxt, total = slice_rows(rows, query_offset())
    more = url_for("location_finder.location_stores", offset=nxt, q=query or None, rows=1) if nxt is not None else None
    if request.args.get("rows") == "1" or query_offset():
        body = render_template(
            "location_finder_store_rows.html",
            rows=chunk,
            total=total,
            more=more,
            money=_money,
        )
    else:
        body = render_template(
            "location_finder_stores.html",
            rows=chunk,
            total=total,
            more=more,
            correlations=board.get("correlations") or {},
            money=_money,
        )
    return html_fragment(body)


@location_finder_bp.route("/location-finder/brand", methods=["POST"])
def location_finder_brand():
    brand = (request.form.get("brand") or "").strip()
    region = (request.form.get("region") or "").strip()
    try:
        found = find_brand_outlets(brand, region, GOOGLE_API_KEY)
    except PlacesLookupError as exc:
        return _render_form(error=str(exc), brand=brand, region=region)
    except requests.RequestException:
        return _render_form(
            error="Could not reach Google Places. Try again.",
            brand=brand,
            region=region,
        )

    places = _with_logos(found["places"])
    area = found["region"]
    return render_template(
        "location_finder_brand.html",
        brand=brand,
        region_name=area["name"],
        region_query=region,
        places=places,
        latitude=area["lat"],
        longitude=area["lng"],
        sw=area["sw"],
        ne=area["ne"],
        truncated=found["truncated"],
        known_brands=known_brand_choices(),
        outlet_count=len(places),
        GOOGLE_MAPS_API_KEY=GOOGLE_API_KEY,
    )

