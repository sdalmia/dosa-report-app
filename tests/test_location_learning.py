import csv
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-key")
_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _DB.name)
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import create_app
from app.location_model import (
    MIN_FORMAT_N,
    cap_bounds,
    clear_approvals,
    delivery_signal,
    load_model,
    mall_rows,
    fit_pooled,
    input_index,
    latest_approved,
    learning_rows,
    log_prediction,
    metro_signal,
    metro_stations,
    outcome_rows,
    prior_weights,
    refit_model,
    review_stats,
    ridership_coverage,
    snapshot_rows,
    south_indian_signal,
    write_outcomes,
    write_refit,
    write_snapshot,
)
from app.owner_tools.metrics import build_goals
from app.owner_tools.sources import load_goals
from app.site_pattern import clear_cache
from app.store_health.contract import load_feeds
from app.store_master import allows_growth, find_store, is_trading, store_gaps


OWNER = "siddhant@dalgreenfoods.com"
OTHER = "siddhant@dosacoffee.com"


def _vector(**values):
    base = {key: 0.5 for key in prior_weights()["high_street"]}
    base.update(values)
    return base


class StoreStatusTests(unittest.TestCase):
    def test_closed_stores_are_out_of_rankings_and_gaps(self):
        for label in ("Chattarpur (02/0005)", "GK1 Cloud Kitchen (02/0002)"):
            row = find_store(label)
            self.assertEqual(row["status"], "closed")
            self.assertFalse(is_trading(label))
            self.assertEqual(store_gaps(row), [])
            self.assertFalse(allows_growth(label))

    def test_faridabad_is_closing_with_no_growth_actions(self):
        row = find_store("Sec 15 Faridabad (02/0007)")
        self.assertEqual(row["status"], "closing 31 Oct")
        self.assertTrue(is_trading(row["posist_name"]))
        self.assertFalse(allows_growth(row["posist_name"]))
        payload = build_goals(load_feeds(), load_goals(), "2026-10", False)
        match = next(store for store in payload["stores"] if "Faridabad" in store["label"])
        self.assertEqual(match["empty"], "No growth actions.")
        self.assertIsNone(match["bar_pct"])


