import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-key")

from app.brand_search import PlacesLookupError, find_brand_outlets
from app.brands import (
    annotate_place,
    build_positioning,
    match_brand,
    name_matches_brand_query,
    site_verdict,
)
from app.routes.location_finder import compute_new_score


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return FakeResponse(self.handler(url, params or {}))


def _place(place_id, name, lat, lng, price_level=None):
    place = {
        "place_id": place_id,
        "name": name,
        "geometry": {"location": {"lat": lat, "lng": lng}},
        "vicinity": name,
    }
    if price_level is not None:
        place["price_level"] = price_level
    return place


def _kolkata_geocode():
    return {
        "status": "OK",
        "results": [{
            "formatted_address": "Kolkata, West Bengal, India",
            "geometry": {
                "location": {"lat": 22.57, "lng": 88.36},
                "viewport": {
                    "southwest": {"lat": 22.45, "lng": 88.25},
                    "northeast": {"lat": 22.65, "lng": 88.45},
                },
            },
        }],
    }


class BrandMatchTests(unittest.TestCase):
    def test_known_brands_and_lookalikes(self):
        self.assertEqual(match_brand("Starbucks Coffee Park Street")["id"], "starbucks")
        self.assertEqual(match_brand("McDonald's")["id"], "mcdonalds")
        self.assertEqual(match_brand("Kentucky Fried Chicken")["id"], "kfc")
        self.assertEqual(match_brand("Wow! Momo Salt Lake")["id"], "wowmomo")
        self.assertEqual(match_brand("Cafe Coffee Day")["id"], "ccd")
        self.assertEqual(match_brand("Haldiram's Prabhuji")["id"], "haldirams")
        self.assertIsNone(match_brand("Wow! China"))
        self.assertIsNone(match_brand("An accident site"))
        self.assertIsNone(match_brand("Local dosa house"))

    def test_brand_query_uses_aliases_not_loose_keywords(self):
        self.assertTrue(name_matches_brand_query("KFC Camac Street", "KFC"))
        self.assertTrue(name_matches_brand_query("Kentucky Fried Chicken", "KFC"))
        self.assertTrue(name_matches_brand_query("CCD — Park Street", "Cafe Coffee Day"))
        self.assertFalse(name_matches_brand_query("Wow! China", "Wow Momo"))
        self.assertFalse(name_matches_brand_query("Pizza Express", "Pizza Hut"))


class PositioningTests(unittest.TestCase):
    def test_bill_bands_rent_and_similar_brands_use_only_places_data(self):
        places = [
            {"name": "Starbucks Coffee", "price_level": 2, "cuisine": "Cafe"},
            {"name": "Starbucks Salt Lake", "price_level": 2, "cuisine": "Cafe"},
            {"name": "Local Dosa", "price_level": 1, "cuisine": "South Indian"},
            {"name": "No Bill Cafe", "cuisine": "Cafe"},
            {"name": "Wow! China", "cuisine": "Asian"},
        ]
        for place in places:
            annotate_place(place)
            place["logo_url"] = "/static/" + place["logo"] if place.get("logo") else None

        positioning = build_positioning(places)
        blob = str(positioning)

        self.assertEqual(positioning["rent"]["status"], "unavailable")
        self.assertEqual(positioning["rent"]["label"], "Unavailable")
        self.assertNotIn("amount", positioning["rent"])
        for banned in ("₹", "Rs", "INR", "rupee"):
            self.assertNotIn(banned, blob)

        self.assertEqual(positioning["bill"]["dominant_level"], 2)
        self.assertIn("Moderate", positioning["bill"]["headline"])
        self.assertIn("bill is unavailable", positioning["bill"]["headline"])
        self.assertEqual(positioning["bill"]["missing"], 2)
        self.assertIn("2 places have no price level", positioning["bill"]["headline"])
        self.assertIn("moderate cafe brand fits", positioning["fit"])

        names = [row["name"] for row in positioning["similar_brands"]]
        self.assertEqual(names, ["Starbucks"])
        self.assertTrue(positioning["similar_brands"][0]["same_bill_band"])
        self.assertIn("Moderate (2)", positioning["similar_brands"][0]["bill"])

    def test_missing_price_level_does_not_invent_a_band(self):
        places = [{"name": "Local Kitchen", "cuisine": "North Indian"}]
        annotate_place(places[0])
        positioning = build_positioning(places)
        self.assertIsNone(places[0]["bill_band"])
        self.assertEqual(positioning["bill"]["known"], 0)
        self.assertIn("Unavailable", positioning["bill"]["headline"])
        self.assertIn("price position is unavailable", positioning["fit"])
        self.assertEqual(positioning["similar_brands"], [])


