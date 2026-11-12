"""Feedback storage, insights access, and learned suggestions."""

import hashlib
import json
import logging
import os
import unittest

from app import create_app
from app.chat.house import house_notes
from app.chat.memory import ChatFeedback, gap_reason, learned_questions, record_ask, record_rating
from app.chat.suggestions import chips
from app.extensions import db


class GapReasonTests(unittest.TestCase):
    def test_reasons(self):
        self.assertEqual(gap_reason("Company profit is only on the owner login."), "refusal")
        self.assertEqual(gap_reason("Buying prices aren't loaded yet."), "stale")
        self.assertEqual(gap_reason("That price isn't in the loaded buying summary."), "no_data")
        self.assertEqual(gap_reason("November pace is 85.8%."), "")


class LearningStorageTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        ChatFeedback.query.filter(ChatFeedback.question.like("Learn test %")).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def test_thumbs_down_keeps_a_note_and_up_does_not(self):
        ask_id = record_ask("Learn test milk price", "procurement", "11 Nov 2026", "ops", "person", "")
        record_rating(ask_id, "Learn test milk price", "procurement", "11 Nov 2026", "down", "Too vague", "ops", "person", "")
        row = db.session.get(ChatFeedback, ask_id) if hasattr(db.session, "get") else ChatFeedback.query.get(ask_id)
        self.assertEqual(row.rating, "down")
        self.assertEqual(row.note, "Too vague")
        self.assertEqual(row.role, "ops")
        self.assertEqual(row.source, "person")
        self.assertEqual(row.actor, "")
        record_rating(ask_id, "Learn test milk price", "procurement", "11 Nov 2026", "up", "ignore this key sk-test", "ops", "person", "")
        db.session.refresh(row)
        self.assertEqual(row.rating, "up")
        self.assertIsNone(row.note)
        columns = {column.name for column in ChatFeedback.__table__.columns}
        self.assertNotIn("api_key", columns)
        self.assertNotIn("prompt", columns)

    def test_a_bot_rating_stores_the_name_not_the_key(self):
        secret = "learn-secret-key"
        os.environ["CHAT_BOT_KEYS"] = json.dumps({
            "tony": {"hash": hashlib.sha256(secret.encode()).hexdigest(), "role": "ops"},
        })
        try:
            with self.assertLogs("app.routes.main", level="INFO") as captured:
                response = self.client.post(
                    "/api/chat/feedback",
                    json={
                        "question": "Learn test quiet Tuesday",
                        "topic": "sales",
                        "data_as_of": "11 Nov 2026",
                        "rating": "up",
                        "note": secret,
                        "api_key": secret,
                    },
                    headers={"Authorization": "Bearer " + secret},
                )
            self.assertEqual(response.status_code, 200)
            blob = " ".join(captured.output)
            self.assertNotIn(secret, blob)
            row = ChatFeedback.query.filter_by(question="Learn test quiet Tuesday").one()
            self.assertEqual(row.source, "bot")
            self.assertEqual(row.actor, "tony")
            self.assertEqual(row.role, "ops")
            self.assertIsNone(row.note)
            self.assertNotIn(secret, " ".join(str(getattr(row, name) or "") for name in (
                "question", "topic", "note", "actor", "role", "source", "data_as_of",
            )))
        finally:
            os.environ.pop("CHAT_BOT_KEYS", None)

    def test_often_and_well_rated_questions_join_the_pool_for_the_role(self):
        for _ in range(3):
            record_rating(None, "Learn test which counter is quiet", "sales", "11 Nov 2026", "up", "", "ops", "person", "")
            record_rating(None, "Learn test cash in the Delhi account", "finance", "11 Nov 2026", "up", "", "finance", "bot", "accountant")
        ops = learned_questions("ops")
        self.assertIn("Learn test which counter is quiet", ops)
        self.assertNotIn("Learn test cash in the Delhi account", ops)
        finance = learned_questions("finance")
        self.assertIn("Learn test cash in the Delhi account", finance)
        shown = chips(False, sales=True)
        self.assertIn("Learn test which counter is quiet", shown)
        self.assertNotIn("Learn test cash in the Delhi account", shown)

    def test_house_notes_are_loaded_for_the_model(self):
        text = house_notes()
        self.assertIn("Rosedale", text)
        self.assertIn("own baseline", text)
        self.assertIn("Manisquare", text)


class InsightsAccessTests(unittest.TestCase):
    def setUp(self):
        secret = "insights-secret"
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

    def _login(self, email):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Tester", "email": email}
            sess["user_email"] = email

    def test_insights_page_is_owner_only_and_unlinked(self):
        self._login("guest@example.com")
        blocked = self.client.get("/chat/insights")
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("/dashboard", blocked.headers["Location"])
        self._login("siddhant@dalgreenfoods.com")
        page = self.client.get("/chat/insights")
        self.assertEqual(page.status_code, 200)
        self.assertIn("What the chat is learning", page.get_data(as_text=True))
        home = self.client.get("/dashboard")
        self.assertNotIn("/chat/insights", home.get_data(as_text=True))
        self.assertNotIn('href="/chat/insights"', home.get_data(as_text=True))

    def test_insights_api_allows_ops_and_refuses_finance_without_logging_the_key(self):
        missing = self.client.get("/api/chat/insights?days=7")
        self.assertEqual(missing.status_code, 401)
        finance = self.client.get(
            "/api/chat/insights?days=7",
            headers={"Authorization": "Bearer " + self.finance},
        )
        self.assertEqual(finance.status_code, 403)
        logger = logging.getLogger("app.routes.main")
        logger.setLevel(logging.INFO)
        with self.assertLogs("app.routes.main", level="INFO") as captured:
            allowed = self.client.get(
                "/api/chat/insights?days=7",
                headers={"Authorization": "Bearer " + self.secret},
            )
        self.assertEqual(allowed.status_code, 200)
        body = allowed.get_json()
        self.assertEqual(body["days"], 7)
        self.assertIn("most_asked", body)
        self.assertIn("thumbs_down", body)
        self.assertIn("gaps", body)
        self.assertNotIn(self.secret, " ".join(captured.output))


class ModelLogTests(unittest.TestCase):
    def test_the_model_call_does_not_log_the_key_or_the_prompt(self):
        from app.chat.answer import produce_answer

        os.environ["CHAT_API_KEY"] = "super-secret-key"
        os.environ["CHAT_API_URL"] = "http://127.0.0.1:9/nope"
        os.environ.pop("CHAT_MOCK", None)
        data = {"role": "ops", "sales_windows": {}, "summary": {}, "dossiers": {}}
        try:
            with self.assertLogs("app.chat.answer", level="INFO") as captured:
                result = produce_answer("How is North?", data, False)
            blob = " ".join(captured.output)
            self.assertEqual(result["fallback"], "request_error")
            self.assertTrue(result["text"].startswith("AI unavailable"))
            self.assertIn("model_used=none", blob)
            self.assertIn("fallback=request_error", blob)
            self.assertNotIn("super-secret-key", blob)
            self.assertNotIn("House notes", blob)
            self.assertNotIn("79.9", blob)
        finally:
            os.environ.pop("CHAT_API_KEY", None)
            os.environ.pop("CHAT_API_URL", None)


if __name__ == "__main__":
    unittest.main()
