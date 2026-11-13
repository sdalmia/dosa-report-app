"""Calendar-month sales, checked against posist_daily.csv and Insights notes."""

import csv
import re
import unittest
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.chat.answer import produce_answer
from app.chat.context import build_context
from app.chat.facts import answer_from_data
from app.chat.month_sales import relevant
from app.chat.snapshot import reset_snapshot, view_for
from app.food_courts import is_mall_food_court
from app.store_health.day_notes import FARIDABAD_CLOSED_FROM

_ROOT = Path(__file__).resolve().parents[1]
_POSIST = _ROOT / "data" / "store_health" / "posist_daily.csv"
_INSIGHTS = _ROOT / "data" / "posist" / "sales_pred_vs_actual.csv"
_CLOSED = ("chattarpur", "gk1", "gk 1")


def _day(value):
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _num(value):
    text = str(value or "").strip().replace(",", "")
    return float(text) if text else 0.0


def _lakh(rupees):
    return f"₹{float(rupees) / 100000:.2f}L"


def october_kolkata_from_file():
    """Sum 1–31 Oct 2026 from posist_daily.csv only. Independent of the answer code."""
    start, end = date(2026, 10, 1), date(2026, 10, 31)
    stores = {}
    with _POSIST.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            day = _day(raw["date"])
            if day < start or day > end:
                continue
            name = (raw.get("store") or "").strip()
            folded = name.casefold()
            if any(token in folded for token in _CLOSED):
                continue
            if "faridabad" in folded and day >= FARIDABAD_CLOSED_FROM:
                continue
            if (raw.get("region") or "").strip() != "East":
                continue
            bucket = stores.setdefault(name, {"gross": 0.0, "bills": 0.0, "days": set(), "mall": is_mall_food_court(name)})
            bucket["gross"] += _num(raw.get("gross"))
            bucket["bills"] += _num(raw.get("bills"))
            bucket["days"].add(day)
    gross = sum(row["gross"] for row in stores.values())
    mall = sum(row["gross"] for row in stores.values() if row["mall"])
    bills_ex = sum(row["bills"] for row in stores.values() if not row["mall"])
    return {
        "gross": gross,
        "mall": mall,
        "bills_ex": bills_ex,
        "stores": stores,
        "days": monthrange(2026, 10)[1],
    }


def october_east_net_from_file():
    """Sum East net for 2–31 Oct from Posist Insights notes. 1 Oct is not on the file."""
    pattern = re.compile(r"East ₹([0-9.]+)L \+ North ₹([0-9.]+)L")
    total = Decimal(0)
    days = []
    with _INSIGHTS.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            day = _day(raw["date"])
            if day.year != 2026 or day.month != 10:
                continue
            match = pattern.search(raw.get("notes") or "")
            if not match:
                continue
            total += Decimal(match.group(1)) * Decimal(100000)
            days.append(day)
    return float(total), sorted(days)


class MonthSalesTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.ops = view_for(role="ops")
        self.file = october_kolkata_from_file()

    def test_file_has_all_31_october_days_for_kolkata(self):
        self.assertGreater(self.file["gross"], 0)
        self.assertEqual(self.file["days"], 31)
        # Every East store except the food truck has 31 days.
        thin = [name for name, row in self.file["stores"].items() if len(row["days"]) != 31]
        self.assertTrue(all("food truck" in name.casefold() for name in thin))
        self.assertGreater(self.file["mall"], 0)
        self.assertLess(self.file["mall"], self.file["gross"])

    def test_kolkata_october_uses_the_calendar_month_and_includes_mall_sales(self):
        expected = _lakh(self.file["gross"])
        for question in (
            "What is the total october sale for Kolkata",
            "total october sales in Kolkata",
            "You need to check sales again for kolkata in october",
        ):
            answer = answer_from_data(question, self.ops, False)
            text = answer["text"]
            self.assertIn(expected, text, question)
            self.assertIn("1–31 Oct", text, question)
            self.assertIn("October 2026", text, question)
            self.assertEqual(answer["as_of"], "31 Oct 2026")
            self.assertIn("Manisquare", text, question)
            self.assertIn("Forum", text, question)
            manisquare = next(row for name, row in self.file["stores"].items() if "manisquare" in name.casefold())
            forum = next(row for name, row in self.file["stores"].items() if "forum" in name.casefold() and "rangoli" not in name.casefold())
            self.assertIn(_lakh(manisquare["gross"]), text, question)
            self.assertIn(_lakh(forum["gross"]), text, question)
            self.assertIn("sales are counted", text.casefold(), question)
            # The wrong live answer used November 1–8 and a ₹54.03L headline.
            self.assertNotIn("54.03", text, question)
            self.assertNotIn("8 Nov", text, question)
            self.assertNotIn("9.85", text, question)
            # Excluding mall sales would understate the city total.
            self.assertNotIn(_lakh(self.file["gross"] - self.file["mall"]), text, question)
            # Ideal Plaza's October figure, not its 1–8 Nov figure.
            ideal = next(row for name, row in self.file["stores"].items() if "ideal plaza" in name.casefold())
            self.assertIn(_lakh(ideal["gross"]), text, question)
            self.assertIsNotNone(answer.get("table"))
            self.assertIsNotNone(answer.get("chart"))

    def test_october_sales_without_a_city_reports_both_cities(self):
        answer = answer_from_data("October sales", self.ops, False)
        text = answer["text"]
        self.assertIn(_lakh(self.file["gross"]), text)
        self.assertIn("Kolkata", text)
        self.assertIn("NCR", text)
        self.assertIn("1–31 Oct", text)
        self.assertNotIn("54.03", text)
        self.assertNotIn("8 Nov", text)

    def test_east_net_is_2_to_31_oct_and_does_not_invent_1_oct(self):
        net, days = october_east_net_from_file()
        self.assertEqual(days[0], date(2026, 10, 2))
        self.assertEqual(days[-1], date(2026, 10, 31))
        self.assertNotIn(date(2026, 10, 1), days)
        answer = answer_from_data("What is the total october sale for Kolkata", self.ops, False)
        self.assertIn(_lakh(net), answer["text"])
        self.assertIn("1 Oct net is not loaded", answer["text"])
        self.assertIn("full-month net is not stated", answer["text"])
        self.assertIn("24.78%", answer["text"])

    def test_context_gives_the_model_the_october_calendar_table(self):
        context = build_context("total october sales in Kolkata", self.ops)
        self.assertIn(_lakh(self.file["gross"]), context)
        self.assertIn("1–31 Oct", context)
        self.assertIn("Calendar-month sales", context)
        self.assertIn("do not relabel November figures as October", context)
        self.assertIn("Manisquare", context)
        ideal = next(row for name, row in self.file["stores"].items() if "ideal plaza" in name.casefold())
        self.assertIn(_lakh(ideal["gross"]), context)
        # Token cap already tested elsewhere; this packet must stay in the untruncated front.
        self.assertNotIn("[truncated", context)

    def test_model_cannot_rewrite_october_totals(self):
        def fake_client(messages, model):
            return (
                "Total October sales are not directly listed. "
                "October month-to-date sales (up to 8 Nov 2026) are ₹54.03L gross, "
                "excluding mall bulk stores. Ideal Plaza ₹9.85L.",
                None,
            )

        result = produce_answer(
            "total october sales in Kolkata",
            self.ops,
            False,
            client=fake_client,
        )
        self.assertIn(_lakh(self.file["gross"]), result["text"])
        self.assertIn("1–31 Oct", result["text"])
        self.assertNotIn("54.03", result["text"])
        self.assertNotIn("8 Nov", result["text"])
        self.assertNotIn("9.85", result["text"])
        self.assertIsNone(result.get("fallback"))

    def test_audit_and_tally_questions_are_not_taken_over(self):
        self.assertFalse(relevant("Which stores scored lowest in the October mystery audit?"))
        self.assertFalse(relevant("Top 10 payments in Kolkata in October"))
        self.assertFalse(relevant(
            "What is should be my purchase budget for the month of october in kolkata, "
            "keeping in mind my average closing inventory to be 5-7% of the sales"
        ))
        # Existing pace answer for this month is unchanged.
        pace = answer_from_data("How are we tracking against this month's target?", self.ops, False)
        self.assertIn("84.3%", pace["text"])
        self.assertEqual(pace["as_of"], "12 Nov 2026")

    def test_prompt_with_month_sales_stays_under_the_token_cap(self):
        text = build_context(
            "Why is Kalkaji down, and what is the menu mix, vendors, Grand Economics, and licences?",
            view_for(role="owner"),
        )
        self.assertLessEqual(len(text) / 4, 12000)


if __name__ == "__main__":
    unittest.main()
