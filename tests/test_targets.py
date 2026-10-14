"""October net targets and the 13 Oct gross pace."""

import os
import tempfile
import unittest
from datetime import date

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _DB.name)
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import create_app
from app.store_health.contract import load_feeds
from app.targets import build_board, canonical_store_code, load_targets

TODAY = date(2026, 10, 14)


class TargetBoardTests(unittest.TestCase):
    def test_tony_file_maps_thirty_stores_and_skips_events(self):
        rows = load_targets()
        self.assertEqual(len(rows), 30)
        self.assertEqual(sum(row["target_net"] for row in rows), 56725000)
        self.assertTrue(all(row["mapped"] for row in rows))
        self.assertEqual(canonical_store_code("002"), "01/0002")
        self.assertEqual(canonical_store_code("0009"), "01/0009")
        by_budget = {row["budget_name"]: row for row in rows}
        self.assertEqual(by_budget["JC 21"]["name"], "Salt Lake (002)")
        self.assertEqual(by_budget["BD 25"]["name"], "Salt Lake Sec-1 (0009)")
        self.assertEqual(by_budget["IP"]["name"], "Ideal Plaza (01/0001)")
        self.assertEqual(by_budget["Faridabad"]["target_net"], 1200000)
        self.assertEqual(by_budget["Faridabad"]["status"], "closing 20 Oct")
        self.assertNotIn("Events & Catering", by_budget)
        self.assertNotIn("Event & Catering", by_budget)

    def test_pace_is_gross_against_a_net_target_with_network_net_on_top(self):
        feeds = load_feeds()
        board = build_board(feeds["posist"], TODAY)
        self.assertEqual(len(board["rows"]), 30)
        self.assertEqual(board["rows"][0]["name"], "Gurgaon Sec 10 (02/0014)")
        self.assertEqual(board["rows"][0]["pct_label"], "61.9%")
        self.assertTrue(board["rows"][0]["line"].startswith("Gross "))
        self.assertEqual(board["note"], "Rough guide (gross vs net target).")
        self.assertIn("86.4% of pro-rata", board["network"])
        self.assertIn("11–13 Oct", board["network"])
        self.assertIn("96.3%", board["pace"])
        self.assertTrue(board["pace"].startswith("1–13 Oct gross "))
        faridabad = next(row for row in board["rows"] if row["budget_name"] == "Faridabad")
        self.assertEqual(faridabad["tag"], "closing 20 Oct")
        self.assertIn("month ₹12L", faridabad["line"])
        self.assertIn("81.2%", faridabad["line"])
        truck = next(row for row in board["rows"] if row["budget_name"] == "Food Truck")
        self.assertIn("9 days on file", truck["line"])
        names = " ".join(row["name"] for row in board["rows"])
        self.assertNotIn("Events", names)
        self.assertNotIn("₹0", board["network"] + board["pace"] + board["note"])

    def test_a_store_with_no_target_stays_empty(self):
        board = build_board(
            {("Dosa Coffee - Events & Catering", TODAY): {"gross": 1000}},
            TODAY,
            store_label="Dosa Coffee - Events & Catering",
        )
        self.assertEqual(board["rows"], [])
        self.assertEqual(board["empty"], "No target for this store.")
        self.assertEqual(build_board({}, TODAY)["rows"], [])

    def test_home_loads_the_pace_after_first_paint(self):
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user"] = {"name": "Asha Rao", "email": "asha@dosacoffee.com"}
        home = client.get("/dashboard")
        self.assertEqual(home.status_code, 200)
        html = home.get_data(as_text=True)
        self.assertIn('data-src="/dashboard/targets"', html)
        self.assertNotIn("61.9%", html)
        self.assertNotIn("Rough guide", html)
        fragment = client.get("/dashboard/targets")
        self.assertEqual(fragment.status_code, 200)
        body = fragment.get_data(as_text=True)
        self.assertIn("Rough guide (gross vs net target).", body)
        self.assertIn("86.4% of pro-rata", body)
        self.assertIn("61.9%", body)
        self.assertIn("Salt Lake (002)", body)
        self.assertIn("Salt Lake Sec-1 (0009)", body)
        self.assertIn("closing 20 Oct", body)
        self.assertIn("month ₹12L", body)
        self.assertNotIn("Events", body)
        self.assertNotIn(".csv", body)
        self.assertNotIn(".xlsx", body)
        self.assertNotRegex(body, r"\bblank\b")
        self.assertNotIn('data-theme="dark"', body)


if __name__ == "__main__":
    unittest.main()