class MallInputTests(unittest.TestCase):
    def test_v2_matches_stores_and_clusters_and_leaves_blanks_unknown(self):
        clear_cache()
        rows = mall_rows()
        self.assertEqual(len(rows), 43)
        stores = [row for row in rows if row["role"] == "store"]
        candidates = [row for row in rows if row["role"] == "candidate"]
        references = [row for row in rows if row["role"] == "reference"]
        self.assertEqual(len(stores), 7)
        self.assertEqual(len(candidates), 31)
        self.assertEqual(len(references), 5)
        self.assertTrue(all(row["matched"] and row["store_id"] for row in stores))
        self.assertEqual(
            {row["store_id"] for row in stores},
            {
                "dosa-coffee-forum-0003",
                "dosa-coffee-manisquare-0004",
                "dosa-coffee-quest-mall-01-0016",
                "dosa-coffee-rosedale-plaza-0006",
                "dosa-coffee-ideal-plaza-01-0001",
                "dosa-coffee-rangoli-mall-01-0010",
                "pacific-mall-jasola-02-0011",
            },
        )
        self.assertTrue(all(row["matched"] and row["cluster_site_id"] for row in candidates))
        forum = next(row for row in stores if row["store_id"] == "dosa-coffee-forum-0003")
        self.assertEqual(forum["aggregator_enabled"], 0.0)
        self.assertEqual(forum["food_court"], 1.0)
        ideal = next(row for row in stores if "Ideal" in row["mall_name"])
        self.assertIsNone(ideal["anchor_count"])
        self.assertIsNone(ideal["food_court"])
        self.assertIsNotNone(ideal["review_count"])
        shipra = next(row for row in candidates if row["mall_name"] == "Shipra Mall")
        gaur = next(row for row in candidates if row["mall_name"] == "Gaur Central Mall")
        rcube = next(row for row in candidates if "Rcube" in row["mall_name"])
        self.assertIsNone(shipra["review_count"])
        self.assertIsNone(gaur["review_count"])
        self.assertIsNone(rcube["aggregator_enabled"])
        self.assertEqual(rcube["food_court"], 1.0)

    def test_reference_malls_are_not_scored_and_candidates_are(self):
        clear_cache()
        from app.site_pattern import load_board

        markers = load_board()["malls"]
        references = [row for row in markers if row["reference"]]
        scored = [row for row in markers if not row["reference"]]
        self.assertEqual(len(references), 5)
        self.assertEqual(len(scored), 31)
        self.assertTrue(all(row["score"] is None for row in references))
        self.assertTrue(all(row["score"] is not None for row in scored))
        self.assertIn("DLF Mall of India", {row["name"] for row in references})
        self.assertNotIn("DLF Mall of India", {row["name"] for row in scored})

    def test_a_replaced_file_is_reread(self):
        from app.location_model import clear_input_cache

        folder = tempfile.TemporaryDirectory()
        previous = os.environ.get("LOCATION_DATA_DIR")
        os.environ["LOCATION_DATA_DIR"] = folder.name
        try:
            inputs = Path(folder.name) / "inputs"
            inputs.mkdir()
            path = inputs / "mall_inputs.csv"
            path.write_text(
                "site_id,mall_name,lat,lng,city,aggregator_enabled,mall_google_reviews,n_anchor_brands_inside,food_court\n"
                "Dosa Coffee - Forum (0003),Forum,22.5,88.3,Kolkata,yes,10,4,no\n",
                encoding="utf-8",
            )
            clear_input_cache()
            clear_cache()
            first = mall_rows()[0]
            self.assertEqual(first["aggregator_enabled"], 1.0)
            self.assertEqual(first["food_court"], 0.0)
            self.assertEqual(first["store_id"], "dosa-coffee-forum-0003")
            path.write_text(
                "site_id,mall_name,lat,lng,city,aggregator_enabled,mall_google_reviews,n_anchor_brands_inside,food_court\n"
                "Dosa Coffee - Forum (0003),Forum,22.5,88.3,Kolkata,,20,4,\n",
                encoding="utf-8",
            )
            stamp = path.stat().st_mtime
            os.utime(path, (stamp + 10, stamp + 10))
            second = mall_rows()[0]
            self.assertIsNone(second["aggregator_enabled"])
            self.assertIsNone(second["food_court"])
            self.assertEqual(second["review_count"], 20.0)
        finally:
            if previous is None:
                os.environ.pop("LOCATION_DATA_DIR", None)
            else:
                os.environ["LOCATION_DATA_DIR"] = previous
            folder.cleanup()
            clear_input_cache()
            clear_cache()

    def test_v2026_10b_is_proposed_and_the_named_mall_misses_shrink(self):
        proposed = load_model("v2026-10b")
        previous = load_model("v2026-10")
        self.assertEqual(proposed["status"], "proposed")
        self.assertIsNone(proposed["approved_at"])
        self.assertIn("mall", proposed["frozen_formats"])
        self.assertLess(proposed["format_counts"]["mall"], 8)
        self.assertIsNone(latest_approved())
        before = {row["store"]: row for row in previous["backtest"]}
        after = {row["store"]: row for row in proposed["backtest"]}
        improved = {
            "Dosa Coffee - Ideal Plaza (01/0001)": 4.25,
            "Pacific mall, Jasola (02/0011)": 2.66,
            "Dosa Coffee - Rosedale Plaza(0006)": 2.0,
            "Dosa Coffee - Manisquare (0004)": 2.23,
        }
        for name, gap in improved.items():
            self.assertLess(after[name]["decile_gap"], before[name]["decile_gap"])
            self.assertEqual(after[name]["decile_gap"], gap)
            self.assertTrue(after[name]["miss"])
        self.assertGreater(after["Dosa Coffee - Forum (0003)"]["decile_gap"], before["Dosa Coffee - Forum (0003)"]["decile_gap"])
        self.assertGreater(after["Dosa Coffee - Quest Mall (01/0016)"]["decile_gap"], before["Dosa Coffee - Quest Mall (01/0016)"]["decile_gap"])


