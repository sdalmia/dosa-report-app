import csv
import html as html_lib
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
    AUDIT_COLUMNS,
    CALENDAR_COLUMNS,
    FAMEPILOT_COLUMNS,
    KEKA_COLUMNS,
    POSIST_COLUMNS,
    REELO_COLUMNS,
    load_calendar,
    load_posist,
    parse_number,
)
from app.store_health.stores import unique_store_label
from app.store_health.present import (
    business_today,
    format_count,
    format_money,
    format_pct,
)


POSIST_HEADER = ",".join(POSIST_COLUMNS)
CALENDAR_HEADER = ",".join(CALENDAR_COLUMNS)

SAMPLE_POSIST = (
    "Gurgaon Sec-15 (02/0010),2026-10-02,62912.34,67393.99,105,599.17,"
    "+6.54,-4.55,+11.62,59049.24,110,536.81,5,4048,0,live,true,North"
)
GURGAON_SLUG = "gurgaon-sec-15-02-0010"


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
        self.assertEqual(parse_number("0.00"), 0.0)
        self.assertEqual(parse_number("+6.54"), 6.54)
        self.assertEqual(parse_number("152,678.98"), 152678.98)
        self.assertEqual(parse_number("47.66%"), 47.66)
        self.assertEqual(format_money(152678.98, "net"), "₹1,52,678.98")
        self.assertIsNone(parse_number(""))

    def test_shipped_files_keep_tony_headers(self):
        root = Path(__file__).resolve().parents[1] / "data" / "store_health"
        with (root / "posist_daily.csv").open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            self.assertEqual(tuple(next(reader)), POSIST_COLUMNS)
            self.assertEqual(sum(1 for _ in reader), 33)
        with (root / "sales_pred_vs_actual.csv").open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            self.assertEqual(tuple(next(reader)), CALENDAR_COLUMNS)
            self.assertEqual(sum(1 for _ in reader), 33)

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
        self.assertNotIn("Sector 3, Salt Lake", html)
        self.assertNotIn("Gurgaon Sec-15", html)
        self.assertIn("posist_daily.csv is missing.", html)
        self.assertIn("sales_pred_vs_actual.csv is missing.", html)
        self.assertNotIn("File last saved", html)
        self.assertNotIn("Newest date in the file", html)
        self.assertEqual(html.count("<optgroup"), 0)
        self.assertEqual(cell(html, "net"), "")
        self.assertEqual(cell(html, "void_bills"), "")
        self.assertEqual(cell(html, "primary_lead"), "")
        self.assertEqual(cell(html, "headcount"), "")
        self.assertEqual(cell(html, "rating"), "")
        self.assertEqual(cell(html, "review_count"), "")
        self.assertEqual(cell(html, "main_threat"), "")
        self.assertNotIn("62912", html)
        self.assertIn("Choose a store to see its mystery audit.", html)
        self.assertIn("mystery_audit.csv is missing.", html)
        self.assertIn("keka.csv is missing.", html)
        self.assertIn("Headcount is registered employees, not people on shift.", html)
        self.assertIn("not a confirmed single store manager.", html)
        self.assertIn("reelo.csv is missing.", html)
        self.assertIn("famepilot.csv is missing.", html)
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
            f"/store-health/{GURGAON_SLUG}?start=2026-10-01&end=2026-10-03&day=2026-10-02"
        )
        self.assertIn(">Gurgaon Sec-15 (02/0010)</option>", html)
        self.assertNotIn("Dosa Coffee - Gurgaon", html)
        self.assertNotIn("Gurugram Sector-15", html)
        self.assertNotIn("Delhi-NCR", html)
        self.assertIn(">North</li>", html)
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
        self.assertEqual(cell(html, "primary_lead"), "")
        self.assertEqual(cell(html, "headcount"), "")
        self.assertEqual(cell(html, "rating"), "")
        self.assertEqual(cell(html, "main_threat"), "")
        self.assertIn("reelo.csv is missing.", html)
        self.assertIn("famepilot.csv is missing.", html)
        self.assertIn("No ops, CRM, or cost insights are on file for this store.", html)

    def test_other_store_does_not_inherit_the_sample(self):
        self.write("posist_daily.csv", POSIST_HEADER + "\n" + SAMPLE_POSIST + "\n")
        self.write(
            "posist_daily.csv",
            Path(self.data.name, "posist_daily.csv").read_text(encoding="utf-8")
            + '"Sector 3, Salt Lake",2026-10-02,1000,,,,,,,,,,,,,,\n',
        )
        html = self.get("/store-health?store=sector-3-salt-lake&start=2026-10-02&end=2026-10-02&day=2026-10-02")
        self.assertEqual(cell(html, "net"), "₹1,000")
        self.assertEqual(cell(html, "gross"), "")
        self.assertEqual(cell(html, "bills"), "")
        self.assertEqual(cell(html, "void_bills"), "")
        self.assertEqual(cell(html, "net_wow_pct"), "")
        self.assertNotIn("62,912", html)
        self.assertIn(">Sector 3, Salt Lake</option>", html)

    def test_blank_day_for_a_chosen_store(self):
        self.write("posist_daily.csv", POSIST_HEADER + "\n" + SAMPLE_POSIST + "\n")
        html = self.get(f"/store-health/{GURGAON_SLUG}?start=2026-10-01&end=2026-10-01&day=2026-10-01")
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
        self.assertIn(">Dosa Coffee - New Outlet (09/0007)</option>", opened)
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

    def test_empty_files_do_not_invent_a_timestamp(self):
        self.write("posist_daily.csv", POSIST_HEADER + "\n")
        self.write("sales_pred_vs_actual.csv", CALENDAR_HEADER + "\n")
        html = self.get("/store-health")
        self.assertIn("posist_daily.csv is empty.", html)
        self.assertIn("sales_pred_vs_actual.csv is empty.", html)
        self.assertNotIn("File last saved", html)
        self.assertNotIn("Newest date in the file", html)
        self.assertEqual(html.count("<optgroup"), 0)

    def test_calendar_only_name_stays_out_of_the_picker(self):
        self.write("posist_daily.csv", POSIST_HEADER + "\n" + SAMPLE_POSIST + "\n")
        self.write(
            "sales_pred_vs_actual.csv",
            CALENDAR_HEADER + "\nDosa Coffee - Calendar Only (09/0099),2026-10-02,Friday,,,,,,10,,,,,\n",
        )
        html = self.get("/store-health")
        self.assertNotIn("Calendar Only", html)
        self.assertIn(">Gurgaon Sec-15 (02/0010)</option>", html)

    def test_tony_drop_uses_exact_labels_and_last_updated(self):
        root = Path(__file__).resolve().parents[1] / "data" / "store_health"
        os.environ["STORE_HEALTH_DATA_DIR"] = str(root)
        html = self.get("/store-health")
        with (root / "posist_daily.csv").open(encoding="utf-8-sig", newline="") as handle:
            names = [row["store"] for row in csv.DictReader(handle)]
        self.assertEqual(len(set(names)), 33)
        for name in names:
            self.assertIn(f">{html_lib.escape(name)}</option>", html)
        self.assertNotIn(">Salt Lake</option>", html)
        self.assertNotIn(">Gurgaon Sec-15</option>", html)
        self.assertNotIn("Sector 3, Salt Lake", html)
        self.assertIn("Dosa Coffee - Calcutta Swiming Club (0007)", html)
        self.assertIn('data-posist-state="ready"', html)
        self.assertIn('data-calendar-state="ready"', html)
        self.assertEqual(cell(html, "posist_newest_date"), "2 Oct 2026")
        self.assertEqual(cell(html, "calendar_newest_date"), "2 Oct 2026")
        self.assertRegex(cell(html, "posist_saved_at"), r"\d{1,2} [A-Z][a-z]{2} \d{4}, \d{1,2}:\d{2} (am|pm) IST")
        self.assertRegex(cell(html, "calendar_saved_at"), r"\d{1,2} [A-Z][a-z]{2} \d{4}, \d{1,2}:\d{2} (am|pm) IST")
        self.assertRegex(html, r'<option value=""[^>]*selected')
        self.assertEqual(cell(html, "net"), "")

        match = re.search(r'<option value="([^"]+)"[^>]*>Connaught place \(02/0012\)</option>', html)
        self.assertIsNotNone(match)
        page = self.get(f"/store-health/{match.group(1)}?start=2026-10-02&end=2026-10-02&day=2026-10-02")
        self.assertEqual(cell(page, "net"), "₹1,52,678.98")
        self.assertEqual(cell(page, "gross"), "")
        self.assertEqual(cell(page, "bills"), "218")
        self.assertEqual(cell(page, "apb"), "₹700.36")
        self.assertEqual(cell(page, "net_wow_pct"), "+47.66%")
        self.assertEqual(cell(page, "bills_wow_pct"), "+30.54%")
        self.assertEqual(cell(page, "apb_wow_pct"), "+13.11%")
        self.assertEqual(cell(page, "net_last_same_weekday"), "₹1,03,402.35")
        self.assertEqual(cell(page, "bills_last_same_weekday"), "167")
        self.assertEqual(cell(page, "apb_last_same_weekday"), "₹619.18")
        self.assertEqual(cell(page, "unsettled_bills"), "11")
        self.assertEqual(cell(page, "unsettled_amount"), "₹10,018")
        self.assertEqual(cell(page, "void_bills"), "4")
        self.assertEqual(cell(page, "source"), "Live")
        self.assertEqual(cell(page, "provisional"), "Provisional")
        self.assertIn(">North</li>", page)
        self.assertEqual(cell(page, "pred_mid", "2026-10-02"), "")
        self.assertEqual(cell(page, "pred_low", "2026-10-02"), "")
        self.assertEqual(cell(page, "pred_high", "2026-10-02"), "")
        self.assertEqual(cell(page, "variance_vs_mid", "2026-10-02"), "")
        self.assertEqual(cell(page, "variance_pct", "2026-10-02"), "")
        self.assertEqual(cell(page, "tier", "2026-10-02"), "")
        self.assertEqual(cell(page, "actual_net", "2026-10-02"), "₹1,52,678.98")
        self.assertEqual(cell(page, "status", "2026-10-02"), "Actual, provisional end of day")
        self.assertEqual(cell(page, "drivers", "2026-10-02"), "Gandhi Jayanti")
        self.assertEqual(cell(page, "notes", "2026-10-02"), "")
        self.assertEqual(cell(page, "weekday", "2026-10-02"), "Friday")

        gk = re.search(r'<option value="([^"]+)"[^>]*>GK1 Cloud Kitchen \(02/0002\)</option>', page)
        gk_page = self.get(f"/store-health/{gk.group(1)}?day=2026-10-02&start=2026-10-02&end=2026-10-02")
        self.assertEqual(cell(gk_page, "net"), "₹0")
        self.assertEqual(cell(gk_page, "bills"), "0")
        self.assertEqual(cell(gk_page, "apb"), "")
        self.assertEqual(cell(gk_page, "gross"), "")
        self.assertEqual(cell(gk_page, "net_wow_pct"), "")

        events = re.search(
            r'<option value="([^"]+)"[^>]*>Dosa Coffee - Events &amp; Catering</option>',
            page,
        )
        events_page = self.get(f"/store-health/{events.group(1)}?day=2026-10-02&start=2026-10-02&end=2026-10-02")
        self.assertEqual(cell(events_page, "net"), "₹0")
        self.assertEqual(cell(events_page, "gross"), "")
        self.assertEqual(cell(events_page, "apb"), "₹0")
        self.assertEqual(cell(events_page, "net_wow_pct"), "0%")
        self.assertIn(">East</li>", events_page)

    def _option_slug(self, html, label):
        match = re.search(
            rf'<option value="([^"]+)"[^>]*>{re.escape(html_lib.escape(label))}</option>',
            html,
        )
        self.assertIsNotNone(match, label)
        return match.group(1)

    def test_ambiguous_short_label_is_not_applied(self):
        self.write(
            "posist_daily.csv",
            POSIST_HEADER
            + "\n"
            + "Dosa Coffee - Salt Lake (002),2026-10-02,1,,,,,,,,,,,,,,,,East\n"
            + "Dosa Coffee - Salt Lake Sec-1 (0009),2026-10-02,2,,,,,,,,,,,,,,,,East\n"
            + "Gurgaon Sec 10 (02/0014),2026-10-02,3,,,,,,,,,,,,,,,,North\n",
        )
        self.write(
            "keka.csv",
            "posist_store,keka_location,headcount,primary_lead,other_leads,match_status,note\n"
            "Salt Lake,Somewhere,10,Should Not Attach,none,matched,note\n"
            "Gurgaon Sec 10,Gurgaon Sec 10,24,Anil Singh Bisht (ARM),none,matched,note\n",
        )
        index = self.get("/store-health")
        salt = self._option_slug(index, "Dosa Coffee - Salt Lake (002)")
        sec1 = self._option_slug(index, "Dosa Coffee - Salt Lake Sec-1 (0009)")
        sec10 = self._option_slug(index, "Gurgaon Sec 10 (02/0014)")
        salt_page = self.get(f"/store-health/{salt}?day=2026-10-02")
        sec1_page = self.get(f"/store-health/{sec1}?day=2026-10-02")
        sec10_page = self.get(f"/store-health/{sec10}?day=2026-10-02")
        self.assertEqual(cell(salt_page, "primary_lead"), "")
        self.assertEqual(cell(salt_page, "headcount"), "")
        self.assertNotIn("Should Not Attach", salt_page)
        self.assertEqual(cell(sec1_page, "primary_lead"), "")
        self.assertNotIn("Should Not Attach", sec1_page)
        self.assertEqual(cell(sec10_page, "primary_lead"), "Anil Singh Bisht (ARM)")
        self.assertEqual(cell(sec10_page, "headcount"), "24")
        self.assertEqual(cell(sec10_page, "match_status"), "matched")
        self.assertIsNone(unique_store_label("Salt Lake", [
            "Dosa Coffee - Salt Lake (002)",
            "Dosa Coffee - Salt Lake Sec-1 (0009)",
        ]))
        self.assertIn("does not match one Posist store", salt_page)

    def test_keka_and_mystery_audit_drop(self):
        root = Path(__file__).resolve().parents[1] / "data" / "store_health"
        with (root / "keka.csv").open(encoding="utf-8-sig", newline="") as handle:
            keka_rows = list(csv.DictReader(handle))
        with (root / "mystery_audit.csv").open(encoding="utf-8-sig", newline="") as handle:
            audit_rows = list(csv.DictReader(handle))
        self.assertEqual(len(keka_rows), 33)
        self.assertEqual(tuple(keka_rows[0].keys()), KEKA_COLUMNS)
        self.assertEqual(len(audit_rows), 13)
        self.assertEqual(tuple(audit_rows[0].keys()), AUDIT_COLUMNS)
        self.assertEqual(sum(1 for row in audit_rows if row["status"] == "brand aggregate"), 1)
        self.assertEqual(sum(1 for row in keka_rows if row["match_status"] == "no keka match"), 4)

        os.environ["STORE_HEALTH_DATA_DIR"] = str(root)
        index = self.get("/store-health")
        self.assertIn("Headcount is registered employees, not people on shift.", index)
        self.assertIn("not a confirmed single store manager.", index)
        self.assertIn("Brand aggregate", index)
        self.assertEqual(cell(index, "brand_avg"), "88.3%")
        self.assertEqual(cell(index, "brand_weekday"), "not provided in one-pager")
        self.assertEqual(cell(index, "brand_status"), "brand aggregate")
        self.assertEqual(cell(index, "audit_avg"), "")
        self.assertEqual(cell(index, "primary_lead"), "")
        self.assertEqual(cell(index, "rating"), "")
        self.assertIn("Choose a store to see its Famepilot row.", index)
        self.assertIn("Choose a store to see its Reelo row.", index)
        self.assertIn("Past 30 days preset", index)
        self.assertIn("not a verified 30-day range", index)
        self.assertIn("Last 30 Days, 03 Sep 2026 to 03 Oct 2026.", index)
        self.assertRegex(cell(index, "reelo_saved_at"), r"\d{1,2} [A-Z][a-z]{2} \d{4}, \d{1,2}:\d{2} (am|pm) IST")
        self.assertRegex(cell(index, "famepilot_saved_at"), r"\d{1,2} [A-Z][a-z]{2} \d{4}, \d{1,2}:\d{2} (am|pm) IST")
        self.assertNotIn('data-field="reelo_newest_date"', index)
        self.assertNotIn('data-field="famepilot_newest_date"', index)
        self.assertEqual(cell(index, "posist_newest_date"), "2 Oct 2026")
        self.assertEqual(cell(index, "calendar_newest_date"), "2 Oct 2026")

        def open_store(label):
            slug = self._option_slug(index, label)
            return self.get(f"/store-health/{slug}?start=2026-10-02&end=2026-10-02&day=2026-10-02")

        ideal = open_store("Dosa Coffee - Ideal Plaza (01/0001)")
        self.assertEqual(cell(ideal, "headcount"), "102")
        self.assertEqual(cell(ideal, "primary_lead"), "Dipankar Saha (RGM)")
        self.assertEqual(cell(ideal, "keka_location"), "Ideal Plaza")
        self.assertEqual(cell(ideal, "match_status"), "matched")
        self.assertEqual(cell(ideal, "audit_avg"), "not in cycle")
        self.assertEqual(cell(ideal, "audit_status"), "not in cycle")
        self.assertEqual(cell(ideal, "audit_period"), "August 2026")
        self.assertEqual(cell(ideal, "brand_avg"), "88.3%")
        self.assertNotEqual(cell(ideal, "audit_avg"), cell(ideal, "brand_avg"))

        salt = open_store("Dosa Coffee - Salt Lake (002)")
        self.assertEqual(cell(salt, "match_status"), "inferred")
        self.assertEqual(cell(salt, "keka_location"), "Salt Lake Sec 3")
        self.assertEqual(cell(salt, "headcount"), "51")
        self.assertEqual(cell(salt, "primary_lead"), "Sk Jamiruddin (RGM)")

        faridabad = open_store("Sec 15 Faridabad (02/0007)")
        self.assertEqual(cell(faridabad, "match_status"), "inferred")
        self.assertEqual(cell(faridabad, "keka_location"), "Faridabad")
        self.assertEqual(cell(faridabad, "headcount"), "47")
        self.assertEqual(cell(faridabad, "primary_lead"), "Mohammad Javed Idrishi (SM)")

        sec10 = open_store("Gurgaon Sec 10 (02/0014)")
        self.assertEqual(cell(sec10, "match_status"), "matched")
        self.assertEqual(cell(sec10, "keka_location"), "Gurgaon Sec 10")
        self.assertEqual(cell(sec10, "headcount"), "24")
        self.assertEqual(cell(sec10, "primary_lead"), "Anil Singh Bisht (ARM)")

        new_town = open_store("Dosa Coffee - New Town - Cloud Kitchen (01/0013)")
        self.assertEqual(cell(new_town, "keka_location"), "Cloud Kitchen New Town")
        self.assertEqual(cell(new_town, "headcount"), "13")
        self.assertEqual(cell(new_town, "primary_lead"), "Prodip Kumar Ghosh (ARM)")
        self.assertEqual(cell(new_town, "audit_avg"), "not in cycle")
        self.assertEqual(cell(new_town, "audit_note"), "Not in August 2026 audit cycle")

        jasola = open_store("Pacific mall, Jasola (02/0011)")
        self.assertEqual(cell(jasola, "keka_location"), "Jasola Pacific Mall")
        self.assertEqual(cell(jasola, "headcount"), "60")
        self.assertEqual(cell(jasola, "audit_avg"), "84.0%")
        self.assertEqual(cell(jasola, "audit_weekend"), "73.3%")
        self.assertEqual(cell(jasola, "audit_note"), "Weekend crash")

        sec31 = open_store("Sec 31 - Gurgaon (02/0016)")
        self.assertEqual(cell(sec31, "keka_location"), "Gurgaon Sec 31")
        self.assertEqual(cell(sec31, "match_status"), "matched")

        forum = open_store("Dosa Coffee - Forum (0003)")
        self.assertEqual(cell(forum, "audit_avg"), "64.7%")
        self.assertEqual(cell(forum, "audit_weekday"), "40.9% (1-10)")
        self.assertEqual(cell(forum, "audit_weekend"), "recovered (score not provided in one-pager)")
        self.assertEqual(cell(forum, "audit_note"), "Weekday POS outage; weekend recovered")
        self.assertEqual(cell(forum, "audit_status"), "scored")
        self.assertEqual(cell(forum, "other_leads"), "none")

        connaught = open_store("Connaught place (02/0012)")
        self.assertEqual(cell(connaught, "net"), "₹1,52,678.98")
        self.assertEqual(cell(connaught, "headcount"), "73")
        self.assertEqual(cell(connaught, "primary_lead"), "Ashwani Kumar (RGM)")
        self.assertEqual(cell(connaught, "match_status"), "matched")
        self.assertEqual(cell(connaught, "audit_avg"), "79.9%")
        self.assertEqual(cell(connaught, "audit_weekday"), "not provided in one-pager")
        self.assertEqual(cell(connaught, "audit_weekend"), "74.4% (4-10)")
        self.assertEqual(cell(connaught, "audit_period"), "August 2026")
        self.assertEqual(cell(connaught, "brand_avg"), "88.3%")
        self.assertEqual(cell(connaught, "rating"), "4.82")
        self.assertEqual(cell(connaught, "review_count"), "349")
        self.assertEqual(cell(connaught, "redemption_rate"), "12.33%")
        self.assertEqual(cell(connaught, "reelo_match_status"), "matched")

        kalkaji = open_store("Kalkaji (02/0004)")
        self.assertEqual(cell(kalkaji, "audit_avg"), "")
        self.assertEqual(cell(kalkaji, "audit_weekday"), "")
        self.assertEqual(cell(kalkaji, "audit_weekend"), "")
        self.assertEqual(cell(kalkaji, "audit_status"), "")
        self.assertIn("No mystery audit is on file for this store.", kalkaji)
        self.assertEqual(cell(kalkaji, "brand_avg"), "88.3%")
        self.assertEqual(cell(kalkaji, "headcount"), "39")
        self.assertEqual(cell(kalkaji, "primary_lead"), "Deepak Nagar (RGM)")

        for label in (
            "Dosa Coffee - Food Truck - 1 (0008)",
            "Dosa Coffee - Events & Catering",
            "GK1 Cloud Kitchen (02/0002)",
            "Chattarpur (02/0005)",
        ):
            page = open_store(label)
            self.assertEqual(cell(page, "match_status"), "no keka match", label)
            self.assertEqual(cell(page, "primary_lead"), "", label)
            self.assertEqual(cell(page, "headcount"), "", label)
            self.assertEqual(cell(page, "keka_location"), "", label)
            self.assertIn("No Keka match. No manager is on file.", page)
            self.assertNotIn("Dipankar Saha", page)

        self.assertNotIn("does not match one Posist store", index)

    def test_reelo_and_famepilot_drop(self):
        root = Path(__file__).resolve().parents[1] / "data" / "store_health"
        with (root / "reelo.csv").open(encoding="utf-8-sig", newline="") as handle:
            reelo_rows = list(csv.DictReader(handle))
        with (root / "famepilot.csv").open(encoding="utf-8-sig", newline="") as handle:
            fame_rows = list(csv.DictReader(handle))
        self.assertEqual(len(reelo_rows), 33)
        self.assertEqual(tuple(reelo_rows[0].keys()), REELO_COLUMNS)
        self.assertEqual(len(fame_rows), 33)
        self.assertEqual(tuple(fame_rows[0].keys()), FAMEPILOT_COLUMNS)
        self.assertEqual(sum(1 for row in reelo_rows if row["match_status"] == "not in Reelo"), 8)
        self.assertEqual(sum(1 for row in reelo_rows if row["match_status"] == "inferred"), 1)
        self.assertEqual(sum(1 for row in reelo_rows if row["redemption_rate"] != "not in Reelo"), 25)
        self.assertEqual(sum(1 for row in fame_rows if not (row["famepilot_location"] or "").strip()), 8)

        os.environ["STORE_HEALTH_DATA_DIR"] = str(root)
        index = self.get("/store-health")

        def open_store(label):
            slug = self._option_slug(index, label)
            return self.get(f"/store-health/{slug}?day=2026-10-02")

        ideal = open_store("Dosa Coffee - Ideal Plaza (01/0001)")
        self.assertEqual(cell(ideal, "rating"), "4.80")
        self.assertEqual(cell(ideal, "review_count"), "35")
        self.assertEqual(cell(ideal, "main_threat"), "")
        self.assertEqual(cell(ideal, "private_rating"), "3.58")
        self.assertEqual(cell(ideal, "private_review_count"), "132")
        self.assertEqual(cell(ideal, "overall_reviews"), "167")
        self.assertEqual(cell(ideal, "reelo_store"), "Dosa Coffee Ideal Plaza")
        self.assertEqual(cell(ideal, "reelo_match_status"), "matched")
        self.assertEqual(cell(ideal, "times_redeemed"), "558")
        self.assertEqual(cell(ideal, "redemption_rate"), "45.28%")
        self.assertEqual(cell(ideal, "redemption_revenue"), "₹3,75,778")
        self.assertEqual(cell(ideal, "phone_capture"), "95.38%")
        self.assertEqual(cell(ideal, "visits"), "7808")
        self.assertEqual(cell(ideal, "active_customers"), "4288")
        self.assertIn("Phone capture is valid visits / (valid + blocked) x 100.", ideal)
        self.assertIn("Last 30 Days, 03 Sep 2026 to 03 Oct 2026.", ideal)

        salt = open_store("Dosa Coffee - Salt Lake (002)")
        self.assertEqual(cell(salt, "reelo_match_status"), "inferred")
        self.assertEqual(cell(salt, "reelo_store"), "Dosa Coffee Saltlake JC21")
        self.assertIn("Salt Lake Sec 3", cell(salt, "reelo_note"))
        self.assertIn("Not a confirmed address match.", cell(salt, "reelo_note"))
        self.assertEqual(cell(salt, "keka_location"), "Salt Lake Sec 3")
        self.assertEqual(cell(salt, "famepilot_location"), "01/0002 / Dosa Coffee- Saltlake Sec 3")
        self.assertIn("by code 0002", cell(salt, "famepilot_note"))
        self.assertEqual(cell(salt, "rating"), "4.51")
        self.assertEqual(cell(salt, "review_count"), "37")
        self.assertEqual(cell(salt, "main_threat"), "Missing Item")

        new_town = open_store("Dosa Coffee - New Town - Cloud Kitchen (01/0013)")
        self.assertIn("not in Reelo", new_town)
        self.assertEqual(cell(new_town, "reelo_match_status"), "not in Reelo")
        self.assertEqual(cell(new_town, "redemption_rate"), "")
        self.assertEqual(cell(new_town, "redemption_revenue"), "")
        self.assertEqual(cell(new_town, "times_redeemed"), "")
        self.assertEqual(cell(new_town, "phone_capture"), "")
        self.assertEqual(cell(new_town, "visits"), "")
        self.assertEqual(cell(new_town, "active_customers"), "")
        self.assertEqual(cell(new_town, "rating"), "")
        self.assertEqual(cell(new_town, "review_count"), "0")
        self.assertEqual(cell(new_town, "private_rating"), "3.80")
        self.assertEqual(cell(new_town, "private_review_count"), "59")
        self.assertEqual(cell(new_town, "overall_reviews"), "59")
        self.assertEqual(cell(new_town, "main_threat"), "Missing Item")
        self.assertNotIn("no reviews in window", new_town.lower())

        rohini = open_store("Rohini Sec-7 (02/0008)")
        self.assertEqual(cell(rohini, "main_threat"), "tie: Missing Item, Quality Issue")
        paschim = open_store("Paschim Vihar (02/0003)")
        self.assertEqual(cell(paschim, "main_threat"), "tie: Missing Item, Wrong Item")

        forum = open_store("Dosa Coffee - Forum (0003)")
        self.assertEqual(cell(forum, "reelo_match_status"), "not in Reelo")
        self.assertEqual(cell(forum, "rating"), "5.00")
        self.assertEqual(cell(forum, "review_count"), "2")
        self.assertEqual(cell(forum, "main_threat"), "not shown")
        self.assertEqual(cell(forum, "private_rating"), "")
        self.assertEqual(cell(forum, "private_review_count"), "0")
        self.assertEqual(cell(forum, "overall_reviews"), "2")

        for label in (
            "Dosa Coffee - Manisquare (0004)",
            "Dosa Coffee - Forum (0003)",
            "Dosa Coffee - New Town - Cloud Kitchen (01/0013)",
            "Dosa Coffee - Calcutta Swiming Club (0007)",
            "Dosa Coffee - Food Truck - 1 (0008)",
            "Dosa Coffee - Events & Catering",
            "GK1 Cloud Kitchen (02/0002)",
            "Chattarpur (02/0005)",
        ):
            page = open_store(label)
            self.assertEqual(cell(page, "reelo_match_status"), "not in Reelo", label)
            self.assertIn(">not in Reelo</p>", page.replace("\n", ""), label)
            self.assertEqual(cell(page, "redemption_revenue"), "", label)
            self.assertNotIn("₹0", cell(page, "redemption_revenue") or "x")

        for label in (
            "Shalimar Bagh (02/0015)",
            "Sec 31 - Gurgaon (02/0016)",
            "GK1 Cloud Kitchen (02/0002)",
            "Chattarpur (02/0005)",
            "Dosa Coffee - Quest Mall (01/0016)",
            "Dosa Coffee - Calcutta Swiming Club (0007)",
            "Dosa Coffee - Food Truck - 1 (0008)",
            "Dosa Coffee - Events & Catering",
        ):
            page = open_store(label)
            self.assertEqual(cell(page, "rating"), "", label)
            self.assertEqual(cell(page, "review_count"), "", label)
            self.assertEqual(cell(page, "famepilot_location"), "", label)
            self.assertIn("No Famepilot location.", page)

        quest = open_store("Dosa Coffee - Quest Mall (01/0016)")
        self.assertEqual(cell(quest, "rating"), "")
        self.assertEqual(cell(quest, "reelo_match_status"), "matched")
        self.assertEqual(cell(quest, "redemption_rate"), "10.38%")
        self.assertEqual(cell(quest, "times_redeemed"), "86")
        self.assertIn("26 Sep 26 - 02 Oct 26 (7 days)", quest)
        self.assertIn("not a verified 30-day range", quest)

    def test_committed_headers_round_trip_with_csv(self):
        root = Path(__file__).resolve().parents[1] / "data" / "store_health"
        with (root / "posist_daily.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(tuple(next(csv.reader(handle))), POSIST_COLUMNS)
        with (root / "sales_pred_vs_actual.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(tuple(next(csv.reader(handle))), CALENDAR_COLUMNS)


if __name__ == "__main__":
    unittest.main()
