"""Phone layout, owner money, filters, and food-court bill rules."""

import os
import tempfile
import unittest

from tests.stitch import page
from datetime import date
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _DB.name)
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import create_app
from app.food_courts import is_mall_food_court
from app.procurement import procurement_tiles
from app.store_health.present import format_owner_rupee


class PhoneUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant Dalmia", "email": "siddhant@dalgreenfoods.com"}
            sess["user_email"] = "siddhant@dalgreenfoods.com"

    def test_header_and_drawer_css(self):
        css = (Path(__file__).resolve().parents[1] / "static/css/theme.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 399px)", css)
        self.assertIn(".cc-hello { display: none; }", css)
        self.assertIn("52px + env(safe-area-inset-bottom)", css)
        html = page(self.client, "/dashboard")
        self.assertIn("cc-search-drawer", html)
        self.assertIn("cc-search-header", html)
        self.assertIn(">Today<", html)
        self.assertIn(">Outside<", html)
        self.assertIn("Fame Pilot", html)
        self.assertIn('name="cc_store"', html)
        self.assertIn("Delhi NCR", html)
        self.assertIn("Last 7 days", html)

    def test_owner_rupee_has_no_paise(self):
        self.assertEqual(format_owner_rupee(490578.11), "₹4.9L")
        self.assertEqual(format_owner_rupee(490578), "₹4.9L")
        self.assertEqual(format_owner_rupee(1250.6), "₹1,251")
        self.assertEqual(format_owner_rupee(13_000_000), "₹1.3Cr")
        self.assertTrue(is_mall_food_court("Dosa Coffee - Manisquare (0004)"))
        self.assertTrue(is_mall_food_court("Dosa Coffee - Forum (0003)"))
        self.assertFalse(is_mall_food_court("Dosa Coffee - Ideal Plaza (01/0001)"))

    def test_filter_is_remembered_for_the_session(self):
        first = self.client.get("/dashboard?cc_city=Kolkata&cc_range=7")
        self.assertEqual(first.status_code, 200)
        page = first.get_data(as_text=True)
        self.assertIn("Kolkata", page)
        again = self.client.get("/scorecard")
        self.assertEqual(again.status_code, 200)
        scorecard = again.get_data(as_text=True)
        self.assertIn('value="Kolkata" selected', scorecard)
        self.assertIn('value="7" selected', scorecard)

    def test_bought_and_warehouse_cards_use_separate_rows(self):
        root = Path(__file__).resolve().parents[1] / "data" / "procurement"
        tiles = {tile["id"]: tile for tile in procurement_tiles(root)}
        bought = tiles["bought_consumed"]["lines"][0]
        self.assertEqual([row["label"] for row in bought["stats"]], ["Bought", "Used", "Difference"])
        self.assertNotIn("consumed", bought["value"].casefold())
        stock = tiles["warehouse"]["lines"][0]
        self.assertEqual([row["label"] for row in stock["stats"]], ["Opening", "Closing", "Change"])
        html = self.client.get("/procurement").get_data(as_text=True)
        self.assertIn("stat-row", html)
        self.assertIn("₹20,90,655.02", html)


if __name__ == "__main__":
    unittest.main()
