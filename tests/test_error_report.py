"""The Report an error mail: a fixed subject, a labelled body, and a local log."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.chat.error_report import prefill, subject_line, submit_report


class ErrorReportTests(unittest.TestCase):
    def setUp(self):
        self.log = Path(tempfile.mkdtemp()) / "error_reports.jsonl"
        self.patch = patch("app.chat.error_report._LOG", self.log)
        self.patch.start()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.patch.stop()

    def _login(self, email="siddhant@dalgreenfoods.com"):
        with self.client.session_transaction() as sess:
            sess["user"] = {"email": email}
            sess["user_email"] = email

    def test_subject_is_a_fixed_machine_line(self):
        line = subject_line("Sales", "Ideal Plaza", "17 Nov–23 Nov 2026", "Net sales", "₹9.85 L")
        self.assertEqual(
            line,
            "[Wizard error] Sales | Ideal Plaza | 17 Nov–23 Nov 2026 | Net sales: ₹9.85 L",
        )
        blank = subject_line("", "  ", "", "", "")
        self.assertEqual(blank, "[Wizard error] Other | Unknown | Unknown | Unknown: Unknown")
        self.assertNotIn("|  |", blank)
        self.assertFalse(any(part.strip() == "" for part in blank.split("|")))

    def test_prefill_comes_from_the_answer(self):
        fields = prefill(
            "How did Ideal Plaza do?",
            "Net sales ₹9.85 L for 17-23 Nov 2026.",
        )
        self.assertEqual(fields["area"], "Sales")
        self.assertEqual(fields["place"], "Ideal Plaza")
        self.assertEqual(fields["dates"], "17 Nov–23 Nov 2026")
        self.assertEqual(fields["metric"], "Net sales")
        self.assertEqual(fields["value"], "₹9.85 L")
        from app.chat.facts import answer_from_data
        growth = answer_from_data(
            "Are we growing or de-growing in sales, transactions and APC, and why?",
            {"role": "owner"},
            True,
        )["text"]
        guessed = prefill(
            "Are we growing or de-growing in sales, transactions and APC, and why?",
            growth,
        )
        self.assertEqual(guessed["area"], "Sales")
        self.assertEqual(guessed["place"], "Network")
        self.assertEqual(guessed["dates"], "1 Nov–23 Nov 2026")
        self.assertEqual(guessed["metric"], "Sales")
        self.assertEqual(guessed["value"], "-7.9%")
        flat = " ".join(growth.replace("|", " ").replace("#", " ").replace("*", " ").split())
        shown = prefill(
            "Are we growing or de-growing in sales, transactions and APC, and why?",
            flat,
        )
        self.assertEqual(shown["place"], "Network")
        self.assertEqual(shown["value"], "-7.9%")

    def test_body_repeats_the_fields_and_redacts_for_a_non_owner(self):
        sent = {}

        def mailer(subject, body, turns):
            sent["subject"] = subject
            sent["body"] = body

        result = submit_report({
            "area": "Sales",
            "place": "Ideal Plaza",
            "dates": "17 Nov–23 Nov 2026",
            "metric": "Net sales",
            "value": "₹9.85 L",
            "note": "The week is short",
            "correction": "₹10.10 L",
            "answer": "Net sales ₹9.85 L",
            "page": "/dashboard",
            "turns": [
                {"role": "user", "text": "How did Ideal Plaza do?"},
                {"role": "wizard", "text": "EBITDA is 10 and rent is high"},
            ],
        }, "ops@dalgreenfoods.com", False, mailer)
        self.assertTrue(result["ok"])
        self.assertTrue(sent["subject"].startswith("[Wizard error] Sales | Ideal Plaza |"))
        self.assertIn("Area: Sales", sent["body"])
        self.assertIn("Store or Network/City: Ideal Plaza", sent["body"])
        self.assertIn("Date range: 17 Nov–23 Nov 2026", sent["body"])
        self.assertIn("Metric: Net sales", sent["body"])
        self.assertIn("Disputed value: ₹9.85 L", sent["body"])
        self.assertIn("[redacted]", sent["body"])
        self.assertNotIn("EBITDA", sent["body"])
        self.assertTrue(self.log.is_file())

    def test_an_owner_keeps_the_finance_lines(self):
        sent = {}
        submit_report({
            "note": "Wrong",
            "turns": [{"role": "wizard", "text": "EBITDA is 10"}],
        }, "siddhant@dalgreenfoods.com", True, lambda subject, body, turns: sent.update(body=body))
        self.assertIn("EBITDA is 10", sent["body"])

    def test_route_saves_the_log_when_mail_is_not_configured(self):
        os.environ.pop("MAIL_SERVER", None)
        os.environ.pop("MAIL_USERNAME", None)
        self._login()
        response = self.client.post("/api/chat/error-report", json={
            "area": "Sales",
            "place": "Ideal Plaza",
            "dates": "17 Nov–23 Nov 2026",
            "metric": "Net sales",
            "value": "₹9.85 L",
            "note": "Too low",
        })
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "Couldn't send, try again")
        saved = json.loads(self.log.read_text(encoding="utf-8").strip())
        self.assertEqual(
            saved["subject"],
            "[Wizard error] Sales | Ideal Plaza | 17 Nov–23 Nov 2026 | Net sales: ₹9.85 L",
        )

    def test_route_sends_the_subject_and_attachments(self):
        os.environ["MAIL_SERVER"] = "smtp.example.com"
        os.environ["MAIL_USERNAME"] = "wizard@example.com"
        self._login()
        with patch("app.mail.mail.send") as send:
            response = self.client.post("/api/chat/error-report", json={
                "area": "sales",
                "place": "Ideal Plaza",
                "dates": "17 Nov–23 Nov 2026",
                "metric": "Net sales",
                "value": "₹9.85 L",
                "note": "Too low",
                "answer": "Net sales ₹9.85 L",
                "turns": [{"role": "user", "text": "Ideal Plaza?"}],
            })
        os.environ.pop("MAIL_SERVER", None)
        os.environ.pop("MAIL_USERNAME", None)
        self.assertEqual(response.status_code, 200)
        message = send.call_args.args[0]
        self.assertEqual(
            message.subject,
            "[Wizard error] Sales | Ideal Plaza | 17 Nov–23 Nov 2026 | Net sales: ₹9.85 L",
        )
        self.assertIn("Area: Sales", message.body)
        kinds = [item.content_type for item in message.attachments]
        self.assertIn("text/plain", kinds)
        self.assertIn("text/html", kinds)

    def test_the_page_has_a_report_button_and_no_unconnected_send(self):
        script = Path("static/js/chat.js").read_text(encoding="utf-8")
        self.assertIn("Report an error", script)
        self.assertNotIn("Send to Chief of Staff", script)
        self.assertNotIn("isn't connected yet", script)
        self.assertNotIn('data-act="cos"', script)


if __name__ == "__main__":
    unittest.main()
