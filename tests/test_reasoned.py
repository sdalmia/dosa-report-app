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

    def test_an_analytic_question_uses_the_partner_shape(self):
        for question in QUESTIONS:
            answer = answer_from_data(question, self.data, False)
            text = answer["text"]
            pyramid = text.split("Growth plan")[0]
            self.assertTrue(pyramid.strip().startswith("**"), question)
            self.assertIn("**So what**", pyramid, question)
            self.assertIn("**Moves**", pyramid, question)
            self.assertIn("**Non-obvious insight.**", pyramid, question)
            self.assertIn("Hypothesis:", pyramid, question)
            self.assertIn("Test:", pyramid, question)
            self.assertRegex(pyramid[:500].casefold(), r"\byou\b|\byour\b", question)
            self.assertNotIn("Worth noting:", pyramid, question)
            self.assertNotIn("Faridabad", pyramid, question)
            self.assertNotIn("than kolkata", text.casefold(), question)
            self.assertNotIn("EBITDA", text, question)
            self.assertNotIn("packet", pyramid.casefold(), question)
            self.assertIn("Daypart is not loaded", pyramid, question)
            self.assertIn("24.78%", pyramid, question)
            self.assertIn("Rosedale", pyramid, question)
            self.assertNotIn("flagged as unexplained", pyramid.casefold(), question)
            moves = pyramid.split("**Moves**", 1)[1].split("**Non-obvious insight.**", 1)[0]
            numbered = [line for line in moves.splitlines() if line[:2] in {"1.", "2.", "3.", "4.", "5."}]
            self.assertGreaterEqual(len(numbered), 3, question)
            self.assertLessEqual(len(numbered), 5, question)
            for line in numbered:
                self.assertIn("Value:", line, question)
                self.assertIn("Owner:", line, question)
                self.assertIn("Timeframe:", line, question)
            self.assertTrue(any("not sized" in line.casefold() for line in numbered), question)
            self.assertRegex(text, r"1\. .+Owner: ")

    def test_a_price_lookup_stays_short(self):
        answer = answer_from_data(
            "What are we paying for dosa daal this month vs last?",
            self.data,
            False,
        )
        self.assertNotIn("**So what**", answer["text"])
        self.assertNotIn("**Why**", answer["text"])
        self.assertNotIn("Worth noting:", answer["text"])
        self.assertIn("vs its last month", answer["text"].casefold())
        self.assertNotIn("than kolkata", answer["text"].casefold())

    def test_a_sales_lookup_stays_short_and_adds_one_note(self):
        answer = answer_from_data("what were sales yesterday", self.data, False)
        text = answer["text"]
        self.assertNotIn("**So what**", text)
        self.assertNotIn("**Moves**", text)
        self.assertIn("Worth noting:", text)
        self.assertEqual(text.count("Worth noting:"), 1)
        self.assertIn("85.2%", text)
        self.assertLess(text.count("\n\n"), 8)
        self.assertIn("Data through", text)
        self.assertNotIn("than kolkata", text.casefold())
        self.assertNotIn("EBITDA", text)

    def test_ops_still_cannot_see_profit(self):
        answer = answer_from_data("What's each company's profit this month?", self.data, False)
        self.assertNotIn("EBITDA", answer["text"])
        self.assertNotIn("15L", answer["text"])
        self.assertNotIn("**So what**", answer["text"])
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

    def test_the_prompt_asks_for_a_partner_and_keeps_the_guardrails(self):
        self.assertIn("senior partner", _SYSTEM)
        self.assertIn("McKinsey", _SYSTEM)
        self.assertIn("**So what.**", _SYSTEM)
        self.assertIn("**Non-obvious insight.**", _SYSTEM)
        self.assertIn("Worth noting:", _SYSTEM)
        self.assertIn("Hypothesis", _SYSTEM)
        self.assertNotIn("150 words", _SYSTEM)
        self.assertNotIn("250 to 450", _SYSTEM)
        self.assertIn("Never invent a number", _SYSTEM)
        self.assertIn("Finance, HR, and the inbox", _SYSTEM)
        self.assertIn("Tally", _SYSTEM)
        self.assertIn("Anup", _SYSTEM)
        self.assertIn("Vikas", _SYSTEM)
        self.assertIn("Sanjoy", _SYSTEM)
        self.assertNotIn("Sanjoy / Anup / Vikas", _SYSTEM)
        self.assertIn("Shilajit", _SYSTEM)
        self.assertIn("Navratri", _SYSTEM)
        self.assertIn("Chhath", _SYSTEM)
        self.assertIn("Posist Insights", _SYSTEM)
        self.assertIn("Rent above 25%", _SYSTEM)
        self.assertIn("bill count", _SYSTEM)
        self.assertIn("Rosedale", _SYSTEM)
        self.assertIn("Faridabad", _SYSTEM)
        self.assertIn("Chattarpur", _SYSTEM)
        self.assertIn("GK1", _SYSTEM)
        self.assertIn("Manisquare", _SYSTEM)
        self.assertIn("24.78%", _SYSTEM)
        self.assertIn("own baseline", _SYSTEM)

    def test_mock_output_follows_the_partner_shape(self):
        os.environ["CHAT_MOCK"] = "1"
        os.environ.pop("CHAT_API_KEY", None)
        try:
            result = produce_answer("how did sales do last week", self.data, False)
        finally:
            os.environ.pop("CHAT_MOCK", None)
        self.assertEqual(result["fallback"], "mock")
        self.assertTrue(result["text"].startswith("Mock answer."))
        self.assertIn("**So what**", result["text"])
        self.assertIn("**Moves**", result["text"])
        self.assertIn("**Non-obvious insight.**", result["text"])
        self.assertIn("Owner: Anup", result["text"])
        self.assertIn("Owner: Vikas", result["text"])
        self.assertNotIn("Sanjoy / Anup / Vikas", result["text"])
        self.assertIn("Timeframe:", result["text"])


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
            "**So what.** North pace is 79.9%. A gap of ₹9,99,999 is not real.",
            "",
            "**Moves**",
            "1. Check the North stores behind 79.9% pace. Value: not sized. Owner: Sanjoy / Anup / Vikas. Timeframe: this week.",
            "```chart",
            '{"type":"bar","title":"Pace","unit":"%","series":[{"label":"North","value":79.9},{"label":"Made up","value":8675309}]}',
            "```",
        ])

        def client(messages, model):
            self.assertIn("**So what.**", messages[0]["content"])
            self.assertIn("senior partner", messages[0]["content"])
            self.assertIn("Per-store daily gross", messages[-1]["content"])
            return reply, None

        result = produce_answer("why is North behind target", self.data, False, client=client)
        self.assertIn("**So what.**", result["text"])
        self.assertIn("**Moves**", result["text"])
        self.assertIn("79.9%", result["text"])
        self.assertNotIn("9,99,999", result["text"])
        self.assertNotIn("999999", result["text"])
        self.assertIn("not in the file", result["text"])
        self.assertIsNone(result["chart"])
        self.assertIsNone(result["fallback"])


if __name__ == "__main__":
    unittest.main()
