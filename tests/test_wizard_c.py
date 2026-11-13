"""Exports, share links, Chief of Staff, and the inbox digest."""

import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app import create_app
from app.chat.extras import ChiefRequest, ChatSnapshot, strip_html
from app.extensions import db


class ExtraTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CHAT_INGEST_KEY", None)
        os.environ.pop("CHAT_INGEST_TOKEN", None)
        os.environ.pop("WIZARD_WEBHOOK_URL", None)
        os.environ.pop("WIZARD_WEBHOOK_KEY", None)
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _login(self, email):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant", "email": email}
            sess["user_email"] = email

    def test_inbox_requires_a_token_and_strips_html(self):
        missing = self.client.post("/api/chat/inbox-digest", json={"items": []})
        self.assertEqual(missing.status_code, 503)
        os.environ["CHAT_INGEST_KEY"] = "ingest-secret"
        denied = self.client.post(
            "/api/chat/inbox-digest",
            data=b"{}",
            headers={"Authorization": "Bearer wrong", "Content-Type": "application/json"},
        )
        self.assertEqual(denied.status_code, 401)
        body = {"items": [{"summary": "<b>Call the landlord</b>", "subject": "Rent"}]}
        ok = self.client.post(
            "/api/chat/inbox-digest",
            data=json.dumps(body),
            headers={"Authorization": "Bearer ingest-secret", "Content-Type": "application/json"},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertNotIn("<b>", json.dumps(strip_html(body)))

    def test_share_of_a_finance_answer_stays_on_the_owner_login(self):
        self._login("siddhant@dalgreenfoods.com")
        created = self.client.post("/api/chat/share", json={
            "question": "Show Grand Economics EBITDA",
            "answer": "EBITDA is loaded.",
            "days": 7,
            "public": True,
        })
        self.assertEqual(created.status_code, 200)
        payload = created.get_json()
        self.assertTrue(payload["restricted"])
        self.assertNotIn("ingest-secret", json.dumps(payload))
        token = payload["url"].rsplit("/", 1)[-1]
        self.client2 = self.app.test_client()
        with self.client2.session_transaction() as sess:
            sess["user"] = {"name": "Ops", "email": "ops@dosacoffee.com"}
            sess["user_email"] = "ops@dosacoffee.com"
        denied = self.client2.get("/chat/s/" + token)
        self.assertEqual(denied.status_code, 403)
        with self.app.app_context():
            row = ChatSnapshot.query.filter_by(token=token).one()
            row.expires_at = datetime.utcnow() - timedelta(days=1)
            db.session.commit()
        expired = self.client.get("/chat/s/" + token)
        self.assertEqual(expired.status_code, 410)

    def test_chief_of_staff_sends_only_on_click_and_hides_the_key(self):
        self._login("siddhant@dalgreenfoods.com")
        os.environ["WIZARD_WEBHOOK_URL"] = "https://example.test/hook"
        os.environ["WIZARD_WEBHOOK_KEY"] = "super-secret-key"
        from app.chat.facts import answer_from_data
        from app.chat.snapshot import view_for

        with self.app.app_context():
            before = ChiefRequest.query.count()
        answer_from_data("Ask HR to call back absconders", view_for(role="owner"), True)
        with self.app.app_context():
            self.assertEqual(ChiefRequest.query.count(), before)
        with patch("urllib.request.urlopen") as opened:
            opened.return_value.__enter__.return_value.read.return_value = b"{}"
            response = self.client.post("/api/chat/cos", json={"request": "Call absconders", "excerpt": "9 exits"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("super-secret-key", response.get_data(as_text=True))
        self.assertEqual(opened.call_count, 1)
        sent = opened.call_args.args[0]
        self.assertEqual(sent.get_header("X-webhook-key"), "super-secret-key")


if __name__ == "__main__":
    unittest.main()
