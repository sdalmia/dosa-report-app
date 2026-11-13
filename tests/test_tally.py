"""Tally day book answers stay on the owner and finance roles."""

import unittest

from app.chat.facts import answer_from_data
from app.chat.snapshot import reset_snapshot, view_for
from app.chat.suggestions import TALLY


class TallyTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()

    def test_ops_does_not_see_delhi_payments(self):
        answer = answer_from_data("What did we pay in Delhi on 2 Nov?", view_for(role="ops"), False)
        self.assertIn("not included", answer["text"].casefold())
        self.assertNotIn("1,644,116", answer["text"])
        self.assertNotIn("Mandi Fresh", answer["text"])

    def test_delhi_2_nov_payments_match_the_file(self):
        answer = answer_from_data("What did we pay in Delhi on 2 Nov?", view_for(role="owner"), True)
        self.assertIn("₹1,644,116.52", answer["text"])
        self.assertIn("Mandi Fresh", answer["text"])
        self.assertIn("Nothing after", answer["text"])
        self.assertIn("missing, not zero", answer["text"])
        self.assertIsNotNone(answer["table"])
        self.assertLessEqual(len(answer["table"]["rows"]), 10)

    def test_kolkata_october_top_payment_is_the_epf_line(self):
        answer = answer_from_data("Top 10 payments in Kolkata in October", view_for(role="finance"), False)
        self.assertIn("₹1,337,943.00", answer["text"])
        self.assertIn("EPF", answer["text"])
        self.assertEqual(len(answer["table"]["rows"]), 10)

    def test_a_missing_day_is_not_filled_with_zero(self):
        answer = answer_from_data("What did we pay in Delhi on 6 Nov?", view_for(role="owner"), True)
        self.assertIn("no day book rows", answer["text"].casefold())
        self.assertNotIn("₹0", answer["text"])

    def test_preview_questions_are_the_two_samples(self):
        self.assertEqual(TALLY[0], "What did we pay in Delhi on 2 Nov?")
        self.assertIn("Kolkata", TALLY[1])


if __name__ == "__main__":
    unittest.main()
