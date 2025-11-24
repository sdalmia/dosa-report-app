# location_finder.py – Updated to accept Google Maps URL instead of lat/lng

from flask import Blueprint, render_template, request, redirect, url_for, flash
import requests
import os
import re

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
    if not places:
        return 0

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
        "transport_score": transport_score
    }


# -----------------------------
# Main route
# -----------------------------
@location_finder_bp.route('/location-finder', methods=['GET', 'POST'])
def location_finder():
    if request.method == 'POST':

        print("Inside POST of location_finder()\n\n\n")

        lat = float(request.form.get("latitude"))
        lng = float(request.form.get("longitude"))
        location_name = request.form.get("location_name")
        place_id = request.form.get("place_id")
        radius = int(request.form.get("radius", 500))  # Default = 500m


        print("lat and lng extracted\n")
        print("latitude: ",lat,"\n")
        print("longitude: ",lng,"\n")

        if lat is None or lng is None:
            flash("Unable to extract coordinates from the Google Maps link.", "danger")
            print("Unable to extract coordinates from the Google Maps link.")
            return redirect(url_for("location_finder.location_finder"))

        location_name = get_location_name(lat, lng)


        places = fetch_eateries(lat, lng, radius)
        places = sorted(
        places,
            key=lambda p: p.get("user_ratings_total", 0),
            reverse=True
        )

        for p in places:
            p["cuisine"] = get_cuisine(p)
        print("cuisine list: \n",p["cuisine"])


        # Scoring logic (basic version)
        result = compute_new_score(places,lat, lng, radius)
        score = result["score"]


        return render_template(
            "location_finder_result.html",
            score=score,
            breakdown=result,
            places=places,
            latitude=lat,
            longitude=lng,
            location_name=location_name,
            GOOGLE_MAPS_API_KEY=GOOGLE_API_KEY
        )

    # GET request → show form
    return render_template("location_finder_form.html",
        GOOGLE_MAPS_API_KEY=GOOGLE_API_KEY
        )

