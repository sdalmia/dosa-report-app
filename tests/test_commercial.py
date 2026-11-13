"""Delivery commission, food-cost basis, and licence status."""

import unittest
from datetime import date

from app.chat.facts import answer_from_data
from app.chat.licences import load, packet, status_on
from app.chat.snapshot import reset_snapshot, snapshot, view_for
from app.commercial import (
    AGGREGATOR_COMMISSION_PCT,
    GST_ON_COMMISSION_PCT,
    channel_contribution,
    effective_commission_pct,
    split_delivery_net,
)


class FoodContextTests(unittest.TestCase):
    def test_ideal_plaza_context_uses_raw_plus_semi(self):
        from app.chat.context import build_context

        reset_snapshot()
        text = build_context("What is Ideal Plaza food cost?", view_for(role="ops"))
        self.assertIn("raw + semi-processed", text)
        self.assertIn("18.1%", text)
        self.assertIn("24.3%", text)
        self.assertIn("Packaging", text)


class CommissionTests(unittest.TestCase):
    def test_effective_rate_is_24_78_percent_of_net(self):
        self.assertEqual(AGGREGATOR_COMMISSION_PCT, 21)
        self.assertEqual(GST_ON_COMMISSION_PCT, 18)
        self.assertEqual(f"{effective_commission_pct():.2f}", "24.78")
        take = split_delivery_net(100)
        self.assertAlmostEqual(take["drag"], 24.78)
        self.assertAlmostEqual(take["realisation"], 75.22)
        self.assertIsNone(split_delivery_net(None))
        held = channel_contribution(100, food=None, packaging=10)
        self.assertIn("food cost", held["missing"])
        self.assertNotIn("packaging", held["missing"])
        self.assertAlmostEqual(held["contribution"], 65.22)

    def test_a_delivery_question_states_the_basis_and_skips_dine_in(self):
        reset_snapshot()
        answer = answer_from_data(
            "What commission do Swiggy and Zomato take, and what is left on a ₹500 net bill?",
            snapshot(),
            False,
        )
        text = answer["text"]
        self.assertIn("24.78%", text)
        self.assertIn("not applied to dine-in or takeaway", text)
        self.assertIn("No Swiggy or Zomato payout", text)
        self.assertIn("₹105.00", text)
        self.assertIn("₹376.10", text)
        self.assertIn("not applied to gross", text)
        self.assertNotIn("Famepilot", text)

    def test_ticket_questions_stay_on_tickets(self):
        reset_snapshot()
        answer = answer_from_data(
            "How do the Famepilot tickets split between Zomato and Swiggy?",
            snapshot(),
            False,
        )
        self.assertIn("tickets", answer["text"].casefold())
        self.assertNotIn("24.78%", answer["text"])


class LicenceTests(unittest.TestCase):
    def test_status_is_recomputed_from_expiry(self):
        as_of = date(2026, 11, 13)
        self.assertEqual(status_on(date(2026, 11, 12), "valid", as_of), "expired")
        self.assertEqual(status_on(date(2026, 12, 4), "valid", as_of), "expiring_30d")
        self.assertEqual(status_on(date(2027, 2, 16), "unknown", as_of), "valid")
        self.assertEqual(status_on(None, "missing", as_of), "missing")
        rows = load(as_of)
        self.assertGreaterEqual(len(rows), 200)
        self.assertFalse(any("faridabad" in row["store"].casefold() for row in rows))
        self.assertFalse(any("chattarpur" in row["store"].casefold() for row in rows))
        sec = [row for row in rows if row["store"] == "Sec 143 Noida" and row["licence_type"] == "fssai"]
        self.assertEqual(sec[0]["status"], "expired")
        body = packet("Which licences expire in the next 30 days?", "ops", as_of)
        self.assertIn("Ideal Plaza", body)
        self.assertIn("Sec 143 Noida", body)
        self.assertIn("dated NCR tracker is pending", body)
        self.assertNotIn(sec[0]["licence_no"], body)
        numbered = packet("What is the FSSAI licence number for Sec 143 Noida?", "ops", as_of)
        self.assertIn(sec[0]["licence_no"], numbered)

    def test_finance_does_not_receive_licence_rows(self):
        reset_snapshot()
        finance = view_for(role="finance")
        answer = answer_from_data("Which licences expire in the next 30 days?", finance, False)
        self.assertIn("not included", answer["text"].casefold())
        self.assertNotIn("Ideal Plaza", answer["text"])


if __name__ == "__main__":
    unittest.main()
