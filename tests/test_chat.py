"""Chat answers, the bot API, and the buying summary."""

import hashlib
import json
import os
import unittest

from app import create_app
from app.chat.bots import authenticate
from app.chat.facts import answer_from_data
from app.chat.snapshot import reset_snapshot, snapshot, view_for
from app.chat.visuals import verify_block


class ChatAnswerTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.data = snapshot()

    def test_pace_uses_the_summary_date_and_a_chart(self):
        answer = answer_from_data("How are we tracking against this month's target?", self.data, False)
        self.assertIn("84.3%", answer["text"])
        self.assertEqual(answer["as_of"], "12 Nov 2026")
        self.assertIsNotNone(answer["chart"])
        self.assertIsNone(answer["table"])
        self.assertIn("Make an action plan", answer["followups"])

    def test_prices_stay_on_each_city_baseline(self):
        answer = answer_from_data(
            "What are we paying for milk, paneer and cheese this month vs last?",
            self.data,
            False,
        )
        text = answer["text"].casefold()
        self.assertIn("vs its last month", text)
        self.assertNotIn("than kolkata", text)
        self.assertNotIn("than delhi", text)
        self.assertEqual(answer["as_of"], "12 Nov 2026")
        self.assertTrue(answer["table"]["rows"])

    def test_named_item_uses_each_city_baseline(self):
        answer = answer_from_data(
            "What are we paying for dosa daal this month vs last?",
            self.data,
            False,
        )
        text = answer["text"].casefold()
        self.assertIn("dosa daal", text)
        self.assertIn("vs its last month", text)
        self.assertIn("delhi", text)
        self.assertIn("kolkata", text)
        self.assertNotIn("than kolkata", text)
        self.assertNotIn("than delhi", text)
        self.assertEqual(answer["as_of"], "12 Nov 2026")

    def test_above_average_cites_the_city_baseline(self):
        answer = answer_from_data("Which items did we buy above average price this week?", self.data, False)
        self.assertIn("own baseline", answer["text"])
        self.assertIn("579.4%", answer["text"])
        self.assertEqual(answer["as_of"], "12 Nov 2026")

    def test_named_store_joins_sources_and_says_when_one_is_missing(self):
        answer = answer_from_data("Sec 143 Noida is soft, what else moved?", self.data, False)
        self.assertIn("Sec 143 Noida", answer["text"])
        self.assertIn("78.25%", answer["text"])
        self.assertIn("Forecast has no row", answer["text"])
        self.assertIn("Reviews have no row", answer["text"])
        self.assertNotIn("Staff lead", answer["text"])
        self.assertTrue(answer["table"])

    def test_ops_snapshot_has_no_finance(self):
        ops = view_for(role="ops")
        answer = answer_from_data("What's each company's profit this month?", ops, False)
        self.assertNotIn("15L", answer["text"])
        self.assertNotIn("EBITDA", answer["text"])
        self.assertEqual(ops["finance"], [])

    def test_finance_role_can_see_profit(self):
        finance = view_for(role="finance")
        answer = answer_from_data("What's each company's profit this month?", finance, False)
        self.assertIn("EBITDA", answer["text"])
        self.assertEqual(finance["dossiers"][next(iter(finance["dossiers"]))]["hr"], None)

    def test_a_made_up_chart_number_is_dropped(self):
        allowed = [85.8, 91.6, 79.9]
        blocked = verify_block(
            {"type": "bar", "series": [{"label": "East", "value": 999}]},
            allowed,
        )
        self.assertIsNone(blocked)


class TrackerFallbackTests(unittest.TestCase):
    def test_a_price_missing_from_the_summary_uses_the_tracker(self):
        from datetime import date

        from app.extensions import db
        from app.models import IngredientPrice

        app = create_app()
        app.config["TESTING"] = True
        with app.app_context():
            row = IngredientPrice(
                ingredient_name="Test Spice 999",
                unit_price=13,
                quantity=2,
                date=date(2026, 11, 2),
            )
            db.session.add(row)
            db.session.commit()
            try:
                answer = answer_from_data("What did we pay for Test Spice 999?", snapshot(), False)
            finally:
                db.session.delete(row)
                db.session.commit()
        self.assertIn("ingredient tracker", answer["text"].casefold())
        self.assertIn("₹13", answer["text"])
        self.assertNotIn("than kolkata", answer["text"].casefold())
        self.assertNotIn("buying summary", answer["text"].casefold())


class BotApiTests(unittest.TestCase):
    def setUp(self):
        secret = "ops-secret"
        finance = "finance-secret"
        os.environ["CHAT_BOT_KEYS"] = json.dumps({
            "tony": {"hash": hashlib.sha256(secret.encode()).hexdigest(), "role": "ops"},
            "accountant": {"hash": hashlib.sha256(finance.encode()).hexdigest(), "role": "finance"},
        })
        self.secret = secret
        self.finance = finance
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.environ.pop("CHAT_BOT_KEYS", None)

    def test_ops_key_cannot_read_accounts(self):
        denied = self.client.post("/api/ask", json={"question": "What's each company's profit this month?"})
        self.assertEqual(denied.status_code, 401)
        response = self.client.post(
            "/api/ask",
            json={"question": "What's each company's profit this month?", "mode": "answer"},
            headers={"Authorization": "Bearer " + self.secret},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertNotIn("EBITDA", body["answer"])
        self.assertNotIn("15L", body["answer"])
        plan = self.client.post(
            "/api/ask",
            json={"question": "Make an action plan", "mode": "action_plan"},
            headers={"Authorization": "Bearer " + self.secret},
        )
        actions = plan.get_json()["actions"]
        self.assertTrue(actions)
        self.assertLessEqual(len(actions), 5)
        self.assertTrue(all(row["why"] and row["owner"] and row["urgency"] for row in actions))
        self.assertNotIn("Shilajit", " ".join(row["owner"] for row in actions))

    def test_finance_key_can_read_profit(self):
        who = authenticate("Bearer " + self.finance)
        self.assertEqual(who["role"], "finance")
        response = self.client.post(
            "/api/ask",
            json={"question": "What's each company's profit this month?"},
            headers={"Authorization": "Bearer " + self.finance},
        )
        self.assertIn("EBITDA", response.get_json()["answer"])


if __name__ == "__main__":
    unittest.main()
