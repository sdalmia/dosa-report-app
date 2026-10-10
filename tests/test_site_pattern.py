import os
import tempfile
import unittest

os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-key")
_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _DB.name)
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.site_pattern import (
    METRO_WEIGHTS,
    blend,
    clear_cache,
    load_board,
    metro_parts,
    station_distance_unit,
)
from app import create_app


class BlendTests(unittest.TestCase):
    def test_missing_input_is_left_out_and_zero_is_kept(self):
        left_out = blend([
            {"key": "a", "label": "A", "weight": 0.4, "value": 1, "detail": ""},
            {"key": "b", "label": "B", "weight": 0.4, "value": None, "detail": ""},
            {"key": "c", "label": "C", "weight": 0.2, "value": 1, "detail": ""},
        ])
        self.assertEqual(left_out["score"], 10)
        missing = next(part for part in left_out["parts"] if part["key"] == "b")
        self.assertEqual(missing["status"], "data coming")
        self.assertIsNone(missing["points"])

        counted = blend([
            {"key": "a", "label": "A", "weight": 0.4, "value": 1, "detail": ""},
            {"key": "b", "label": "B", "weight": 0.4, "value": 0, "detail": ""},
            {"key": "c", "label": "C", "weight": 0.2, "value": 1, "detail": ""},
        ])
        self.assertEqual(counted["score"], 6)

    def test_station_distance_does_not_treat_blank_as_zero(self):
        self.assertIsNone(station_distance_unit(None))
        self.assertEqual(station_distance_unit(40), 1)
        self.assertEqual(station_distance_unit(2000), 0)


class NcrAndMetroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clear_cache()
        cls.board = load_board()
        cls.by_name = {store["name"]: store for store in cls.board["stores"]}

    def test_rescored_pins_keep_the_old_score_in_the_note(self):
        kalkaji = self.by_name["Kalkaji (02/0004)"]
        paschim = self.by_name["Paschim Vihar (02/0003)"]
        shalimar = self.by_name["Shalimar Bagh (02/0015)"]
        sec10 = self.by_name["Gurgaon Sec 10 (02/0014)"]
        self.assertEqual(kalkaji["classic_score"], 9.2)
        self.assertEqual(kalkaji["earlier_score"], 2.3)
        self.assertFalse(kalkaji["repin"])
        self.assertEqual(paschim["classic_score"], 6.7)
        self.assertEqual(paschim["earlier_score"], 7.5)
        self.assertFalse(paschim["repin"])
        self.assertEqual(shalimar["classic_score"], 4.5)
        self.assertEqual(shalimar["earlier_score"], 2.6)
        self.assertFalse(shalimar["repin"])
        self.assertEqual(sec10["classic_score"], 7.9)
        self.assertEqual(sec10["earlier_score"], 7.9)
        self.assertFalse(sec10["repin"])
        self.assertIn("Earlier landmark pin scored 2.3", kalkaji["score_note"])

    def test_shalimar_is_a_metro_unit_and_ridership_is_not_zero(self):
        shalimar = self.by_name["Shalimar Bagh (02/0015)"]
        self.assertEqual(shalimar["format_label"], "Metro / transit unit")
        self.assertEqual(METRO_WEIGHTS["energy"], 0.15)
        self.assertEqual(METRO_WEIGHTS["reviews"], 0.05)
        self.assertLess(METRO_WEIGHTS["energy"], 0.35)
        parts = {part["key"]: part for part in shalimar["pattern"]["parts"]}
        self.assertEqual(parts["ridership"]["status"], "data coming")
        self.assertEqual(parts["ridership"]["weight_pct"], 20)
        self.assertEqual(parts["distance"]["status"], "in")
        self.assertEqual(parts["distance"]["value"], 1)
        self.assertIn("Shalimar Bagh", parts["distance"]["detail"])
        self.assertIsNone(parts["ridership"]["points"])
        self.assertEqual(parts["energy"]["weight_pct"], 15)
        about = " ".join(shalimar["pattern"].get("about") or [])
        self.assertIn("4 stores", about)
        self.assertIn("Swimming Club", about)
        self.assertIn("data coming", about)
        self.assertNotIn(".csv", about)
        self.assertIsNotNone(shalimar["pattern_score"])
        self.assertGreater(shalimar["google_rating"], 4)

    def test_loaded_ridership_keeps_its_source(self):
        signals = {
            "station_m": 40,
            "station_detail": "Shalimar Bagh",
            "ridership": 50000,
            "ridership_source": "DMRC published daily ridership",
            "ridership_band": (4.0, 5.5),
            "energy": 0.2,
            "energy_detail": "1.1 / 6",
            "reviews": 4546,
            "reviews_detail": "4546 reviews",
            "transport": 0.43,
            "transport_detail": "0.43 / 1",
            "premium": 0.8,
            "premium_detail": "",
            "diversity": 1,
            "diversity_detail": "",
            "quality": 1,
            "quality_detail": "",
            "anchor": 1,
        }
        parts = {part["key"]: part for part in blend(metro_parts(signals, (3, 5)))["parts"]}
        self.assertEqual(parts["ridership"]["status"], "in")
        self.assertIn("DMRC published daily ridership", parts["ridership"]["detail"])
        self.assertIn("Source:", parts["ridership"]["detail"])

    def test_page_lists_candidates_and_does_not_name_files(self):
        app = create_app()
        client = app.test_client()
        html = client.get("/location-finder").get_data(as_text=True)
        self.assertEqual(html.count("<tr>"), 2 + 66 + 30)
        self.assertIn("Best next sites", html)
        self.assertIn("Show neighbour brands", html)
        self.assertIn("Metro / transit unit", html)
        self.assertIn("Re-pin needed", html)
        self.assertIn("data coming", html)
        self.assertIn("Earlier landmark pin scored 2.6", html)
        self.assertNotIn(".csv", html)
        self.assertIn('name="theme-color" content="#f7f6f3"', html)
        self.assertEqual(len(self.board["outlets"]), 1228)
        self.assertEqual(len(self.board["brands"]), 11)
        self.assertEqual(sum(1 for area in self.board["candidates"] if area["airport"]), 3)


if __name__ == "__main__":
    unittest.main()
