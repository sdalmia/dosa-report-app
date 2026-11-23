"""Analytic answers explain themselves. A figure that is not in the packet does not survive."""

import os
import unittest

from app.chat.answer import _SYSTEM, produce_answer
from app.chat.context import build_context
from app.chat.facts import answer_from_data
from app.chat.snapshot import reset_snapshot, view_for


QUESTIONS = (
    "how did sales do last week",
    "why is North behind target",
    "which stores need attention",
    "how do we increase sales",
)


class ReasonedAnswerTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.data = view_for(role="ops")

    def test_an_analytic_question_has_why_and_next_steps(self):
        for question in QUESTIONS:
            answer = answer_from_data(question, self.data, False)
            text = answer["text"]
            self.assertIn("**Why**", text, question)
            self.assertIn("**Likely causes**", text, question)
            self.assertIn("**Next steps**", text, question)
            self.assertGreaterEqual(text.count("\n"), 4, question)
            self.assertNotIn("Faridabad", text.split("**Why**", 1)[-1].split("**Likely causes**", 1)[0])
            self.assertNotIn("than kolkata", text.casefold())
            self.assertNotIn("EBITDA", text)
            self.assertRegex(text, r"1\. .+Owner: ")

    def test_a_price_lookup_stays_short(self):
        answer = answer_from_data(
            "What are we paying for dosa daal this month vs last?",
            self.data,
            False,
        )
        self.assertNotIn("**Why**", answer["text"])
        self.assertIn("vs its last month", answer["text"].casefold())
        self.assertNotIn("than kolkata", answer["text"].casefold())

    def test_ops_still_cannot_see_profit(self):
        answer = answer_from_data("What's each company's profit this month?", self.data, False)
        self.assertNotIn("EBITDA", answer["text"])
        self.assertNotIn("15L", answer["text"])
        self.assertNotIn("**Why**", answer["text"])

    def test_the_packet_carries_daily_sales_and_tolerates_a_missing_forecast(self):
        text = build_context("how did sales do last week", self.data)
        self.assertIn("Per-store daily gross", text)
        self.assertIn("Point forecast, range, and month landing: not in the summary file.", text)
        self.assertIn("Famepilot tickets", text)
        self.assertIn("Procurement summary", text)
        self.assertIn("redemption_pct", text)
        self.assertNotIn("EBITDA", text)
        copied = dict(self.data)
        copied["summary"] = dict(self.data["summary"])
        copied["summary"]["point_forecast_L"] = 18.2
        copied["summary"]["month_landing_L"] = 410.0
        richer = build_context("how did sales do last week", copied)
        self.assertIn("point_forecast_L: 18.2", richer)
        self.assertIn("month_landing_L: 410.0", richer)

    def test_the_prompt_asks_for_a_full_answer_and_keeps_the_guardrails(self):
        self.assertIn("250 to 450", _SYSTEM)
        self.assertNotIn("150 words", _SYSTEM)
        self.assertIn("Never invent a number", _SYSTEM)
        self.assertIn("Finance, HR, and the inbox", _SYSTEM)
        self.assertIn("Sanjoy / Anup / Vikas", _SYSTEM)
        self.assertIn("Shilajit", _SYSTEM)


class UnknownNumberTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.data = view_for(role="ops")
        os.environ["CHAT_API_KEY"] = "test-key-not-a-secret"
        os.environ.pop("CHAT_MOCK", None)

    def tearDown(self):
        os.environ.pop("CHAT_API_KEY", None)

    def test_a_number_outside_the_packet_does_not_survive(self):
        reply = "\n".join([
            "**North is behind at 79.9%.**",
            "",
            "**Why**",
            "North pace is 79.9%. A gap of ₹9,99,999 is not real.",
            "",
            "**Next steps**",
            "1. Check the North stores behind 79.9% pace. Owner: Sanjoy / Anup / Vikas.",
            "```chart",
            '{"type":"bar","title":"Pace","unit":"%","series":[{"label":"North","value":79.9},{"label":"Made up","value":8675309}]}',
            "```",
        ])

        def client(messages, model):
            self.assertIn("**Why**", messages[0]["content"])
            self.assertIn("Per-store daily gross", messages[-1]["content"])
            return reply, None

        result = produce_answer("why is North behind target", self.data, False, client=client)
        self.assertIn("**Why**", result["text"])
        self.assertIn("**Next steps**", result["text"])
        self.assertIn("79.9%", result["text"])
        self.assertNotIn("9,99,999", result["text"])
        self.assertNotIn("999999", result["text"])
        self.assertIn("not in the file", result["text"])
        self.assertIsNone(result["chart"])
        self.assertIsNone(result["fallback"])


if __name__ == "__main__":
    unittest.main()