class SnapshotTests(unittest.TestCase):
    def test_snapshot_uses_the_pin_and_leaves_missing_competitors_blank(self):
        clear_cache()
        rows = {row["store"]: row for row in snapshot_rows("2026-10")}
        self.assertNotIn("Chattarpur (02/0005)", rows)
        self.assertNotIn("GK1 Cloud Kitchen (02/0002)", rows)
        kalkaji = rows["Kalkaji (02/0004)"]
        self.assertEqual(kalkaji["classic_score"], 9.2)
        self.assertAlmostEqual(kalkaji["lat"], 28.540608)
        self.assertEqual(kalkaji["market"], "NCR")
        self.assertGreater(kalkaji["competitor_count"], 0)
        self.assertGreaterEqual(kalkaji["competitor_count_all"], kalkaji["competitor_count"])
        self.assertGreaterEqual(kalkaji["south_indian_density"], 0)
        self.assertLessEqual(kalkaji["south_indian_density"], 1)
        self.assertIsNone(kalkaji["aggregator_enabled"])
        self.assertIsNone(kalkaji["mall_reviews"])
        ideal = rows["Dosa Coffee - Ideal Plaza (01/0001)"]
        self.assertEqual(ideal["aggregator_enabled"], 1)
        self.assertIsNotNone(ideal["mall_reviews"])
        self.assertIsNone(ideal["anchors"])
        self.assertIsNone(ideal["food_court"])
        forum = rows["Dosa Coffee - Forum (0003)"]
        self.assertEqual(forum["aggregator_enabled"], 0)
        self.assertEqual(forum["food_court"], 1)
        self.assertEqual(rows["Shalimar Bagh (02/0015)"]["format"], "metro")
        shalimar = rows["Shalimar Bagh (02/0015)"]
        self.assertIsNotNone(shalimar["energy"])
        self.assertIsNotNone(shalimar["neighbour_brands"])


class OutcomeTests(unittest.TestCase):
    def test_mall_bills_and_apb_stay_blank(self):
        features = snapshot_rows("2026-10")
        outcomes = {row["store"]: row for row in outcome_rows(features)}
        for name in ("Dosa Coffee - Manisquare (0004)", "Dosa Coffee - Forum (0003)"):
            self.assertIsNone(outcomes[name]["bills_per_trading_day"])
            self.assertIsNone(outcomes[name]["apb"])
            self.assertIsNotNone(outcomes[name]["gross_per_trading_day"])
        ideal = outcomes["Dosa Coffee - Ideal Plaza (01/0001)"]
        self.assertIsNotNone(ideal["gross_per_trading_day"])
        self.assertIsNotNone(ideal["dine_in_share"])
        self.assertIsNotNone(ideal["famepilot_rating"])
        self.assertIsNotNone(ideal["bills_per_trading_day"])


class FitTests(unittest.TestCase):
    def test_weight_move_is_capped_and_small_formats_stay_put(self):
        priors = prior_weights()
        high = []
        for index in range(12):
            rank_driver = index / 11
            high.append({
                "store": f"H{index}",
                "format": "high_street",
                "rank": rank_driver,
                "x": _vector(energy=rank_driver, reviews=0.2, transport=0.2, premium=0.2, diversity=0.2, quality=0.2, anchor=1),
            })
        mall = [{
            "store": f"M{index}",
            "format": "mall",
            "rank": 0.5,
            "x": _vector(),
        } for index in range(MIN_FORMAT_N - 1)]
        fitted, frozen, keys = fit_pooled({"high_street": high, "mall": mall}, priors, steps=400)
        self.assertIn("mall", frozen)
        self.assertEqual(fitted["mall"], priors["mall"])
        low, high_cap = cap_bounds(priors["high_street"]["energy"])
        self.assertGreaterEqual(fitted["high_street"]["energy"], low - 1e-9)
        self.assertLessEqual(fitted["high_street"]["energy"], high_cap + 1e-9)
        self.assertGreater(fitted["high_street"]["energy"], priors["high_street"]["energy"])
        for value in fitted["high_street"].values():
            self.assertGreaterEqual(value, 0)

    def test_refit_records_spearman_loo_and_misses(self):
        features = []
        outcomes = []
        for index in range(10):
            features.append({
                "as_of": "2026-10",
                "store_id": f"s{index}",
                "store": f"Store {index}",
                "market": "NCR",
                "format": "high_street",
                "energy_of_6": 6 * (index / 9),
                "quality": 1,
                "anchor": 1,
                "diversity": 1,
                "transport": 0.4,
                "energy": index / 9,
                "reviews": 0.4,
                "premium": 0.4,
                "south_indian_density": None,
            })
            outcomes.append({
                "store": f"Store {index}",
                "gross_per_trading_day": 1000 + index * 100,
            })
        # One store is scored as if energy were high but sales are low, so leave-one-out can miss.
        features.append({
            "as_of": "2026-10",
            "store_id": "odd",
            "store": "Odd store",
            "market": "NCR",
            "format": "high_street",
            "energy_of_6": 6,
            "quality": 1,
            "anchor": 1,
            "diversity": 1,
            "transport": 0.4,
            "energy": 1,
            "reviews": 0.4,
            "premium": 0.4,
            "south_indian_density": None,
        })
        outcomes.append({"store": "Odd store", "gross_per_trading_day": 1000})
        payload = refit_model(features, outcomes, "2026-10")
        self.assertEqual(payload["status"], "proposed")
        self.assertEqual(payload["prior_version"], "prior")
        self.assertGreaterEqual(payload["n"], 8)
        self.assertIsNotNone(payload["spearman"])
        self.assertIsNotNone(payload["loo_mae"])
        self.assertTrue(payload["backtest"])
        self.assertTrue(any(row["miss"] for row in payload["backtest"]))
        joined = learning_rows(features, outcomes)
        self.assertTrue(all(row["rank"] is not None for row in joined))


