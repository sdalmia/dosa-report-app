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
        self.assertNotIn("Restroworks login", tony)
        logan = (FLAGS / "logan.csv").read_text(encoding="utf-8")
        self.assertNotIn("WhatsApp", logan)
        self.assertNotIn("Reelo", logan)
        alfred = (FLAGS / "alfred.csv").read_text(encoding="utf-8")
        self.assertEqual(alfred.strip(), "area,severity,title,detail,owner,as_of,source")
        self.assertNotIn("Batcave", alfred)

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
        self.assertNotIn("WhatsApp", titles)
        self.assertNotIn("Batcave", titles)
        self.assertNotIn("Restroworks login", titles)
        self.assertIn("Staff are not using Frontlyne", titles)
        self.assertIn("07-10 salary run", titles)
        self.assertIn("North ticket size slipping", titles)
        areas = {row["area"] for row in visible}
        self.assertIn("people", areas)
        self.assertIn("accounts", areas)
        self.assertNotIn("alfred.csv", {row["file"] for row in visible})
        self._login("dalmia.siddhant@gmail.com")
        html = self.client.get("/flags").get_data(as_text=True)
        payload = self.client.get("/flags.json").get_json()
        blob = html + " ".join(item["title"] for item in payload["flags"])
        for bit in RESTRICTED_BITS:
            self.assertIn(bit, blob)
        self.assertIn('id="area-people"', html)
        self.assertNotIn("Batcave", html)
        self.assertNotIn("WhatsApp", html)

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
        self.assertIn("North ticket size slipping", html)
        self.assertIn("North ticket size slipping", titles)
        self.assertNotIn("WhatsApp", html)
        self.assertNotIn("Batcave", html)
        self.assertNotIn("Restroworks login", html)
        self.assertNotIn("accounts", areas)
        self.assertNotIn("people", areas)
        self.assertIn("sales", areas)
        self.assertEqual(page.get_data(as_text=True).count('class="flag-card'), 5)
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

    def test_header_only_and_empty_files_add_nothing(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        Path(folder.name, "alfred.csv").write_text(
            "area,severity,title,detail,owner,as_of,source\n",
            encoding="utf-8",
        )
        Path(folder.name, "blank.csv").write_text("", encoding="utf-8")
        rows = load_flag_rows(folder.name, today=date(2026, 10, 9))
        self.assertEqual(rows, [])
        os.environ["FLAGS_DATA_DIR"] = folder.name
        self._login("asha@dosacoffee.com")
        page = self.client.get("/dashboard")
        flags = self.client.get("/flags")
        payload = self.client.get("/flags.json")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(flags.status_code, 200)
        self.assertEqual(payload.status_code, 200)
        self.assertEqual(payload.get_json()["flags"], [])
        self.assertNotIn('class="flag-card', page.get_data(as_text=True))
        self.assertIn("No flags to show", page.get_data(as_text=True))


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
            by_key["all"]["comparable_gross"] / by_key["all"]["comparable_bills"],
        )
        self.assertGreater(by_key["all"]["gross_value"], by_key["all"]["comparable_gross"])
        bill_alerts = " ".join(alert["text"] for alert in view["alerts"] if alert["kind"] == "Bills")
        self.assertNotIn("Manisquare", bill_alerts)
        self.assertNotIn("Forum", bill_alerts)
        self.assertTrue(by_key["East"]["gross_change"])
        self.assertNotEqual(by_key["all"]["gross"], "₹0")
        html = self.client.get("/dashboard").get_data(as_text=True)
        self.assertEqual(view["window_subtitle"], "10 Sep – 9 Oct · vs last Friday")
        self.assertIn("Gross", html)
        self.assertIn("10 Sep – 9 Oct · vs last Friday", html)
        self.assertIn("Calculated. Gross divided by bills.", html)
        self.assertNotIn("posist_daily", html)
        self.assertNotIn("days with a row", html)
        self.assertNotIn(".csv", html)
        self.assertNotIn(".xlsx", html)
        self.assertIn("viewport", html)
        self.assertIn("theme.css", html)
        self.assertIn("Brief", html)
        self.assertIn('href="/brief"', html)
        self.assertIn('href="/scorecard"', html)
        self.assertIn("See all stores", html)
        self.assertIn("See procurement", html)
        self.assertIn("Store Health", html)
        self.assertIn("Zomato Settlement Uploader", html)
        self.assertIn("Ingredient Price Tracker", html)
        self.assertIn("Location Finder", html)
        self.assertIn("/upload", html)
        self.assertIn("/ingredient-tracker/", html)
        self.assertIn("/location-finder", html)
        self.assertIn("/store-health", html)
        self.assertIn("₹20,90,655.02", html)
        self.assertIn("15 Nov 2026", html)
        self.assertLessEqual(html.count('class="league-row"'), 10)
        self.assertLessEqual(html.count('class="alert-row"'), 5)
        self.assertEqual(html.count('<article class="tile">'), min(3, len(view["procurement"])))
        self.assertIn('class="tile rep-compact"', html)
        stores = self.client.get("/stores").get_data(as_text=True)
        self.assertGreater(stores.count('class="league-row"'), html.count('class="league-row"'))
        buying = self.client.get("/procurement").get_data(as_text=True)
        self.assertGreater(buying.count("<article class=\"tile\">"), 3)
        self.assertNotIn(".xlsx", buying)
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

    def test_light_is_the_default_theme(self):
        root = Path(__file__).resolve().parents[1]
        base = (root / "app/templates/base.html").read_text(encoding="utf-8")
        home = (root / "app/templates/home.html").read_text(encoding="utf-8")
        css = (root / "static/css/theme.css").read_text(encoding="utf-8")
        script = (root / "static/js/command.js").read_text(encoding="utf-8")
        for text in (base, home):
            self.assertIn('stored === "dark" ? "dark" : "light"', text)
            self.assertNotIn("prefers-color-scheme", text)
        self.assertNotIn("prefers-color-scheme", css)
        self.assertNotIn("prefers-color-scheme", script)
        tokens = css.split('html[data-theme="dark"]', 1)[0]
        self.assertIn("--bg: #f7f6f3", tokens)
        self.assertIn("--surface: #ffffff", tokens)
        self.assertIn("--text: #141414", tokens)
        self.assertIn("--text-muted: #3f3a33", tokens)

    def test_consumption_pack_and_base_kitchen_use_the_files(self):
        root = Path(__file__).resolve().parents[1] / "data" / "procurement"
        tiles = {tile["id"]: tile for tile in procurement_tiles(root)}
        bought = " ".join(
            f"{line['label']} {line['value']}" for line in tiles["bought_consumed"]["lines"]
        )
        self.assertIn("₹20,90,655.02", bought)
        self.assertIn("₹12,49,845.52", bought)
        self.assertIn("₹15,00,003.85", bought)
        self.assertIn("Kolkata", bought)
        self.assertIn("Delhi", bought)
        stock = " ".join(
            f"{line['label']} {line['value']}" for line in tiles["warehouse"]["lines"]
        )
        self.assertIn("₹11,69,932", stock)
        self.assertIn("₹21,74,378", stock)
        self.assertIn("₹10,04,447", stock)
        self.assertIn("₹14,89,757", stock)
        self.assertIn("₹26,18,445", stock)
        self.assertTrue(tiles["overstock"]["lines"])
        self.assertTrue(tiles["no_purchase"]["lines"])
        self.assertTrue(tiles["packaging"]["lines"])
        self.assertIn("₹44,115.68", tiles["wastage"]["lines"][0]["value"])
        hershey = " ".join(
            f"{line['label']} {line['value']}" for line in tiles["hershey"]["lines"]
        )
        self.assertIn("IN-1854", hershey)
        self.assertIn("₹1,80,174", hershey)
        summary = " ".join(
            f"{line['label']} {line['value']}" for line in tiles["purchase_summary"]["lines"]
        )
        self.assertIn("₹73,05,434.52", summary)
        self.assertIn("Grand total", summary)
        headlines = " ".join(line["label"] for line in tiles["headlines"]["lines"])
        self.assertIn("Warehouses absorbed", headlines)
        self.assertEqual(tiles["bought_consumed"]["period"], "1 Oct 2026 to 8 Oct 2026")


if __name__ == "__main__":
    unittest.main()
