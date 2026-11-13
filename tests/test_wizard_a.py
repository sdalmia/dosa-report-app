"""Finance, procurement, Posist fixes, growth, trends, and the calendar."""

import unittest

from app.chat.context import build_context
from app.chat.facts import answer_from_data
from app.chat.router import dispatch, tool_specs
from app.chat.snapshot import reset_snapshot, view_for


class WizardGroupATests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()

    def test_ops_does_not_receive_grand_economics_lines(self):
        ops = view_for(role="ops")
        answer = answer_from_data("Show Grand Economics rent and EBITDA by city", ops, False)
        self.assertIn("not included", answer["text"].casefold())
        self.assertNotIn("fnb_cost", answer["text"])
        owner = answer_from_data("Show Grand Economics rent and EBITDA by city", view_for(role="owner"), True)
        self.assertIn("ebitda", owner["text"])
        self.assertIn("October 2026 is not in this file", owner["text"])

    def test_posist_fixes_lead_with_the_file_and_note_delhi(self):
        answer = answer_from_data("What can we fix on Posist?", view_for(role="ops"), False)
        self.assertIn("Quest Mall", answer["text"])
        self.assertIn("Delhi recipe variance is not covered", answer["text"])
        self.assertIn("Coconut", answer["text"])

    def test_growth_states_the_assumption_and_a_real_gap(self):
        answer = answer_from_data("How do we increase sales?", view_for(role="ops"), False)
        self.assertIn("Assumption", answer["text"])
        self.assertIn("₹", answer["text"])
        self.assertIn("not a forecast", answer["text"])

    def test_kalkaji_weekend_uses_the_calendar_file(self):
        answer = answer_from_data("What's predicted for Kalkaji this weekend?", view_for(role="ops"), False)
        self.assertIn("Kalkaji", answer["text"])
        self.assertIn("58823", answer["text"].replace(",", "").replace("₹", ""))
        self.assertIsNotNone(answer.get("calendar"))
        self.assertTrue(answer["calendar"]["days"])

    def test_prompt_stays_under_the_token_cap(self):
        text = build_context(
            "Why is Kalkaji down, and what is the menu mix, vendors, Grand Economics, and licences?",
            view_for(role="owner"),
        )
        self.assertLessEqual(len(text) / 4, 12000)

    def test_finance_tool_is_hidden_from_ops(self):
        self.assertNotIn("finance", [spec["function"]["name"] for spec in tool_specs("ops")])
        self.assertIn("finance", [spec["function"]["name"] for spec in tool_specs("finance")])
        hidden = dispatch("finance", {"question": "EBITDA"}, "ops")
        self.assertIn("cannot", hidden["error"])


if __name__ == "__main__":
    unittest.main()
