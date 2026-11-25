"""The command centre shell stays light, navigable, and free of file names."""

import os
import tempfile
import unittest
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _DB.name)
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import create_app

ROOT = Path(__file__).resolve().parents[1]


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant", "email": "siddhant@dalgreenfoods.com"}
            sess["user_email"] = "siddhant@dalgreenfoods.com"

    def test_light_is_the_default_and_the_nav_is_on_every_working_page(self):
        css = (ROOT / "static/css/theme.css").read_text(encoding="utf-8")
        self.assertIn("font-family: Inter", css)
        self.assertIn("tabular-nums", css)
        self.assertIn(".cc-side", css)
        self.assertIn(".cc-bottom", css)
        home = (ROOT / "app/templates/base.html").read_text(encoding="utf-8")
        self.assertIn('stored === "dark" ? "dark" : "light"', home)
        for path in ("/board", "/store-health", "/tickets", "/procurement", "/dashboard"):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200, path)
            html = page.get_data(as_text=True)
            self.assertIn('class="cc-side"', html, path)
            self.assertIn('class="cc-bottom"', html, path)
            for label in ("Home", "Sales", "Reviews", "Procurement", "Wizard", "Location"):
                self.assertIn(f">{label}</span>", html, path)
            self.assertIn("/locations", html, path)
            self.assertNotIn(".csv", html, path)
            self.assertNotIn("data-theme=\"dark\"", html.split("<body", 1)[0], path)

    def test_location_leads_with_the_top_area(self):
        html = self.client.get("/locations").get_data(as_text=True)
        self.assertEqual(self.client.get("/locations").status_code, 200)
        self.assertIn("Top score", html)
        self.assertIn("v2026-11", html)
        self.assertIn("proposed", html.casefold())
        self.assertIn("Model accuracy: moderate; treat as a shortlist", html)
        self.assertNotIn("leave-one-out", html.casefold())
        self.assertNotIn("rank match", html.casefold())
        self.assertIn("loc-pin", html)
        self.assertNotIn("Faridabad", html)
        self.assertNotIn(".csv", html)

    def test_home_puts_the_numbers_in_cards(self):
        html = self.client.get("/board").get_data(as_text=True)
        self.assertIn("kpi-card", html)
        self.assertIn("kpi-spark", html)
        self.assertIn("Red flags", html)


if __name__ == "__main__":
    unittest.main()
