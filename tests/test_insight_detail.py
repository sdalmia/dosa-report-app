"""Insight card details use the files and do not invent a blank net."""

import unittest

from app import create_app
from app.chat.insight_detail import build_detail
from app.chat.wizard_a import trend_cards


class InsightDetailTests(unittest.TestCase):
    def test_store_sheet_uses_the_full_week_and_leaves_net_blank(self):
        detail = build_detail("gurgaon-dlf", "owner")
        card = next(row for row in trend_cards() if "Gurgaon" in row["title"])
        self.assertEqual(detail["title"], "Gurgaon DLF")
        self.assertEqual(detail["headline"], card["line"])
        self.assertEqual(detail["window"], "6–12 Nov vs 30 Oct–5 Nov")
        self.assertEqual(len(detail["days"]), 7)
        self.assertEqual(detail["total"]["day"], "Total")
        self.assertEqual(len(detail["chart"]["this_week"]), 7)
        self.assertGreaterEqual(len(detail["facts"]), 3)
        self.assertLessEqual(len(detail["facts"]), 4)
        self.assertTrue(any(line.startswith("Bills ") for line in detail["facts"]))
        self.assertTrue(any(line.startswith("Biggest ") for line in detail["facts"]))
        self.assertTrue(any(line.startswith("City: other Delhi NCR") for line in detail["facts"]))
        self.assertEqual(detail["about"].count("."), 2)
        self.assertIn("net is blank", detail["about"].casefold())
        self.assertEqual(detail["headline"].count(detail["window"]), 1)
        self.assertEqual(detail["days"][0]["day"], "Fri 6 Nov")
        self.assertNotIn("-₹", detail["headline"])
        self.assertNotIn("(02/", detail["share_text"])
        self.assertEqual(detail["city"]["name"], "Delhi NCR")
        peers = " ".join(detail["city"]["peers"]).casefold()
        for name in ("faridabad", "rosedale", "chattarpur", "gk1"):
            self.assertNotIn(name, peers)
        self.assertIn("9 Nov", detail["about"])
        self.assertIn("no store channel file", detail["about"].casefold())
        self.assertTrue(all(row["prior"] == "not in the file" for row in detail["channels"]["rows"]))
        self.assertTrue(detail["days"][0]["this_bills"].isdigit())

    def test_licence_sheet_lists_expired_and_expiring(self):
        detail = build_detail("licences", "owner")
        self.assertEqual(detail["headline"], "9 licences expired, 3 expire in 30 days")
        self.assertEqual(len(detail["rows"]), 12)
        first = detail["rows"][0]
        self.assertEqual(first["store"], "Forum")
        self.assertEqual(first["type"], "Police")
        self.assertEqual(first["expiry"], "31 Mar 2026")
        self.assertIn("overdue", first["when"])
        self.assertNotIn("licence_no", detail["share_text"])
        blocked = build_detail("licences", "finance")
        self.assertEqual(blocked["error"], "forbidden")
        self.assertIsNone(build_detail("not-a-store", "owner"))

    def test_details_endpoint_requires_login(self):
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        blocked = client.get("/api/chat/insights/gurgaon-dlf/details")
        self.assertEqual(blocked.status_code, 302)
        with client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant", "email": "siddhant@dalgreenfoods.com"}
            sess["user_email"] = "siddhant@dalgreenfoods.com"
        page = client.get("/api/chat/insights/gurgaon-dlf/details")
        self.assertEqual(page.status_code, 200)
        body = page.get_json()
        self.assertEqual(body["title"], "Gurgaon DLF")
        self.assertIn("net is blank", body["about"].casefold())
        self.assertEqual(len(body["days"]), 7)
        self.assertIn("this_gross", body["days"][0])
        self.assertIn("prior_gross", body["days"][0])
        missing = client.get("/api/chat/insights/not-a-store/details")
        self.assertEqual(missing.status_code, 404)
        home = client.get("/dashboard")
        html = home.get_data(as_text=True)
        self.assertIn('data-id="gurgaon-dlf"', html)
        self.assertIn('id="insight-sheet"', html)
        opened = client.get("/dashboard?insight=licences")
        text = opened.get_data(as_text=True)
        self.assertIn("9 licences expired, 3 expire in 30 days", text)
        self.assertIn("227 days overdue", text)


if __name__ == "__main__":
    unittest.main()
