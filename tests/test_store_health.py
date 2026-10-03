import csv
import os
import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB.name
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from app.store_health.contract import (
    CALENDAR_COLUMNS,
    POSIST_COLUMNS,
    load_calendar,
    load_posist,
    parse_number,
)
from app.store_health.present import (
    business_today,
    format_count,
    format_money,
    format_pct,
)
from app.store_health.stores import CATALOGUE


POSIST_HEADER = ",".join(POSIST_COLUMNS)
CALENDAR_HEADER = ",".join(CALENDAR_COLUMNS)

SAMPLE_POSIST = (
    "Gurgaon Sec-15 (02/0010),2026-10-02,62912.34,67393.99,105,599.17,"
    "+6.54,-4.55,+11.62,59049.24,110,536.81,5,4048,0,live,true"
)


def cell(html, field, day=None):
    if day:
        pattern = rf'data-field="{field}" data-date="{day}">([^<]*)</'
    else:
        pattern = rf'data-field="{field}">([^<]*)</'
    match = re.search(pattern, html)
    if not match:
        raise AssertionError(f"missing field {field} {day or ''}")
    return match.group(1).strip()


class StoreHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        os.environ["STORE_HEALTH_DATA_DIR"] = self.data.name
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Asha Rao", "email": "asha@dosacoffee.com"}

    def tearDown(self):
        os.environ.pop("STORE_HEALTH_DATA_DIR", None)
        self.data.cleanup()

    def get(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.data[:500])
        return response.get_data(as_text=True)

    def write(self, name, text):
        Path(self.data.name, name).write_text(text, encoding="utf-8")

    def test_formats_rupees_percents_and_real_zero(self):
        self.assertEqual(format_money(62912.34, "net"), "₹62,912.34")
        self.assertEqual(format_money(67393.99, "gross"), "₹67,393.99")
        self.assertEqual(format_money(4048, "unsettled_amount"), "₹4,048")
        self.assertEqual(format_money(100000, "net"), "₹1,00,000")
        self.assertEqual(format_money(1.5, "net_L"), "1.5 L")
        self.assertEqual(format_money(None, "net"), "")
        self.assertEqual(format_money(0, "actual_net"), "₹0")
        self.assertEqual(format_count(0), "0")
        self.assertEqual(format_count(None), "")
        self.assertEqual(format_pct(6.54), "+6.54%")
        self.assertEqual(format_pct(-4.55), "-4.55%")
        self.assertEqual(format_pct(11.62), "+11.62%")
        self.assertIsNone(parse_number(""))
        self.assertIsNone(parse_number("abc"))
        self.assertEqual(parse_number("0"), 0.0)
        self.assertEqual(parse_number("+6.54"), 6.54)

    def test_catalogue_has_no_invented_deployment_codes(self):
        self.assertEqual(len(CATALOGUE), 28)
        coded = [store for store in CATALOGUE if store.deployment_code]
        self.assertEqual([store.id for store in coded], ["ncr-gurugram-sector-15"])
        gurgaon = coded[0]
        self.assertEqual(gurgaon.posist_deployment_name, "Dosa Coffee - Gurgaon Sec-15 (02/0010)")
        self.assertEqual(gurgaon.deployment_code, "02/0010")
        self.assertEqual(gurgaon.region, "North")
        self.assertEqual(gurgaon.format, "Delhi-NCR")
        self.assertIn("Gurgaon Sec-15 (02/0010)", gurgaon.match_keys())
        regions = {store.region for store in CATALOGUE}
        formats = {store.format for store in CATALOGUE}
        self.assertEqual(regions, {"East", "North"})
        self.assertEqual(formats, {"Kolkata", "Delhi-NCR"})

    def test_shipped_files_match_the_contract_and_have_no_rows(self):
        root = Path(__file__).resolve().parents[1] / "data" / "store_health"
        posist = (root / "posist_daily.csv").read_text(encoding="utf-8").strip()
        calendar = (root / "sales_pred_vs_actual.csv").read_text(encoding="utf-8").strip()
        self.assertEqual(posist, POSIST_HEADER)
        self.assertEqual(calendar, CALENDAR_HEADER)
        self.assertNotIn("62912", posist)

    def test_login_required(self):
        anon = self.app.test_client()
        response = anon.get("/store-health")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.headers["Location"])

    def test_index_has_seven_boxes_and_no_store_or_figures(self):
        html = self.get("/store-health")
        order = [
            'id="posist"',
            'id="mystery-audit"',
            'id="staff"',
            'id="famepilot"',
            'id="reelo"',
            'id="insights"',
            'id="sales-calendar"',
        ]
        positions = [html.index(marker) for marker in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Choose a store", html)
        self.assertIn(">Choose a store</option>", html)
        self.assertRegex(html, r'<option value=""[^>]*selected')
        self.assertLess(html.index("Sector 3, Salt Lake"), html.index("Gurgaon Sec-15"))
        self.assertEqual(cell(html, "net"), "")
        self.assertEqual(cell(html, "void_bills"), "")
        self.assertEqual(cell(html, "store_manager"), "")
        self.assertEqual(cell(html, "rating"), "")
        self.assertEqual(cell(html, "complaints"), "")
        self.assertEqual(cell(html, "threats"), "")
        self.assertNotIn("62912", html)
        self.assertIn("No mystery audit is on file for this store.", html)
        self.assertIn("They will come from Keka.", html)
        self.assertIn("No Reelo data is on file for this store.", html)
        self.assertIn("Holiday calendar", html)
        self.assertIn("Local current affairs", html)
        self.assertIn("Weather", html)
        today = business_today()
        start = today - timedelta(days=13)
        self.assertIn(start.isoformat(), html)
        self.assertIn(today.isoformat(), html)
        self.assertEqual(len(re.findall(r'data-field="actual_net" data-date="', html)), 14)
        self.assertIn("Choose a store to see predicted and actual Net.", html)

    def test_sample_row_renders_and_missing_calendar_cells_stay_blank(self):
        self.write("posist_daily.csv", POSIST_HEADER + "\n" + SAMPLE_POSIST + "\n")
        self.write(
            "sales_pred_vs_actual.csv",
            CALENDAR_HEADER
            + "\n"
            + "Gurgaon Sec-15 (02/0010),2026-10-02,Fri,A,,,70000,62912.34,,,,,\n"
            + "Gurgaon Sec-15 (02/0010),2026-10-03,Sat,B,100,200,150,0,-150,-100,actual,,closed till 9\n"
            + ",2026-10-02,Fri,A,1,2,3,4,1,1,pending,network driver,network note\n",
        )
        html = self.get(
            "/store-health/ncr-gurugram-sector-15?start=2026-10-01&end=2026-10-03&day=2026-10-02"
        )
        self.assertIn("Dosa Coffee - Gurgaon Sec-15 (02/0010)", html)
        self.assertIn("Code 02/0010", html)
        self.assertIn(">North</li>", html)
        self.assertIn(">Delhi-NCR</li>", html)
        self.assertEqual(cell(html, "net"), "₹62,912.34")
        self.assertEqual(cell(html, "gross"), "₹67,393.99")
        self.assertEqual(cell(html, "bills"), "105")
        self.assertEqual(cell(html, "apb"), "₹599.17")
        self.assertEqual(cell(html, "net_wow_pct"), "+6.54%")
        self.assertEqual(cell(html, "bills_wow_pct"), "-4.55%")
        self.assertEqual(cell(html, "apb_wow_pct"), "+11.62%")
        self.assertEqual(cell(html, "net_last_same_weekday"), "₹59,049.24")
        self.assertEqual(cell(html, "bills_last_same_weekday"), "110")
        self.assertEqual(cell(html, "apb_last_same_weekday"), "₹536.81")
        self.assertEqual(cell(html, "unsettled_bills"), "5")
        self.assertEqual(cell(html, "unsettled_amount"), "₹4,048")
        self.assertEqual(cell(html, "void_bills"), "0")
        self.assertEqual(cell(html, "source"), "Live")
        self.assertEqual(cell(html, "provisional"), "Provisional")
        self.assertNotIn("7,087", html)
        self.assertEqual(cell(html, "pred_low", "2026-10-02"), "")
        self.assertEqual(cell(html, "pred_high", "2026-10-02"), "")
        self.assertEqual(cell(html, "pred_mid", "2026-10-02"), "₹70,000")
        self.assertEqual(cell(html, "actual_net", "2026-10-02"), "₹62,912.34")
        self.assertEqual(cell(html, "variance_vs_mid", "2026-10-02"), "")
        self.assertEqual(cell(html, "variance_pct", "2026-10-02"), "")
        self.assertEqual(cell(html, "status", "2026-10-02"), "")
        self.assertEqual(cell(html, "weekday", "2026-10-01"), "")
        self.assertEqual(cell(html, "pred_mid", "2026-10-01"), "")
        self.assertEqual(cell(html, "actual_net", "2026-10-01"), "")
        self.assertEqual(cell(html, "actual_net", "2026-10-03"), "₹0")
        self.assertEqual(cell(html, "variance_vs_mid", "2026-10-03"), "-₹150")
        self.assertEqual(cell(html, "variance_pct", "2026-10-03"), "-100%")
        self.assertEqual(cell(html, "status", "2026-10-03"), "Actual")
        self.assertEqual(cell(html, "notes", "2026-10-03"), "closed till 9")
        self.assertNotIn("network driver", html)
        self.assertNotIn("No daily Posist row", html)
        self.assertIn("No mystery audit is on file for this store.", html)
        self.assertEqual(cell(html, "store_manager"), "")
        self.assertEqual(cell(html, "staff_strength"), "")
        self.assertEqual(cell(html, "rating"), "")
        self.assertEqual(cell(html, "threats"), "")
        self.assertIn("No Reelo data is on file for this store.", html)
        self.assertIn("No ops, CRM, or cost insights are on file for this store.", html)

    def test_other_store_does_not_inherit_the_sample(self):
        self.write("posist_daily.csv", POSIST_HEADER + "\n" + SAMPLE_POSIST + "\n")
        self.write(
            "posist_daily.csv",
            Path(self.data.name, "posist_daily.csv").read_text(encoding="utf-8")
            + '"Sector 3, Salt Lake",2026-10-02,1000,,,,,,,,,,,,,,\n',
        )
        html = self.get("/store-health?store=kolkata-sector-3-salt-lake&start=2026-10-02&end=2026-10-02&day=2026-10-02")
        self.assertEqual(cell(html, "net"), "₹1,000")
        self.assertEqual(cell(html, "gross"), "")
        self.assertEqual(cell(html, "bills"), "")
        self.assertEqual(cell(html, "void_bills"), "")
        self.assertEqual(cell(html, "net_wow_pct"), "")
        self.assertNotIn("62,912", html)
        self.assertIn(">East</li>", html)
        self.assertIn(">Kolkata</li>", html)

    def test_blank_day_for_a_chosen_store(self):
        self.write("posist_daily.csv", POSIST_HEADER + "\n" + SAMPLE_POSIST + "\n")
        html = self.get("/store-health?store=ncr-kalkaji&start=2026-10-02&end=2026-10-02&day=2026-10-02")
        self.assertIn("No daily Posist row for this store on this date.", html)
        self.assertEqual(cell(html, "net"), "")
        self.assertEqual(cell(html, "bills"), "")
        self.assertEqual(cell(html, "void_bills"), "")
        self.assertIn("No predicted or actual Net in this range.", html)
        self.assertNotIn("62912", html)

    def test_date_range_and_feed_only_store(self):
        self.write(
            "posist_daily.csv",
            POSIST_HEADER + "\nDosa Coffee - New Outlet (09/0007),2026-10-02,10,,,,,,,,,,,,,,,\n",
        )
        self.write("sales_pred_vs_actual.csv", CALENDAR_HEADER + "\n")
        html = self.get("/store-health?start=2026-10-05&end=2026-10-01")
        self.assertIn("The end date is before the start date.", html)
        self.assertNotIn('data-date="2026-10-05"', html)
        listed = self.get("/store-health")
        self.assertIn("Dosa Coffee - New Outlet (09/0007)", listed)
        opened = self.get("/store-health?store=dosa-coffee-new-outlet-09-0007&day=2026-10-02&start=2026-10-02&end=2026-10-02")
        self.assertEqual(cell(opened, "net"), "₹10")
        self.assertIn("Code 09/0007", opened)
        self.assertNotIn(">North</li>", opened)
        self.assertNotIn(">East</li>", opened)

    def test_last_row_wins_and_bad_number_stays_blank(self):
        text = (
            POSIST_HEADER
            + "\nKalikapur,2026-10-02,10,20,1,2,3,4,5,6,7,8,9,10,1,live,true\n"
            + "Kalikapur,2026-10-02,abc,20,1,2,3,4,5,6,7,8,9,10,1,live,true\n"
        )
        self.write("posist_daily.csv", text)
        rows, warnings = load_posist(self.data.name)
        row = rows[("Kalikapur", date(2026, 10, 2))]
        self.assertIsNone(row["net"])
        self.assertEqual(row["gross"], 20)
        self.assertEqual(row["void_bills"], 1)
        self.assertTrue(any("not a number" in warning for warning in warnings))
        self.assertTrue(any("more than one row" in warning for warning in warnings))

    def test_network_file_without_store_is_not_applied(self):
        self.write(
            "sales_pred_vs_actual.csv",
            "date,weekday,tier,pred_low,pred_high,pred_mid,actual_net,variance_vs_mid,variance_pct,status,drivers,notes\n"
            "2026-10-02,Fri,A,1,2,3,4,5,6,pending,network only,note\n",
        )
        rows, warnings = load_calendar(self.data.name)
        self.assertEqual(rows, {})
        self.assertTrue(any("no store column" in warning for warning in warnings))

    def test_existing_tools_still_open(self):
        html = self.get("/dashboard")
        self.assertIn("Store Health", html)
        self.assertIn("Zomato Settlement Uploader", html)
        self.assertIn("Ingredient Price Tracker", html)
        self.assertIn("Location Finder", html)
        self.assertIn("/upload", html)
        self.assertIn("/ingredient-tracker/", html)
        self.assertIn("/location-finder", html)
        self.assertIn("/store-health", html)
        self.get("/upload")
        self.get("/ingredient-tracker/")
        self.get("/location-finder")

    def test_committed_headers_round_trip_with_csv(self):
        root = Path(__file__).resolve().parents[1] / "data" / "store_health"
        with (root / "posist_daily.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(tuple(next(csv.reader(handle))), POSIST_COLUMNS)
        with (root / "sales_pred_vs_actual.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(tuple(next(csv.reader(handle))), CALENDAR_COLUMNS)


if __name__ == "__main__":
    unittest.main()
