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
from app.store_master import (
    COLUMNS,
    find_store,
    human_notes,
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
        self.assertEqual(len(self.rows), 33)
        self.assertEqual(len({row["store_id"] for row in self.rows}), 33)
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
        self.assertIn("reelo", forum)
        self.assertNotIn("google", forum)
        self.assertEqual(forum["reelo"]["status"], "Needs a Reelo name")

        truck = kinds("Dosa Coffee - Food Truck - 1 (0008)")
        self.assertIn("google", truck)
        self.assertIn("reelo", truck)
        self.assertNotIn("name", truck)

        for row in self.rows:
            delivery = {gap["kind"]: gap for gap in store_gaps(row)}["delivery"]
            self.assertEqual(delivery["status"], "Needs the ids")
            self.assertEqual(delivery["owner"], "Sanjoy / Subhra")
            self.assertNotIn("Known names", human_notes(row["notes"]))

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
        page = self.client.get("/data-gaps")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Data gaps", html)
        self.assertEqual(html.count("<header"), 1)
        self.assertIn('name="theme-color" content="#f7f6f3"', html)
        self.assertIn("Sanjoy / Subhra", html)
        self.assertIn("Needs a listing", html)
        self.assertIn("Duplicate listing", html)
        self.assertNotIn(".csv", html)
        self.assertNotIn("Known names", html)
        self.assertIn('class="cc-bottom"', html)
        bottom = html.split('class="cc-bottom"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn("Data gaps", bottom)
        self.assertEqual(bottom.count("<a "), 5)

        only = self.client.get("/data-gaps?gap=duplicate")
        body = only.get_data(as_text=True)
        self.assertIn("Connaught place", body)
        self.assertNotIn("Quest Mall", body)
        self.assertIn("Needs a cleanup", body)
