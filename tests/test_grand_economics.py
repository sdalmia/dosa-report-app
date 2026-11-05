"""Owner economics page, the tidy table, and the training threat."""

import csv
import gzip
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _DB.name)
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import create_app

ROOT = Path(__file__).resolve().parents[1]
GE = ROOT / "data" / "finance" / "grand_economics"
OWNER = "siddhant@dalgreenfoods.com"


def _parser():
    spec = importlib.util.spec_from_file_location("ge_parse", GE / "parse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GrandEconomicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()
        cls.parser = _parser()

    def setUp(self):
        os.environ.pop("OWNER_EMAILS", None)
        os.environ.pop("TALLY_LEDGER_FILE", None)
        os.environ.pop("GRAND_ECONOMICS_DIR", None)
        with self.client.session_transaction() as sess:
            sess.clear()

    def _login(self, email):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Tester", "email": email}
            sess["user_email"] = email

    def test_parser_keeps_salary_cam_gas_ads_and_skips_empty_months(self):
        self.assertEqual(self.parser.canonical_line("Staff Salary & Bonus"), "salary")
        self.assertEqual(self.parser.canonical_line("Less: Tax"), "tax")
        self.assertEqual(self.parser.canonical_line("CAM"), "cam")
        self.assertEqual(self.parser.canonical_line("Gas"), "gas")
        with (GE / "grand_economics_tidy.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        forum = {
            row["line"]: row["value"]
            for row in rows
            if row["store"] == "Forum Mall" and row["month"] == "2026-09" and row["fy"] == "FY26-27"
        }
        self.assertEqual(forum["salary"], "133334.0")
        self.assertEqual(forum["cam"], "54280.0")
        self.assertEqual(forum["gas"], "4000.0")
        ads = [
            row for row in rows
            if row["city"] == "Kolkata" and row["store"] == "" and row["line"] == "ads" and row["month"] == "2026-09"
        ]
        self.assertEqual(ads[0]["value"], "1066072.11")
        self.assertFalse(any(row["city"] == "Kolkata" and row["month"] == "2026-10" for row in rows))
        self.assertTrue(any(row["city"] == "NCR" and row["month"] == "2026-09" and row["fy"] == "FY26-27" for row in rows))
        self.assertFalse(any(row["city"] == "NCR" and row["month"] == "2026-10" for row in rows))
        self.assertEqual(self.parser.canonical_line("HO+CK Cost"), "ho_ck_cost")
        self.assertEqual(self.parser.canonical_line("Advertisement Expenses"), "ads")

    def test_city_totals_come_from_summary_and_reconcile(self):
        with (GE / "grand_economics_tidy.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        def value(city, store, line, month="2026-09"):
            return sum(float(r["value"]) for r in rows if r["fy"] == "FY26-27" and r["city"] == city
                       and r["store"] == store and r["line"] == line and r["month"] == month)
        self.assertEqual(round(value("Kolkata", "", "ebitda")), 1501233)
        self.assertEqual(round(value("NCR", "", "ebitda")), -881941)
        self.assertEqual(round(value("NCR", "Kitchen & central", "fnb_cost")), 761680)
        for city in ("Kolkata", "NCR"):
            for month in ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"):
                below = sum(float(r["value"]) for r in rows if r["fy"] == "FY26-27" and r["city"] == city
                            and r["month"] == month and r["line"] == "ebitda" and r["level"] != "city")
                self.assertAlmostEqual(below, value(city, "", "ebitda", month), delta=1)
        self.assertFalse(any(r["store"] == "Event Sales" and r["level"] == "store" for r in rows))

    def test_owner_gate_and_light_first_paint(self):
        anon = self.client.get("/grand-economics")
        self.assertEqual(anon.status_code, 302)
        self.assertIn("login", anon.headers["Location"])

        self._login("asha@dosacoffee.com")
        blocked = self.client.get("/grand-economics")
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("/dashboard", blocked.headers["Location"])
        home = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn("Grand economics", home)
        self.assertNotIn("₹15,01,233", home)
        self.assertNotIn("₹2,21,94,223", home)
        self.assertNotIn("Full figures", home)
        self.assertNotIn("307 of 379", home)
        search = self.client.get("/search.json").get_json()
        self.assertNotIn("/grand-economics", [row["href"] for row in search["results"]])

        self._login(OWNER)
        response = self.client.get("/grand-economics")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Loss-making stores", html)
        self.assertIn("Closing 20 Oct", html)
        self.assertIn("Kolkata is in for Apr–Sep 2026. Later months are not yet in.", html)
        self.assertIn("NCR is in for Apr–Sep 2026. Later months are not yet in.", html)
        self.assertIn("Gurgaon Sector 31", html)
        self.assertIn("Gurgaon Sec - 10", html)
        self.assertIn("Paschim Vihar", html)
        self.assertIn("EBITDA after ads and kitchen", html)
        self.assertIn("₹15,01,233", html)
        self.assertIn("-₹8,81,941", html)
        self.assertNotIn("₹15L", html)
        self.assertNotIn("-₹8.8L", html)
        self.assertNotIn("₹26.7L", html)
        self.assertNotIn("₹8.4L", html)
        self.assertNotIn("To check with Shilajit", html)
        self.assertLess(html.index("Loss-making stores"), html.index("Key numbers"))
        self.assertLess(html.index("Key numbers"), html.index("Booked in Oct"))
        self.assertIn("Kolkata ads, Aug 2026: ₹1,54,279. Booked in Oct.", html)
        self.assertIn("Kolkata ads, Sep 2026: ₹2,21,960. Booked in Oct.", html)
        self.assertNotIn("Kitchen &amp; central", html.split("ge-threats", 1)[1].split("ge-cards", 1)[0])
        self.assertIn('data-src="/grand-economics/stores"', html)
        self.assertNotIn("Forum Mall", html)
        self.assertNotIn("Last year is not in.", html)
        self.assertNotIn('data-theme="dark"', html)
        self.assertNotIn(".csv", html)
        self.assertNotIn(".xlsx", html)
        self.assertNotIn(".json", html)
        self.assertNotIn("parse.py", html)
        body = html.split('<div class="owner-tools">', 1)[1].split("<script>", 1)[0]
        self.assertNotRegex(body, r"\b(blank|null|anchor|fragment)\b")
        bottom = html.split('class="cc-bottom"', 1)[1].split("</nav>", 1)[0]
        drawer = html.split('id="nav-drawer"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("Grand economics", drawer)
        self.assertNotIn("Grand economics", bottom)
        self.assertLess(len(gzip.compress(response.data)), 100_000)
        found = self.client.get("/search.json").get_json()
        self.assertIn("/grand-economics", [row["href"] for row in found["results"]])

        owner_home = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("₹15,01,233", owner_home)
        self.assertIn("-₹8,81,941", owner_home)
        self.assertIn("₹2,21,94,223", owner_home)
        self.assertIn("₹2,17,31,347", owner_home)
        self.assertIn("₹4,39,25,570", owner_home)
        self.assertIn("₹6,19,292", owner_home)
        self.assertIn("6.8%", owner_home)
        self.assertIn("-4.1%", owner_home)
        self.assertIn(">Total<", owner_home)
        self.assertIn("Full figures", owner_home)
        self.assertIn("Company P&amp;L", owner_home)
        self.assertNotIn("Stores before ads and kitchen", owner_home)
        self.assertNotIn("/grand-economics/stores", owner_home)
        self.assertNotIn('data-src="/dashboard/training"', owner_home)

        encoded = self.client.get("/grand-economics", headers={"Accept-Encoding": "gzip"})
        if encoded.headers.get("Content-Encoding") == "gzip":
            self.assertLess(len(encoded.data), 100_000)

    def test_store_list_and_detail_load_on_demand(self):
        self._login(OWNER)
        stores = self.client.get("/grand-economics/stores")
        self.assertEqual(stores.status_code, 200)
        body = stores.get_data(as_text=True)
        self.assertIn("Forum Mall", body)
        self.assertIn("Closing 20 Oct", body)
        self.assertIn("data-list", body)
        self.assertNotIn(".json", body)

        detail = self.client.get("/grand-economics/detail/gurgaon-sector-31-ebitda-2026-09")
        self.assertEqual(detail.status_code, 200)
        panel = detail.get_data(as_text=True)
        self.assertIn('id="gurgaon-sector-31-ebitda-2026-09"', panel)
        self.assertIn("Last year is not in.", panel)
        self.assertNotIn("Ledger detail", panel)
        self.assertIn("<svg", panel)
        self.assertNotIn("chart", panel.lower())

        city = self.client.get("/grand-economics/detail/ncr-city-ebitda-2026-09").get_data(as_text=True)
        self.assertIn("Kitchen food not charged to any store", city)
        self.assertIn("-₹7.6L", city)
        self.assertIn("NCR total", city)
        self.assertIn("-₹8,81,941", city)
        self.assertIn("Stores before ads and kitchen", city)
        self.assertNotIn("₹8.4L", city)
        self.assertNotIn("₹26.7L", city)
        kolkata = self.client.get("/grand-economics/detail/kolkata-city-ebitda-2026-09").get_data(as_text=True)
        self.assertIn("₹15,01,233", kolkata)
        self.assertIn("Kolkata total", kolkata)
        self.assertNotIn("₹26.7L", kolkata)
        self.assertNotIn("₹15L", kolkata)

        missing = self.client.get("/grand-economics/detail/no-such-figure")
        self.assertEqual(missing.status_code, 404)

    def test_ledger_slot_appears_only_when_rows_match(self):
        self._login(OWNER)
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as handle:
            handle.write("date,city,store,ledger,voucher,party,amount\n")
            handle.write("2026-09-04,NCR,Gurgaon Sector 31,Rent,JV,Landlord,1200\n")
            handle.write("2026-09-04,NCR,Other Store,Rent,JV,Landlord,99\n")
            handle.write("2026-09-01,Kolkata,,Ads,JV,Agency,500\n")
            path = handle.name
        os.environ["TALLY_LEDGER_FILE"] = path
        try:
            panel = self.client.get("/grand-economics/detail/gurgaon-sector-31-ebitda-2026-09").get_data(as_text=True)
            self.assertIn("Ledger detail", panel)
            self.assertIn("Landlord", panel)
            self.assertNotIn("Other Store", panel)
            city = self.client.get("/grand-economics/detail/kolkata-ads-2026-09").get_data(as_text=True)
            self.assertIn("Ledger detail", city)
            self.assertIn("Agency", city)
        finally:
            os.environ.pop("TALLY_LEDGER_FILE", None)
            os.unlink(path)


class TrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_training_stays_off_home_and_on_its_own_page(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant", "email": OWNER}
            sess["user_email"] = OWNER
        home = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn("307 of 379 active users (about 81%) did not log in from 30 Sep to 3 Oct.", home)
        self.assertNotIn("718 users. 25 onboarding. 45 pending deactivation.", home)
        self.assertNotIn("9 of these users are outside Kolkata and Delhi.", home)
        self.assertNotIn("Central Kitchen Kolkata", home)
        self.assertNotIn("Course status", home)
        self.assertNotIn('data-src="/dashboard/training"', home)
        self.assertNotIn('id="training"', home)
        drawer = home.split('id="nav-drawer"', 1)[1].split("</nav>", 1)[0]
        bottom = home.split('class="cc-bottom"', 1)[1].split("</nav>", 1)[0]
        self.assertIn("/dashboard/training", drawer)
        self.assertNotIn("/dashboard/training", bottom)
        cities = self.client.get("/dashboard/training")
        self.assertEqual(cities.status_code, 200)
        body = cities.get_data(as_text=True)
        self.assertIn("307 of 379 active users (about 81%) did not log in from 30 Sep to 3 Oct.", body)
        self.assertIn("Central Kitchen Kolkata", body)
        self.assertIn("Connaught Place Delhi", body)
        self.assertIn("Course status", body)
        self.assertIn("266 people", body)
        self.assertIn("293 people", body)
        self.assertNotIn(".csv", body)
        self.assertNotIn(".xlsx", body)

        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Asha", "email": "asha@dosacoffee.com"}
            sess["user_email"] = "asha@dosacoffee.com"
        blocked = self.client.get("/dashboard/training")
        self.assertEqual(blocked.status_code, 302)


if __name__ == "__main__":
    unittest.main()