class ScoreTests(unittest.TestCase):
    @patch("app.routes.location_finder.fetch_places_by_type", return_value=[])
    def test_existing_factors_still_score_a_busy_anchor(self, _transport):
        places = [{
            "name": "Starbucks Coffee",
            "user_ratings_total": 25000,
            "rating": 4.5,
            "types": ["cafe"],
        }]
        result = compute_new_score(places, 22.5, 88.3, 500)
        self.assertEqual(result["energy_score"], 6)
        self.assertEqual(result["quality_score"], 1)
        self.assertEqual(result["anchor_score"], 1)
        self.assertEqual(result["diversity_score"], 0)
        self.assertEqual(result["transport_score"], 0)
        self.assertEqual(result["score"], 8.0)
        verdict = site_verdict(result["score"], result)
        self.assertIn("strong site for a new restaurant", verdict["answer"])

    @patch("app.routes.location_finder.fetch_places_by_type", return_value=[])
    def test_anchor_match_stays_case_sensitive_for_om_sweets(self, _transport):
        # The score list checks "OM Sweets" against a lowercased name, so this
        # outlet does not add an anchor point. Logo matching is separate.
        places = [{
            "name": "OM Sweets",
            "user_ratings_total": 100,
            "rating": 4.0,
            "types": ["restaurant"],
        }]
        result = compute_new_score(places, 28.6, 77.2, 500)
        self.assertEqual(result["anchor_score"], 0)
        self.assertEqual(match_brand("OM Sweets")["id"], "omsweets")

    @patch("app.routes.location_finder.fetch_places_by_type", return_value=[])
    def test_no_eateries_still_returns_a_score_dict(self, _transport):
        result = compute_new_score([], 22.5, 88.3, 500)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["score"], 0)
        self.assertIn("weak site", site_verdict(result["score"], result)["answer"])