class JarvisInputTests(unittest.TestCase):
    def test_sites_cover_stores_and_clusters(self):
        sites = input_index()["sites"]
        self.assertEqual(len(sites), 95)
        self.assertEqual(sum(1 for site in sites if site["site_type"] == "store"), 29)
        clusters = [site["site_id"] for site in sites if site["site_type"] == "candidate_cluster"]
        self.assertEqual(len(clusters), 66)
        self.assertTrue(any(site_id.startswith("NCR-C01") for site_id in clusters))
        self.assertTrue(any(site_id.startswith("NCR-C54") for site_id in clusters))
        self.assertTrue(any(site_id.startswith("KOL-C01") for site_id in clusters))
        self.assertTrue(any(site_id.startswith("KOL-C12") for site_id in clusters))

    def test_haldiram_is_out_of_strict_density_and_blank_reviews_stay_blank(self):
        stats = review_stats()
        self.assertEqual(stats["known"], 625)
        self.assertEqual(stats["blank"], 768)
        self.assertGreater(stats["mean_known"], stats["mean_if_blank_were_zero"])
        cp = next(site for site in input_index()["sites"] if site["site_id"].startswith("Connaught"))
        signal = south_indian_signal(cp["lat"], cp["lng"])
        self.assertGreater(signal["all_count"], signal["count"])
        self.assertTrue(signal["capped"])
        self.assertIn("Capped", signal["detail"])
        self.assertIn("Haldiram", signal["detail"])
        quiet = next(site for site in input_index()["sites"] if site["site_id"].startswith("Gurgaon Sec 10"))
        quiet_signal = south_indian_signal(quiet["lat"], quiet["lng"])
        self.assertFalse(quiet_signal["capped"])
        self.assertLess(quiet_signal["count"], 20)
        self.assertEqual(quiet_signal["count"], quiet_signal["all_count"])

    def test_delivery_percentile_and_worldpop_note(self):
        new_town = next(site for site in input_index()["sites"] if "New Town" in site["site_id"] and site["site_type"] == "store")
        signal = delivery_signal(new_town["lat"], new_town["lng"])
        self.assertEqual(signal["raw_restaurants"], 23)
        self.assertLessEqual(signal["restaurants"], 1)
        self.assertNotEqual(signal["restaurants"], 23)
        self.assertIn("percentile", signal["restaurant_detail"])
        self.assertIn("OpenStreetMap", signal["restaurant_detail"])
        self.assertIn("understates", signal["residential_detail"])
        self.assertIn("New Town", signal["about"])
        sector6 = next(site for site in input_index()["sites"] if site["site_id"].startswith("NCR-C02"))
        plain = delivery_signal(sector6["lat"], sector6["lng"])
        self.assertNotIn("understates", plain["about"])
        self.assertNotIn("understates", plain["residential_detail"])

    def test_ridership_keeps_the_latest_period_and_stays_data_coming(self):
        rajiv = next(station for station in metro_stations() if station["station"] == "Rajiv Chowk")
        self.assertEqual(rajiv["daily"], 210000)
        self.assertIn("Jun 2026", rajiv["period"])
        self.assertNotIn("216524", rajiv["period"])
        coverage = ridership_coverage()
        self.assertEqual(coverage["count"], 4)
        self.assertFalse(coverage["open"])
        self.assertEqual(
            {store["name"] for store in coverage["stores"]},
            {"CP", "Ideal Plaza", "Forum", "Swimming Club"},
        )
        cp = next(site for site in input_index()["sites"] if site["site_id"].startswith("Connaught"))
        signal = metro_signal(cp["lat"], cp["lng"])
        self.assertIsNone(signal["ridership"])
        self.assertIn("Rajiv Chowk", signal["station_detail"])
        self.assertIn("4 stores", signal["about"])
        self.assertIn("prior weight", signal["about"])
        self.assertNotIn(".csv", signal["about"])

    def test_score_page_shows_about_this_data(self):
        from unittest.mock import patch

        self.assertFalse(os.environ.get("LOCATION_DATA_DIR"))
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        place = {
            "name": "Test Cafe",
            "place_id": "p1",
            "geometry": {"location": {"lat": 22.561892, "lng": 88.490713}},
            "types": ["cafe"],
            "user_ratings_total": 40,
            "rating": 4.2,
            "business_status": "OPERATIONAL",
        }
        with patch("app.routes.location_finder.fetch_eateries", return_value=[place]), \
             patch("app.routes.location_finder.get_location_name", return_value="New Town, Kolkata"), \
             patch("app.routes.location_finder.fetch_places_by_type", return_value=[]):
            response = client.post("/location-finder", data={
                "latitude": "22.561892",
                "longitude": "88.490713",
                "radius": "500",
                "location_name": "New Town, Kolkata",
                "site_format": "cloud_kitchen",
            })
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("About this data", html)
        self.assertIn("Haldiram", html)
        self.assertIn("OpenStreetMap", html)
        self.assertIn("percentile within the city", html)
        self.assertIn("WorldPop 2020 understates this area", html)
        self.assertIn("4 stores", html)
        self.assertIn("data coming", html)
        self.assertNotIn(".csv", html)
        self.assertNotIn("401", html)


