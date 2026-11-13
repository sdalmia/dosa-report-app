"""Location, brands, prices, gaps, training, Reelo, and Posist channels."""

import unittest

from app.chat.facts import answer_from_data
from app.chat.snapshot import reset_snapshot, view_for


class WizardGroupBTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.ops = view_for(role="ops")

    def test_delhi_candidates_keep_the_finder_score_scale(self):
        answer = answer_from_data("Where should I open next in Delhi?", self.ops, False)
        self.assertIn("out of 10", answer["text"])
        self.assertIn("9.3", answer["text"])
        self.assertIn("not a score out of 10", answer["text"])
        self.assertNotIn("airport concession", answer["text"].casefold())

    def test_ops_gaps_hide_accountant_rows(self):
        ops = answer_from_data("What data are we missing?", self.ops, False)
        self.assertIn("Tony", ops["text"])
        self.assertNotIn("Tally", ops["text"])
        owner = answer_from_data("What data are we missing?", view_for(role="owner"), True)
        self.assertIn("Tony", owner["text"])

    def test_reelo_names_the_stores_that_are_not_covered(self):
        answer = answer_from_data("Which stores are not on Reelo?", self.ops, False)
        self.assertIn("Manisquare", answer["text"])
        self.assertIn("not shown as zero", answer["text"])
        self.assertIn("366540", answer["text"].replace(",", ""))
        self.assertIn("NPS is not in Reelo", answer["text"])
        self.assertNotIn("Faridabad", answer["text"])

    def test_paneer_price_move_stays_on_each_city(self):
        answer = answer_from_data("How has paneer moved?", self.ops, False)
        self.assertIn("own last month", answer["text"].casefold())
        self.assertIn("3-month change is not stated", answer["text"])
        self.assertNotIn("than kolkata", answer["text"].casefold())


if __name__ == "__main__":
    unittest.main()