class BrandSearchTests(unittest.TestCase):
    def test_city_search_keeps_only_name_matches_inside_the_region(self):
        def handler(url, params):
            if "geocode" in url:
                return _kolkata_geocode()
            return {
                "status": "OK",
                "results": [
                    _place("1", "Starbucks Park Street", 22.55, 88.35, 2),
                    _place("2", "Cafe Coffee Day", 22.56, 88.35, 1),
                    _place("3", "Starbucks Salt Lake", 22.58, 88.41, 2),
                    _place("4", "Starbucks Far Away", 23.5, 87.0, 2),
                ],
            }

        http = FakeHttp(handler)
        found = find_brand_outlets("Starbucks", "Kolkata", "test-key", http=http, sleep=lambda _s: None)
        self.assertEqual([p["place_id"] for p in found["places"]], ["1", "3"])
        self.assertFalse(found["truncated"])
        self.assertEqual(found["region"]["name"], "Kolkata, West Bengal, India")
        nearby_calls = [call for call in http.calls if "nearbysearch" in call[0]]
        self.assertEqual(len(nearby_calls), 1)
        self.assertEqual(nearby_calls[0][1]["keyword"], "Starbucks")

    def test_full_result_page_splits_the_city(self):
        state = {"n": 0}

        def handler(url, params):
            if "geocode" in url:
                return _kolkata_geocode()
            state["n"] += 1
            if state["n"] == 1:
                return {
                    "status": "OK",
                    "results": [
                        _place(f"parent-{i}", "Starbucks", 22.55, 88.35, 2)
                        for i in range(60)
                    ],
                }
            lat, lng = (float(part) for part in params["location"].split(","))
            return {"status": "OK", "results": [_place(f"{lat:.4f},{lng:.4f}", "Starbucks", lat, lng, 2)]}

        http = FakeHttp(handler)
        found = find_brand_outlets("Starbucks", "Kolkata", "test-key", http=http, sleep=lambda _s: None)
        self.assertEqual(state["n"], 5)
        self.assertEqual(len(found["places"]), 4)
        self.assertFalse(any(p["place_id"].startswith("parent-") for p in found["places"]))

    def test_region_larger_than_one_circle_is_tiled(self):
        def handler(url, params):
            if "geocode" in url:
                return {
                    "status": "OK",
                    "results": [{
                        "formatted_address": "Delhi NCR, India",
                        "geometry": {
                            "location": {"lat": 28.55, "lng": 77.35},
                            "bounds": {
                                "southwest": {"lat": 28.2, "lng": 77.0},
                                "northeast": {"lat": 28.9, "lng": 77.7},
                            },
                        },
                    }],
                }
            lat, lng = (float(part) for part in params["location"].split(","))
            return {"status": "OK", "results": [_place(f"{lat:.3f},{lng:.3f}", "KFC", lat, lng, 1)]}

        http = FakeHttp(handler)
        found = find_brand_outlets("KFC", "Delhi NCR", "test-key", http=http, sleep=lambda _s: None)
        nearby_calls = [call for call in http.calls if "nearbysearch" in call[0]]
        self.assertEqual(len(nearby_calls), 4)
        self.assertEqual(len(found["places"]), 4)
        self.assertTrue(all(p["name"] == "KFC" for p in found["places"]))

    def test_pagination_and_unknown_place(self):
        def handler(url, params):
            if "geocode" in url:
                return _kolkata_geocode()
            if "pagetoken" in params:
                return {"status": "OK", "results": [_place("2", "Blue Tokai Coffee", 22.57, 88.36)]}
            return {
                "status": "OK",
                "results": [_place("1", "Blue Tokai Park Street", 22.55, 88.35)],
                "next_page_token": "next",
            }

        sleeps = []
        found = find_brand_outlets(
            "Blue Tokai",
            "Kolkata",
            "test-key",
            http=FakeHttp(handler),
            sleep=lambda seconds: sleeps.append(seconds),
        )
        self.assertEqual([p["place_id"] for p in found["places"]], ["2", "1"])
        self.assertEqual(sleeps, [2])

    def test_missing_region_is_an_error(self):
        http = FakeHttp(lambda url, params: {"status": "ZERO_RESULTS", "results": []})
        with self.assertRaises(PlacesLookupError):
            find_brand_outlets("Starbucks", "Not A Real Place", "test-key", http=http, sleep=lambda _s: None)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self._db = tempfile.NamedTemporaryFile(suffix=".db")
        os.environ["DATABASE_URL"] = "sqlite:///" + self._db.name
        os.environ["GOOGLE_MAPS_API_KEY"] = "test-key"
        from app import create_app
        self.app = create_app()
        self.client = self.app.test_client()

    def test_form_keeps_score_and_brand_search(self):
        response = self.client.get("/location-finder")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Score this site", body)
        self.assertIn("Map this brand", body)
        self.assertIn("strong site for a new restaurant", body)
        self.assertIn('id="score-form"', body)
        self.assertIn('id="brand-form"', body)

    @patch("app.routes.location_finder.fetch_places_by_type", return_value=[])
    @patch("app.routes.location_finder.get_location_name", return_value="Park Street, Kolkata")
    @patch("app.routes.location_finder.fetch_eateries")
    def test_score_page_keeps_heatmap_and_labels_gaps(self, fetch_eateries, _name, _transport):
        fetch_eateries.return_value = [{
            "place_id": "sbx",
            "name": "Starbucks Coffee",
            "user_ratings_total": 25000,
            "rating": 4.5,
            "price_level": 2,
            "types": ["cafe", "food"],
            "geometry": {"location": {"lat": 22.55, "lng": 88.35}},
        }]
        response = self.client.post("/location-finder", data={
            "latitude": "22.55",
            "longitude": "88.35",
            "radius": "500",
        })
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Should we open a restaurant here?", body)
        self.assertIn("Yes. This looks like a strong site for a new restaurant.", body)
        self.assertIn('id="heatmap"', body)
        self.assertIn("Review heatmap", body)
        self.assertIn("HeatmapLayer", body)
        self.assertIn("brand_logos/starbucks.png", body)
        self.assertIn("Retail rent", body)
        self.assertIn("does not estimate rent", body)
        self.assertIn("Moderate", body)
        self.assertIn("A moderate cafe brand fits this area.", body)
        self.assertIn("Starbucks", body)
        self.assertIn("Classic score", body)
        self.assertIn("data coming", body)
        self.assertIn("does not estimate rent", body)
        self.assertNotIn("INR", body)
        self.assertNotIn("Rs ", body)

    def test_score_requires_a_picked_location(self):
        response = self.client.post("/location-finder", data={"radius": "500"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Choose a location from the suggestions", response.get_data(as_text=True))

    @patch("app.routes.location_finder.find_brand_outlets")
    def test_brand_map_page(self, finder):
        finder.return_value = {
            "brand": "Starbucks",
            "truncated": False,
            "region": {
                "name": "Kolkata, West Bengal, India",
                "lat": 22.57,
                "lng": 88.36,
                "sw": {"lat": 22.45, "lng": 88.25},
                "ne": {"lat": 22.65, "lng": 88.45},
            },
            "places": [
                _place("1", "Starbucks Park Street", 22.55, 88.35, 2),
            ],
        }
        response = self.client.post("/location-finder/brand", data={
            "brand": "Starbucks",
            "region": "Kolkata",
        })
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('id="brand-map"', body)
        self.assertIn("brand_logos/starbucks.png", body)
        self.assertIn("Score a single site", body)
        self.assertIn("not a site score", body)
        self.assertIn("Moderate", body)
        self.assertNotIn("₹", body)


if __name__ == "__main__":
    unittest.main()
