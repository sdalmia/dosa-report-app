"""October mystery audit and Famepilot tickets, checked against the files."""

import csv
import unittest
from pathlib import Path

from app import create_app
from app.chat.facts import answer_from_data
from app.chat.snapshot import reset_snapshot, snapshot
from app.chat.suggestions import AUDIT, chips

ROOT = Path(__file__).resolve().parents[1]


def _october_bottom():
    path = ROOT / "data" / "store_health" / "mystery_audit.csv"
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            if "october" not in (raw.get("period") or "").casefold():
                continue
            if (raw.get("status") or "").casefold() == "brand aggregate":
                continue
            text = (raw.get("avg_score") or "").replace("%", "").strip()
            try:
                score = float(text)
            except ValueError:
                continue
            rows.append((score, raw["store"]))
    rows.sort()
    return rows


def _ticket_file():
    path = ROOT / "data" / "famepilot" / "tickets.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class OctoberAuditTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.data = snapshot()

    def test_bottom_three_match_the_october_file(self):
        file_rows = _october_bottom()
        self.assertEqual([score for score, _store in file_rows[:3]], [74.2, 81.6, 81.9])
        self.assertEqual(
            [store for _score, store in file_rows[:3]],
            ["Jasola Mall", "CP", "Shalimar Bagh"],
        )
        attention = self.data["attention"]["october_audit"]
        self.assertEqual([row["score"] for row in attention], [74.2, 81.6, 81.9])
        names = " ".join(row["store"].casefold() for row in attention)
        self.assertIn("jasola", names)
        self.assertIn("connaught", names)
        self.assertIn("shalimar", names)

        answer = answer_from_data(AUDIT[0], self.data, False)
        self.assertIn("74.2%", answer["text"])
        self.assertIn("Next:", answer["text"])
        self.assertIn("Make an action plan", answer["followups"])
        table_scores = [row[1] for row in answer["table"]["rows"]]
        self.assertEqual(table_scores[0], "74.2%")
        self.assertEqual(table_scores, sorted(table_scores, key=lambda text: float(text.replace("%", ""))))
        for score, _store in file_rows[:5]:
            self.assertIn(f"{score:.1f}%", table_scores)

    def test_opening_chips_lead_with_the_audit_question(self):
        shown = chips(False, sales=True, audit=True)
        self.assertEqual(shown[0], AUDIT[0])
        app = create_app()
        app.config["TESTING"] = True
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant", "email": "siddhant@dalgreenfoods.com"}
            sess["user_email"] = "siddhant@dalgreenfoods.com"
        html = client.get("/dashboard").get_data(as_text=True)
        self.assertIn(AUDIT[0], html)
        self.assertLess(html.find("North pace"), html.find(AUDIT[0]))


class TicketTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.data = snapshot()
        self.rows = _ticket_file()

    def test_channel_split_and_stale_share_match_the_file(self):
        total = len(self.rows)
        stale = sum(1 for row in self.rows if (row.get("keyword") or "").casefold() == "stale")
        zomato = sum(1 for row in self.rows if (row.get("platform") or "").casefold() == "zomato")
        swiggy = sum(1 for row in self.rows if (row.get("platform") or "").casefold() == "swiggy")
        share = round(stale / total * 100, 1)
        answer = answer_from_data("How do the Famepilot tickets split between Zomato and Swiggy?", self.data, False)
        self.assertIn(f"Zomato {zomato}", answer["text"])
        self.assertIn(f"Swiggy {swiggy}", answer["text"])
        self.assertIn(f"{share:.1f}%", answer["text"])
        self.assertIn("more than 7 days ago", answer["text"])
        self.assertIn("Next:", answer["text"])
        self.assertIn("Make an action plan", answer["followups"])
        by_channel = {row[0]: row for row in answer["table"]["rows"]}
        self.assertEqual(by_channel["Zomato"][1], str(zomato))
        self.assertEqual(by_channel["Swiggy"][1], str(swiggy))
        zomato_stale = sum(
            1 for row in self.rows
            if (row.get("platform") or "").casefold() == "zomato" and (row.get("keyword") or "").casefold() == "stale"
        )
        self.assertEqual(by_channel["Zomato"][2], str(zomato_stale))

    def test_a_named_store_uses_only_its_ticket_rows(self):
        wanted = [
            row for row in self.rows
            if "connaught" in (row.get("store") or "").casefold()
        ]
        self.assertTrue(wanted)
        stale = sum(1 for row in wanted if (row.get("keyword") or "").casefold() == "stale")
        share = round(stale / len(wanted) * 100, 1)
        answer = answer_from_data("Famepilot tickets at Connaught Place, including the stale share", self.data, False)
        self.assertIn("Connaught", answer["text"])
        self.assertIn(str(len(wanted)), answer["text"])
        self.assertIn(f"{share:.1f}%", answer["text"])
        self.assertNotIn(str(len(self.rows)), answer["text"])


if __name__ == "__main__":
    unittest.main()
