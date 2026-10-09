import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _DB.name)
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import create_app
from app.access import DEFAULT_OWNER_EMAILS, is_owner, owner_emails
from app.flags import load_flag_rows, visible_flags
from app.owner_dashboard import build_owner_dashboard
from app.procurement import procurement_tiles

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ROOT / "data" / "flags"
RESTRICTED_BITS = (
    "07-10 salary run",
    "director's personal HDFC",
    "Frontlyne",
    "Gurgaon Sec 10 lost 4 staff",
    "probations overdue",
)


class FlagAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        os.environ.pop("STORE_HEALTH_DATA_DIR", None)
        os.environ.pop("FLAGS_DATA_DIR", None)
        os.environ.pop("OWNER_EMAILS", None)

    def _login(self, email):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Tester", "email": email}
            sess["user_email"] = email

    def test_shipped_files_keep_the_given_names(self):
        expected = {
            "tony.csv",
            "logan.csv",
            "alfred.csv",
            "procurement.csv",
            "accountant.csv",
            "hr.csv",
        }
        self.assertTrue(expected <= {path.name for path in FLAGS.glob("*.csv")})
        tony = (FLAGS / "tony.csv").read_text(encoding="utf-8")
        self.assertTrue(tony.startswith("area,severity,title,detail,owner,as_of,source"))
        self.assertIn("North ticket size slipping", tony)
        self.assertIn("marketing,red,WhatsApp Utility credits", (FLAGS / "logan.csv").read_text(encoding="utf-8"))

    def test_default_owners_and_override(self):
        self.assertEqual(
            owner_emails(),
            {email.casefold() for email in DEFAULT_OWNER_EMAILS},
        )
        self.assertTrue(is_owner("Siddhant@Dalgreenfoods.com"))
        self.assertFalse(is_owner("asha@dosacoffee.com"))
        os.environ["OWNER_EMAILS"] = "owner@example.com, Second@Example.com"
        self.assertEqual(owner_emails(), {"owner@example.com", "second@example.com"})
        self.assertTrue(is_owner("second@example.com"))
        self.assertFalse(is_owner("siddhant@dalgreenfoods.com"))

    def test_owner_sees_accounts_and_people_including_frontlyne(self):
        rows = load_flag_rows(FLAGS, today=date(2026, 10, 9))
        visible = visible_flags(rows, "siddhant@dalgreenfoods.com")
        titles = " ".join(row["title"] for row in visible)
        self.assertIn("WhatsApp Utility credits", titles)
        self.assertIn("Staff are not using Frontlyne", titles)
        self.assertIn("07-10 salary run", titles)
        areas = {row["area"] for row in visible}
        self.assertIn("marketing", areas)
        self.assertIn("people", areas)
        self.assertIn("accounts", areas)
        self._login("dalmia.siddhant@gmail.com")
        html = self.client.get("/flags").get_data(as_text=True)
        payload = self.client.get("/flags.json").get_json()
        blob = html + " ".join(item["title"] for item in payload["flags"])
        for bit in RESTRICTED_BITS:
            self.assertIn(bit, blob)
        self.assertIn('id="area-marketing"', html)
        self.assertIn('id="area-people"', html)
        self.assertIn("WhatsApp Utility credits", html)

    def test_non_owner_does_not_receive_accounts_or_people(self):
        self._login("asha@dosacoffee.com")
        page = self.client.get("/dashboard")
        flags = self.client.get("/flags")
        payload = self.client.get("/flags.json")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(flags.status_code, 200)
        html = page.get_data(as_text=True) + flags.get_data(as_text=True)
        body = payload.get_json()
        areas = {item["area"] for item in body["flags"]}
        titles = " ".join(item["title"] for item in body["flags"])
        for bit in RESTRICTED_BITS:
            self.assertNotIn(bit, html)
            self.assertNotIn(bit, titles)
        self.assertIn("WhatsApp Utility credits", html)
        self.assertIn("WhatsApp Utility credits", titles)
        self.assertNotIn("accounts", areas)
        self.assertNotIn("people", areas)
        self.assertIn("marketing", areas)
        self.assertEqual(html.count('class="flag-card'), 5)
        self.assertIn("See all", page.get_data(as_text=True))

    def test_bad_row_is_skipped_and_training_is_kept(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name, "extra.csv")
        path.write_text(
            "area,severity,title,detail,owner,as_of,source\n"
            "training,amber,Floor training is late,One line,Ops,2026-10-09,manual\n"
            "sales,green,Not a real severity,skip,Ops,2026-10-09,manual\n"
            "sales,red,,missing title,Ops,2026-10-09,manual\n"
            "sales,red,Too old,hidden,Ops,2026-10-01,manual\n"
            "marketing,red,Still in window,keep,Ops,2026-10-02,manual\n",
            encoding="utf-8",
        )
        with self.assertLogs("app.flags", level="WARNING") as caught:
            rows = load_flag_rows(folder.name, today=date(2026, 10, 9))
        self.assertTrue(any("not red or amber" in line for line in caught.output))
        titles = [row["title"] for row in rows]
        self.assertIn("Floor training is late", titles)
        self.assertIn("Still in window", titles)
        self.assertNotIn("Too old", titles)
        self.assertNotIn("Not a real severity", titles)
        self.assertEqual([row["area"] for row in rows if row["title"] == "Floor training is late"], ["training"])


class OwnerDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        os.environ.pop("STORE_HEALTH_DATA_DIR", None)
        os.environ.pop("OWNER_EMAILS", None)
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Asha Rao", "email": "asha@dosacoffee.com"}

    def test_window_splits_and_does_not_invent_zero(self):
        view = build_owner_dashboard(today=date(2026, 10, 9))
        by_key = {row["key"]: row for row in view["regions"]}
        self.assertEqual(
            round((by_key["East"]["gross_value"] + by_key["North"]["gross_value"]) * 100),
            round(by_key["all"]["gross_value"] * 100),
        )
        self.assertEqual(
            by_key["all"]["apb_value"],
            by_key["all"]["gross_value"] / by_key["all"]["bills_value"],
        )
        self.assertTrue(by_key["East"]["gross_change"])
        self.assertNotEqual(by_key["all"]["gross"], "₹0")
        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("Gross", html)
        self.assertIn("Calculated. Gross divided by bills.", html)
        self.assertIn("viewport", html)
        self.assertIn("theme.css", html)
        self.assertIn("Store Health", html)
        self.assertIn("Zomato Settlement Uploader", html)
        self.assertIn("Ingredient Price Tracker", html)
        self.assertIn("Location Finder", html)
        self.assertIn("/upload", html)
        self.assertIn("/ingredient-tracker/", html)
        self.assertIn("/location-finder", html)
        self.assertIn("/store-health", html)
        self.assertIn("No data", html)
        self.assertNotIn("Not in feed", html)
        self.assertTrue(view["chart"]["svg"])
        self.assertTrue(view["chart"]["last_band"])
        self.assertTrue(any(day["tier"] for day in view["next_days"]))
        self.assertEqual(len(view["next_days"]), 8)

    def test_procurement_tile_uses_the_newest_dated_file(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        Path(folder.name, "bought-consumed-2026-09-01.csv").write_text(
            "city,bought,consumed\nKolkata,10,4\n",
            encoding="utf-8",
        )
        Path(folder.name, "bought-consumed-2026-10-08.csv").write_text(
            "city,bought,consumed\nDelhi,30,16\n",
            encoding="utf-8",
        )
        tiles = {tile["id"]: tile for tile in procurement_tiles(folder.name)}
        bought = tiles["bought_consumed"]
        self.assertEqual(bought["source"], "bought-consumed-2026-10-08.csv")
        self.assertIn("Delhi", bought["lines"][0]["label"])
        self.assertNotIn("Kolkata", bought["lines"][0]["value"])
        self.assertEqual(tiles["wastage"]["note"], "No data")
        self.assertIn("data/procurement/", tiles["wastage"]["source"])


if __name__ == "__main__":
    unittest.main()
