import csv
import os
import tempfile
import unittest
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB.name
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from app.store_health.stores import store_from_label, unique_store_label
from app.gaps import filter_gaps, load_gap_board
from app.owner_tools.metrics import build_scorecard
from app.store_health.contract import load_feeds
from app.store_master import (
    COLUMNS,
    NOT_ON_REELO,
    UNKNOWN_STATUS,
    allows_growth,
    find_store,
    get_index,
    human_notes,
    is_trading,
    load_rows,
    store_gaps,
)

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data" / "store_master.csv"
OWNER = "siddhant@dalgreenfoods.com"
OTHER = "siddhant@dosacoffee.com"
FORMATS = {"dine-in", "food court", "kiosk", "cloud kitchen", "truck", "events", ""}


def _by_code(rows, code):
    hits = [row for row in rows if row["posist_code"] == code]
    if len(hits) != 1:
        raise AssertionError(f"{code} matched {len(hits)}")
    return hits[0]


class StoreMasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows(MASTER)
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def _session(self, email):
        with self.client.session_transaction() as sess:
            if email:
                sess["user"] = {"name": "Siddhant Dalmia", "email": email}
            else:
                sess.clear()

    def test_columns_and_one_row_per_outlet(self):
        with MASTER.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(tuple(reader.fieldnames), COLUMNS)
        self.assertEqual(len(self.rows), 36)
        self.assertEqual(len({row["store_id"] for row in self.rows}), 36)
        self.assertEqual(sum(1 for row in self.rows if row["status"] == "trading"), 29)
        for row in self.rows:
            self.assertEqual(row["store_id"], store_from_label(row["posist_name"]).id)
            self.assertIn(row["format"], FORMATS)
            self.assertEqual(row["swiggy_id"], "")
            self.assertEqual(row["zomato_id"], "")
            self.assertNotIn(".csv", row["notes"])
            self.assertNotIn("Fresh Aisle", row["posist_name"])
            self.assertNotIn("Fresh Aisle", row["gbp_name"])

    def test_codes_and_names(self):
        james = _by_code(self.rows, "01/0011")
        self.assertEqual(james["posist_name"], "Dosa Coffee - James long Sarani (01/0011)")
        salt = _by_code(self.rows, "01/0002")
        self.assertEqual(salt["posist_name"], "Dosa Coffee - Salt Lake (002)")
        gk1 = _by_code(self.rows, "02/0002")
        self.assertEqual(gk1["posist_name"], "GK1 Cloud Kitchen (02/0002)")
        self.assertEqual(gk1["format"], "cloud kitchen")
        events = next(row for row in self.rows if "Catering" in row["posist_name"])
        self.assertEqual(events["posist_name"], "Dosa Coffee - Events & Catering")
        self.assertEqual(events["format"], "events")
        self.assertEqual(events["posist_code"], "")
        truck = _by_code(self.rows, "01/0008")
        self.assertEqual(truck["format"], "truck")
        forum = _by_code(self.rows, "01/0003")
        self.assertEqual(forum["format"], "food court")
        fra = _by_code(self.rows, "02/0017")
        self.assertEqual(fra["display_name"], "FRA")
        self.assertEqual(fra["status"], UNKNOWN_STATUS)
        demo = find_store("DEMO OUTLET")
        self.assertEqual(demo["status"], "test")
        closed = find_store("Salt Lake Sec-3 (Not In Use)")
        self.assertEqual(closed["status"], "closed")
        for label in ("GK1 Cloud Kitchen (02/0002)", "Chattarpur (02/0005)"):
            self.assertEqual(find_store(label)["status"], "closed", label)
            self.assertFalse(is_trading(label), label)
            self.assertFalse(allows_growth(label), label)
            self.assertEqual(store_gaps(find_store(label)), [])
        faridabad = find_store("Sec 15 Faridabad (02/0007)")
        self.assertEqual(faridabad["status"], "closing 31 Oct")
        self.assertTrue(is_trading(faridabad["posist_name"]))
        self.assertFalse(allows_growth(faridabad["posist_name"]))
        for label in (
            "Dosa Coffee - Events & Catering",
            "Dosa Coffee, FRA (02/0017)",
        ):
            self.assertEqual(find_store(label)["status"], UNKNOWN_STATUS, label)
            self.assertFalse(is_trading(label), label)

    def test_lookup_uses_the_master(self):
        self.assertEqual(find_store("CP")["posist_name"], "Connaught place (02/0012)")
        self.assertEqual(find_store("Jasola")["posist_name"], "Pacific mall, Jasola (02/0011)")
        self.assertEqual(
            find_store("New Town CK")["posist_name"],
            "Dosa Coffee - New Town - Cloud Kitchen (01/0013)",
        )
        self.assertEqual(find_store("Pacific Jasola")["posist_name"], "Pacific mall, Jasola (02/0011)")
        self.assertEqual(find_store("Gurgaon Sec 10")["posist_name"], "Gurgaon Sec 10 (02/0014)")
        self.assertEqual(find_store("01/0011")["display_name"], "James long Sarani")
        self.assertIsNone(find_store("Salt Lake"))
        self.assertIsNone(find_store("Dosa Coffee"))
        self.assertIsNone(find_store("Fresh Aisle"))
        self.assertTrue(is_trading("Gurgaon Sec 10"))
        self.assertTrue(is_trading("Alpha"))
        self.assertFalse(is_trading("DEMO OUTLET"))
        self.assertIsNone(
            unique_store_label(
                "Salt Lake",
                ["Dosa Coffee - Salt Lake (002)", "Dosa Coffee - Salt Lake Sec-1 (0009)"],
            )
        )

    def test_gaps_name_the_missing_system(self):
        def kinds(label):
            row = find_store(label)
            return {gap["kind"]: gap for gap in store_gaps(row)}

        cp = kinds("CP")
        self.assertIn("duplicate", cp)
        self.assertNotIn("google", cp)
        self.assertNotIn("name", cp)
        self.assertEqual(cp["duplicate"]["owner"], "Sanjoy / Subhra")
        self.assertEqual(cp["duplicate"]["status"], "Needs a cleanup")

        faridabad = kinds("Sec 15 Faridabad (02/0007)")
        self.assertIn("unverified", faridabad)
        self.assertEqual(faridabad["unverified"]["status"], "Needs verification")

        quest = kinds("Quest")
        self.assertIn("google", quest)
        self.assertIn("name", quest)
        self.assertNotIn("reelo", quest)
        self.assertEqual(quest["google"]["status"], "Needs a listing")

        forum = kinds("Forum")
        self.assertNotIn("reelo", forum)
        self.assertNotIn("google", forum)
        self.assertEqual(find_store("Forum")["reelo_status"], NOT_ON_REELO)
        self.assertEqual(find_store("Quest")["reelo_status"], "")

        truck = kinds("Dosa Coffee - Food Truck - 1 (0008)")
        self.assertIn("google", truck)
        self.assertNotIn("reelo", truck)
        self.assertNotIn("name", truck)

        for row in self.rows:
            if row["status"] == "closed":
                self.assertEqual(store_gaps(row), [])
                continue
            kinds_for_row = {gap["kind"] for gap in store_gaps(row)}
            self.assertNotIn("reelo", kinds_for_row)
            delivery = {gap["kind"]: gap for gap in store_gaps(row)}["delivery"]
            self.assertEqual(delivery["status"], "Needs the ids")
            self.assertEqual(delivery["owner"], "Sanjoy / Subhra")
            self.assertNotIn("Known names", human_notes(row["notes"]))
            if row["reelo_name"]:
                self.assertEqual(row["reelo_status"], "")
            else:
                self.assertEqual(row["reelo_status"], NOT_ON_REELO)

    def test_data_gaps_is_owner_only(self):
        self._session(None)
        anon = self.client.get("/data-gaps")
        self.assertEqual(anon.status_code, 302)
        self.assertIn("login", anon.headers["Location"])

        self._session(OTHER)
        blocked = self.client.get("/data-gaps")
        self.assertEqual(blocked.status_code, 302)
        self.assertNotIn("data-gaps", blocked.headers["Location"])
        brief = self.client.get("/brief")
        self.assertEqual(brief.status_code, 200)
        self.assertNotIn("Data gaps", brief.get_data(as_text=True))

        self._session(OWNER)
        page = self.client.get("/data-gaps?cc_store=&cc_city=&cc_range=")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Data gaps", html)
        self.assertEqual(html.count("<header"), 1)
        self.assertIn('name="theme-color" content="#f7f6f3"', html)
        self.assertIn("Sanjoy / Subhra", html)
        self.assertIn("Needs a listing", html)
        self.assertIn("Duplicate listing", html)
        self.assertIn('data-field="open"', html)
        self.assertIn('data-field="waiting"', html)
        self.assertIn('data-field="fixed"', html)
        self.assertNotIn(".csv", html)
        self.assertNotIn("Known names", html)
        self.assertNotIn("Not on Reelo", html)
        self.assertNotIn(NOT_ON_REELO, html)
        self.assertIn("Store Master", html)
        self.assertIn('name="cc_store"', html)
        self.assertIn('class="cc-bottom"', html)
        bottom = html.split('class="cc-bottom"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn("Data gaps", bottom)
        self.assertNotIn("Store Master", bottom)
        self.assertEqual(bottom.count("<a "), 5)
        section = html.split('data-owner="Sanjoy / Subhra"', 1)[1]
        self.assertLess(section.find('data-threat="1"'), section.find("No Swiggy or Zomato id"))

    def test_only_trading_stores_are_ranked(self):
        feeds = load_feeds(ROOT / "data" / "store_health")
        payload = build_scorecard(feeds, {"rows": [], "present": False, "empty": "No wastage figure yet"}, "")
        labels = [store["label"] for store in payload["stores"]]
        self.assertIn("Dosa Coffee - Ideal Plaza (01/0001)", labels)
        for banned in ("GK1", "DEMO", "FRA", "Events", "Not In Use", "Chattarpur"):
            self.assertFalse(any(banned in label for label in labels), banned)
        self.assertTrue(all(is_trading(store["label"]) for store in payload["stores"]))
        self.assertTrue(all(store["rank"] is None or is_trading(store["label"]) for store in payload["stores"]))

    def test_bot_gaps_group_by_owner_and_hide_accounts(self):
        folder = tempfile.TemporaryDirectory()
        header = "gap_id,area,store,title,why_it_matters,fix,owner,status,due,as_of,source\n"
        Path(folder.name, "tony.csv").write_text(
            header
            + "t1,reputation,Forum,Review threat,A public complaint,Reply,Sanjoy / Subhra,open,2026-10-20,2026-10-09,Famepilot\n"
            + "t2,sales,Forum,Soft week,Bills slipped,Check the roster,Sanjoy / Subhra,waiting,,,Posist Insights\n"
            + "bad,sales,Forum,,missing title,x,Sanjoy,open,,,\n",
            encoding="utf-8",
        )
        Path(folder.name, "accountant.csv").write_text(
            header + "a1,accounts,,Salary run,Not in Tally,Book it,Shilajit,open,2026-10-12,2026-10-09,Bank statement\n",
            encoding="utf-8",
        )
        Path(folder.name, "hr.csv").write_text(
            header + "h1,people,Gurgaon Sec 10,Exits,Four people left,Call the manager,HR,fixed,,,Keka report\n",
            encoding="utf-8",
        )
        Path(folder.name, "alfred.csv").write_text(header, encoding="utf-8")
        hidden = load_gap_board([], directory=folder.name, email=OTHER)
        titles = [gap["title"] for gap in hidden["gaps"]]
        self.assertIn("Review threat", titles)
        self.assertIn("Soft week", titles)
        self.assertNotIn("Salary run", titles)
        self.assertNotIn("Exits", titles)
        self.assertEqual(hidden["counts"], {"open": 1, "waiting": 1, "fixed": 0})
        sanjoy = next(group for group in hidden["groups"] if group["owner"] == "Sanjoy / Subhra")
        self.assertEqual(sanjoy["gaps"][0]["title"], "Review threat")
        self.assertTrue(sanjoy["gaps"][0]["threat"])
        self.assertEqual(sanjoy["gaps"][1]["status"], "waiting")
        shown = load_gap_board([], directory=folder.name, email=OWNER)
        shown_titles = [gap["title"] for gap in shown["gaps"]]
        self.assertIn("Salary run", shown_titles)
        self.assertIn("Exits", shown_titles)
        self.assertEqual(shown["counts"]["fixed"], 1)
        self.assertEqual(shown["counts"]["open"], 2)
        folder.cleanup()

    def test_albus_gaps_follow_store_and_city(self):
        index = get_index()
        board = load_gap_board(index.rows, email=OWNER)
        titles = [gap["title"] for gap in board["gaps"]]
        self.assertIn("No single store list", titles)
        self.assertIn("221 unpriced Restroworks ingredients", titles)
        self.assertIn("No store-level net sales", titles)
        waiting = next(gap for gap in board["gaps"] if gap["title"] == "No store-level net sales")
        self.assertEqual(waiting["status"], "waiting")
        self.assertEqual(waiting["owner"], "Anup, Vikas")
        pin = next(gap for gap in board["gaps"] if "share one map pin" in gap["title"])
        self.assertEqual(pin["owner"], "Sanjoy")
        self.assertTrue(pin["threat"])

        def titles_for(**filters):
            kept = filter_gaps(board["gaps"], filters, index)
            return [gap["title"] for gap in kept]

        kolkata = titles_for(cc_city="Kolkata")
        self.assertIn("Recipe looks incomplete: Regular Masala Dosa", kolkata)
        self.assertIn("Recipe looks incomplete: Extra Sambar - 250ml", kolkata)
        self.assertIn("No Google listing", kolkata)
        self.assertIn("New Town CK and Rosedale share one map pin", kolkata)
        self.assertNotIn("Recipe looks incomplete: Onion", kolkata)
        self.assertNotIn("No single store list", kolkata)
        self.assertNotIn("221 unpriced Restroworks ingredients", kolkata)
        self.assertNotIn("No store-level net sales", kolkata)
        self.assertFalse(any("Connaught" in title or "Faridabad" in title for title in kolkata))

        delhi = titles_for(cc_city="Delhi NCR")
        self.assertIn("Recipe looks incomplete: Extra Sambar - 250ml", delhi)
        self.assertIn("Recipe looks incomplete: Onion", delhi)
        self.assertIn("Duplicate listing", delhi)
        self.assertIn("Unverified listing", delhi)
        self.assertNotIn("Recipe looks incomplete: Regular Masala Dosa", delhi)
        self.assertNotIn("New Town CK and Rosedale share one map pin", delhi)
        self.assertFalse(any("Quest Mall" in (gap.get("store") or "") for gap in filter_gaps(board["gaps"], {"cc_city": "Delhi NCR"}, index) if gap["owner"] == "Siddhant" and gap["title"] == "No Google listing"))

        cp = "connaught-place-02-0012"
        one = titles_for(cc_store=cp)
        self.assertIn("Duplicate listing", one)
        self.assertIn("Recipe looks incomplete: Extra Sambar - 250ml", one)
        self.assertNotIn("Recipe looks incomplete: Regular Masala Dosa", one)
        self.assertNotIn("No single store list", one)
        self.assertNotIn("No Google listing", one)
        self.assertNotIn("New Town CK and Rosedale share one map pin", one)

        salt = filter_gaps(
            [{"title": "Salt Lake only", "store": "Salt Lake", "why_it_matters": "", "store_ids": []}],
            {"cc_store": "dosa-coffee-salt-lake-002"},
            index,
        )
        self.assertEqual(salt, [])

        self._session(OWNER)
        page = self.client.get("/data-gaps?cc_city=Kolkata&cc_store=")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Recipe looks incomplete", html)
        self.assertIn('data-owner="Sailesh"', html)
        self.assertIn("Coriander Leaves", html)
        self.assertIn("Sailesh", html)
        self.assertIn("Extra Sambar", html)
        self.assertIn("share one map pin", html)
        self.assertNotIn("Recipe looks incomplete: Onion", html)
        self.assertNotIn("No single store list", html)
        self.assertIn('value="Kolkata" selected', html)
        self.assertIn(">Today<", html)
        self.assertIn(">Outside<", html)

    def test_store_master_page_is_owner_only(self):
        self._session(None)
        anon = self.client.get("/store-master")
        self.assertEqual(anon.status_code, 302)
        self.assertIn("login", anon.headers["Location"])

        self._session(OTHER)
        blocked = self.client.get("/store-master")
        self.assertEqual(blocked.status_code, 302)
        brief = blocked.headers["Location"] and self.client.get("/brief")
        self.assertNotIn("Store Master", brief.get_data(as_text=True))

        self._session(OWNER)
        page = self.client.get("/store-master?cc_store=&cc_city=")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Store Master", html)
        self.assertIn("Connaught place", html)
        self.assertIn('name="cc_store"', html)
        self.assertNotIn("Known names", html)
        self.assertNotIn(".csv", html)
        self.assertNotIn(NOT_ON_REELO, html)
        city = self.client.get("/store-master?cc_city=Kolkata&cc_store=")
        body = city.get_data(as_text=True)
        self.assertIn("Quest Mall", body)
        self.assertNotIn("Connaught place", body)
        self.assertNotIn("Sec 15 Faridabad", body)