class ApprovalPageTests(unittest.TestCase):
    def setUp(self):
        self.previous = os.environ.pop("LOCATION_DATA_DIR", None)
        clear_cache()
        clear_approvals()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        clear_approvals()
        clear_cache()
        if self.previous is not None:
            os.environ["LOCATION_DATA_DIR"] = self.previous

    def _session(self, email):
        with self.client.session_transaction() as sess:
            if email:
                sess["user"] = {"name": "Siddhant Dalmia", "email": email}
            else:
                sess.clear()

    def test_v2026_10_explains_frozen_formats_before_approve(self):
        self._session(OWNER)
        html = self.client.get("/location-model").get_data(as_text=True)
        self.assertIn("Mall, metro and cloud kitchen are frozen in v2026-10b.", html)
        self.assertIn(
            "The mall score uses the prior weights, including aggregator-enabled, mall reviews and anchors.",
            html,
        )
        self.assertIn("Ideal Plaza, Forum and Rangoli Mall are the big misses.", html)
        self.assertIn("Spearman 0.41 means the model ranks stores moderately well.", html)
        self.assertIn(
            "Approve v2026-10b? Live scores will change for high-street sites. You can undo this.",
            html,
        )
        self.assertIn("Stores whose score moves most", html)
        self.assertIn("Frozen", html)
        self.assertNotIn(".csv", html)
        self.assertNotIn(".json", html)

    def test_revert_goes_back_to_the_previous_approved_version(self):
        folder = tempfile.TemporaryDirectory()
        previous = os.environ.get("LOCATION_DATA_DIR")
        os.environ["LOCATION_DATA_DIR"] = folder.name
        try:
            models = Path(folder.name) / "models"
            models.mkdir()
            for name in ("v2026-09", "v2026-10"):
                (models / f"{name}.json").write_text(
                    json.dumps({"version": name, "status": "proposed", "weights": {"high_street": {"energy": 0.3}}}),
                    encoding="utf-8",
                )
            self._session(OWNER)
            first = self.client.post("/location-model", data={
                "action": "approve", "version": "v2026-09", "confirm": "yes",
            })
            self.assertEqual(first.status_code, 200)
            self.assertEqual(latest_approved()["version"], "v2026-09")
            second = self.client.post("/location-model", data={
                "action": "approve", "version": "v2026-10", "confirm": "yes",
            })
            self.assertEqual(second.status_code, 200)
            self.assertEqual(latest_approved()["version"], "v2026-10")
            undone = self.client.post("/location-model", data={"action": "revert", "confirm": "yes"})
            self.assertEqual(undone.status_code, 200)
            self.assertIn("Live scores use v2026-09.", undone.get_data(as_text=True))
            self.assertEqual(latest_approved()["version"], "v2026-09")
            saved = json.loads((models / "v2026-10.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "proposed")
        finally:
            if previous is None:
                os.environ.pop("LOCATION_DATA_DIR", None)
            else:
                os.environ["LOCATION_DATA_DIR"] = previous
            folder.cleanup()
            clear_approvals()

    def test_logged_out_post_is_forbidden(self):
        self._session(None)
        response = self.client.post("/location-model", data={
            "action": "approve",
            "version": "v2026-10",
            "confirm": "yes",
        })
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(latest_approved())

    def test_healthz_db_is_public_and_omits_the_url(self):
        response = self.client.get("/healthz/db")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(set(body), {"dialect", "persistent"})
        self.assertEqual(body["dialect"], "sqlite")
        self.assertIs(body["persistent"], True)
        text = response.get_data(as_text=True)
        self.assertNotIn("sqlite://", text)
        self.assertNotIn(_DB.name, text)

    def test_hosted_sqlite_hides_approve_and_refuses_the_write(self):
        previous = {name: os.environ.get(name) for name in ("RENDER", "FLASK_ENV")}
        try:
            os.environ["RENDER"] = "true"
            os.environ.pop("FLASK_ENV", None)
            health = self.client.get("/healthz/db").get_json()
            self.assertEqual(health, {"dialect": "sqlite", "persistent": False})
            self._session(OWNER)
            html = self.client.get("/location-model").get_data(as_text=True)
            self.assertIn("Approvals can't be saved yet. The database isn't permanent.", html)
            self.assertNotIn(">Approve</button>", html)
            self.assertNotIn(">Undo approval</button>", html)
            posted = self.client.post("/location-model", data={
                "action": "approve",
                "version": "v2026-10",
                "confirm": "yes",
            })
            self.assertEqual(posted.status_code, 400)
            self.assertIn(
                "Approvals can't be saved yet. The database isn't permanent.",
                posted.get_data(as_text=True),
            )
            self.assertIsNone(latest_approved())

            os.environ.pop("RENDER", None)
            os.environ["FLASK_ENV"] = "production"
            health = self.client.get("/healthz/db").get_json()
            self.assertEqual(health, {"dialect": "sqlite", "persistent": False})
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_postgres_on_render_stays_persistent(self):
        from unittest.mock import patch

        from app.extensions import db

        previous = os.environ.get("RENDER")
        os.environ["RENDER"] = "true"
        try:
            with self.app.app_context():
                with patch.object(db.engine.dialect, "name", "postgresql"):
                    body = self.client.get("/healthz/db").get_json()
            self.assertEqual(body, {"dialect": "postgresql", "persistent": True})
            self._session(OWNER)
            with self.app.app_context():
                with patch.object(db.engine.dialect, "name", "postgresql"):
                    html = self.client.get("/location-model").get_data(as_text=True)
            self.assertIn(">Approve</button>", html)
            self.assertNotIn("Approvals can't be saved yet.", html)
        finally:
            if previous is None:
                os.environ.pop("RENDER", None)
            else:
                os.environ["RENDER"] = previous


class PageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("LOCATION_DATA_DIR")
        os.environ["LOCATION_DATA_DIR"] = self.tmp.name
        clear_cache()
        clear_approvals()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("LOCATION_DATA_DIR", None)
        else:
            os.environ["LOCATION_DATA_DIR"] = self.previous
        self.tmp.cleanup()
        clear_approvals()
        clear_cache()

    def _session(self, email):
        with self.client.session_transaction() as sess:
            if email:
                sess["user"] = {"name": "Siddhant Dalmia", "email": email}
            else:
                sess.clear()

    def test_scripts_write_month_files_and_the_page_is_owner_only(self):
        feature_path = write_snapshot("2026-10")
        outcome_path = write_outcomes("2026-10")
        model_path = write_refit("2026-10")
        self.assertTrue(str(feature_path).endswith("2026-10.csv"))
        with feature_path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            self.assertIn("south_indian_density", reader.fieldnames)
            body = list(reader)
        self.assertTrue(all(row["competitor_count"] == "" for row in body))
        with outcome_path.open(encoding="utf-8") as handle:
            outcomes = {row["store"]: row for row in csv.DictReader(handle)}
        self.assertEqual(outcomes["Dosa Coffee - Forum (0003)"]["apb"], "")
        self.assertEqual(outcomes["Dosa Coffee - Manisquare (0004)"]["bills_per_trading_day"], "")
        payload = json.loads(model_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "proposed")
        self.assertIn("loo_mae", payload)

        self._session(None)
        self.assertEqual(self.client.get("/location-model").status_code, 302)
        self._session(OTHER)
        blocked = self.client.get("/location-model")
        self.assertEqual(blocked.status_code, 302)
        self._session(OWNER)
        page = self.client.get("/location-model").get_data(as_text=True)
        self.assertIn("Location model", page)
        self.assertIn("What are we missing", page)
        self.assertIn("Approve", page)
        self.assertIn("You can undo this.", page)
        self.assertIn("Stores whose score moves most", page)
        self.assertNotIn(".csv", page)
        self.assertIn('name="theme-color" content="#f7f6f3"', page)
        self._session(OTHER)
        denied = self.client.post("/location-model", data={
            "action": "approve",
            "version": payload["version"],
            "confirm": "yes",
        })
        self.assertEqual(denied.status_code, 403)
        self._session(OWNER)
        unconfirmed = self.client.post("/location-model", data={
            "action": "approve",
            "version": payload["version"],
        })
        self.assertEqual(unconfirmed.status_code, 400)
        self.assertIsNone(latest_approved())
        approved = self.client.post("/location-model", data={
            "action": "approve",
            "version": payload["version"],
            "confirm": "yes",
        })
        self.assertEqual(approved.status_code, 200)
        approved_html = approved.get_data(as_text=True)
        self.assertIn("Approved.", approved_html)
        self.assertIn(OWNER, approved_html)
        self.assertIn("Undo approval", approved_html)
        saved = json.loads(model_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "proposed")
        self.assertEqual(latest_approved()["version"], payload["version"])
        reverted = self.client.post("/location-model", data={"action": "revert", "confirm": "yes"})
        self.assertEqual(reverted.status_code, 200)
        reverted_html = reverted.get_data(as_text=True)
        self.assertIn("prior weights", reverted_html)
        self.assertIn("Reverted", reverted_html)
        self.assertIn(OWNER, reverted_html)
        self.assertIsNone(latest_approved())

    def test_score_page_logs_the_prediction_and_shows_the_badge(self):
        from unittest.mock import patch

        place = {
            "name": "Test Cafe",
            "place_id": "p1",
            "geometry": {"location": {"lat": 22.55, "lng": 88.35}},
            "types": ["cafe"],
            "user_ratings_total": 25000,
            "rating": 4.6,
            "price_level": 2,
            "business_status": "OPERATIONAL",
        }
        with patch("app.routes.location_finder.fetch_eateries", return_value=[place]), \
             patch("app.routes.location_finder.get_location_name", return_value="Park Street, Kolkata"), \
             patch("app.routes.location_finder.fetch_places_by_type", return_value=[]):
            response = self.client.post("/location-finder", data={
                "latitude": "22.55",
                "longitude": "88.35",
                "radius": "500",
                "location_name": "Park Street, Kolkata",
                "site_format": "high_street",
            })
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Why this score", html)
        self.assertIn("Model prior", html)
        self.assertIn("South Indian competitor density", html)
        self.assertIn("data coming", html)
        self.assertNotIn(".csv", html)
        logged = list(csv.DictReader((Path(self.tmp.name) / "predictions.csv").open(encoding="utf-8")))
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["format"], "high_street")
        self.assertEqual(logged[0]["model_version"], "prior")
        self.assertTrue(logged[0]["score"])

    def test_log_helper_writes_the_header_once(self):
        log_prediction("A site", 22.5, 88.3, "metro", "prior", 6.2, [
            {"label": "Energy", "status": "in", "points": 1.2},
            {"label": "Station ridership", "status": "data coming", "points": None},
        ])
        path = Path(self.tmp.name) / "predictions.csv"
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        self.assertEqual(rows[0]["site_id"], "metro-22.50000-88.30000")
        self.assertIn("data coming", rows[0]["breakdown"])


if __name__ == "__main__":
    unittest.main()
