"""Month lookup and missing-month wording for the April 2026 history window."""

import csv
import json
import unittest
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from app.chat.answer import produce_answer
from app.chat.context import build_context
from app.chat.facts import answer_from_data
from app.chat.history import coverage_line, lookup, missing_text, month_loaded, use_file_answer
from app.chat.month_sales import _lakh, answer as month_sales_answer
from app.chat.router import dispatch, tool_specs
from app.chat.snapshot import reset_snapshot, view_for

_ROOT = Path(__file__).resolve().parents[1]
_AGG = _ROOT / "data" / "history" / "aggregator_store_month.csv"
_SALES_12 = _ROOT / "data" / "posist" / "daily_sales" / "sales_2026-11-12.csv"


def _sep_aggregator_from_file():
    """Independent sums from the mapped aggregator CSV. Faridabad is already out."""
    totals = defaultdict(lambda: {"sales": Decimal(0), "orders": Decimal(0), "n": 0})
    with _AGG.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if raw.get("month") != "2026-09":
                continue
            if "faridabad" in (raw.get("store") or "").casefold() or "faridabad" in (raw.get("workbook_name") or "").casefold():
                raise AssertionError("Faridabad must not be in aggregator_store_month.csv")
            platform = raw.get("platform") or ""
            region = raw.get("region") or ""
            if raw.get("net_sales"):
                sales = Decimal(str(raw["net_sales"]))
                totals[platform]["sales"] += sales
                totals[platform + "|" + region]["sales"] += sales
            if raw.get("orders"):
                totals[platform]["orders"] += Decimal(str(raw["orders"]))
            totals[platform]["n"] += 1
    return totals


def _ideal_plaza_12_nov():
    with _SALES_12.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if "ideal plaza" in (raw.get("store") or "").casefold():
                return float(raw["gross"]), float(raw["bills"])
    raise AssertionError("Ideal Plaza is not in the 12 Nov sales file")


class MissingMonthTests(unittest.TestCase):
    def test_june_kolkata_sales_says_not_loaded_and_names_alfred(self):
        question = "Kolkata sales in June 2026"
        self.assertTrue(use_file_answer(question, "ops"))
        text = lookup(question, "ops")
        self.assertIn("June 2026", text)
        self.assertIn("not in the loaded daily files", text)
        self.assertIn("Alfred", text)
        self.assertIn("No figure is invented", text)
        self.assertNotIn("₹", text)
        self.assertNotIn("Lakh", text)
        self.assertNotIn("estimate", text.casefold())
        # The same wording is what the Wizard would return offline.
        reset_snapshot()
        answer = answer_from_data(question, view_for(role="ops"), False)
        self.assertEqual(answer["text"], text)

    def test_may_menu_mix_names_jarvis(self):
        text = lookup("menu mix in May 2026", "ops")
        self.assertIn("May 2026", text)
        self.assertIn("not loaded yet", text)
        self.assertIn("Jarvis", text)
        self.assertIn("No figure is invented", text)
        self.assertNotIn("₹", text)

    def test_october_finance_names_shilajit_and_is_hidden_from_ops(self):
        text = lookup("Grand Economics in October 2026", "owner")
        self.assertIn("October 2026", text)
        self.assertIn("not loaded yet", text)
        self.assertIn("Shilajit", text)
        self.assertIn("No figure is invented", text)
        self.assertNotIn("₹", text)
        hidden = lookup("Grand Economics in October 2026", "ops")
        self.assertIn("not included for this role", hidden.casefold())
        self.assertNotIn("Shilajit", hidden)

    def test_model_cannot_rewrite_a_missing_month(self):
        def fake_client(messages, model):
            return ("June 2026 Kolkata sales were about ₹2.5Cr, estimated from October.", None)

        reset_snapshot()
        result = produce_answer(
            "Kolkata sales in June 2026",
            view_for(role="ops"),
            False,
            client=fake_client,
        )
        self.assertIn("Alfred", result["text"])
        self.assertIn("not in the loaded daily files", result["text"])
        self.assertIn("No figure is invented", result["text"])
        self.assertNotIn("2.5", result["text"])
        self.assertNotIn("estimated", result["text"])
        self.assertIsNone(result.get("fallback"))


class AggregatorLookupTests(unittest.TestCase):
    def test_swiggy_vs_zomato_september_uses_the_aggregator_file(self):
        expected = _sep_aggregator_from_file()
        self.assertEqual(expected["Zomato"]["n"], 25)
        self.assertEqual(expected["Swiggy"]["n"], 25)
        question = "Swiggy vs Zomato in Sep"
        self.assertTrue(use_file_answer(question, "ops"))
        text = lookup(question, "ops")
        self.assertIn("September 2026", text)
        self.assertIn("Sanjoy", text)
        self.assertIn("Faridabad Sector 15 is left out", text)
        self.assertIn(_lakh(expected["Zomato"]["sales"]), text)
        self.assertIn(_lakh(expected["Swiggy"]["sales"]), text)
        self.assertIn(_lakh(expected["Zomato|Kolkata"]["sales"]), text)
        self.assertIn(_lakh(expected["Swiggy|Kolkata"]["sales"]), text)
        self.assertIn(_lakh(expected["Zomato|Delhi NCR"]["sales"]), text)
        self.assertIn(_lakh(expected["Swiggy|Delhi NCR"]["sales"]), text)
        self.assertIn(str(int(expected["Zomato"]["orders"])), text)
        self.assertIn(str(int(expected["Swiggy"]["orders"])), text)
        self.assertIn("impressions, ads and refunds are blank", text)
        self.assertIn("Belur", text)
        reset_snapshot()
        answer = answer_from_data(question, view_for(role="ops"), False)
        self.assertEqual(answer["text"], text)


class MonthLookupToolTests(unittest.TestCase):
    def test_tool_is_visible_to_ops_and_answers_a_missing_month(self):
        names = [spec["function"]["name"] for spec in tool_specs("ops")]
        self.assertIn("month_lookup", names)
        self.assertNotIn("finance", names)
        self.assertNotIn("tally", names)
        result = dispatch("month_lookup", {"question": "Kolkata sales in June 2026"}, "ops")
        self.assertIn("Alfred", result["text"])
        self.assertIn("not in the loaded daily files", result["text"])

    def test_tool_accepts_month_and_domain_arguments(self):
        result = dispatch(
            "month_lookup",
            {"question": "", "month": "2026-06", "domain": "sales"},
            "ops",
        )
        self.assertEqual(result["text"], missing_text("sales", 2026, 6))

    def test_ops_cannot_look_up_hr(self):
        result = dispatch(
            "month_lookup",
            {"question": "headcount in April 2026", "month": "2026-04", "domain": "hr"},
            "ops",
        )
        self.assertIn("not included for this role", result["text"])
        self.assertNotRegex(result["text"], r"₹")


class SnapshotOverlayTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.ops = view_for(role="ops")
        self.windows = self.ops["sales_windows"]

    def test_store_tables_run_through_12_nov_and_match_the_overlay(self):
        self.assertEqual(self.windows["latest"], "2026-11-12")
        self.assertEqual(self.windows["week_start"], "2026-11-06")
        self.assertEqual(self.windows["month_start"], "2026-11-01")
        names = " ".join(row["store"].casefold() for row in self.windows["latest_rows"])
        self.assertNotIn("faridabad", names)
        self.assertNotIn("chattarpur", names)
        self.assertNotIn("gk1", names)
        self.assertNotIn("gk 1", names)
        ideal = next(row for row in self.windows["latest_rows"] if "ideal plaza" in row["store"].casefold())
        gross, bills = _ideal_plaza_12_nov()
        self.assertEqual(ideal["gross"], gross)
        self.assertEqual(ideal["bills"], bills)

    def test_october_calendar_month_is_unchanged(self):
        answer = answer_from_data("total october sales in Kolkata", self.ops, False)
        self.assertIn("₹316.53L", answer["text"])
        self.assertIn("1–31 Oct", answer["text"])
        self.assertEqual(answer["as_of"], "31 Oct 2026")


class CoverageAndRoleTests(unittest.TestCase):
    def test_coverage_line_is_compact_and_role_gated(self):
        ops = coverage_line("ops")
        owner = coverage_line("owner")
        self.assertIn("History coverage", ops)
        self.assertIn("Never estimate", ops)
        self.assertIn("Alfred", ops)
        self.assertIn("Sanjoy", ops)
        self.assertNotIn("Shilajit", ops)
        self.assertNotIn("the Accountant", ops)
        self.assertNotIn("the HR Bot", ops)
        self.assertIn("Shilajit", owner)
        self.assertIn("the Accountant", owner)
        self.assertIn("the HR Bot", owner)
        # One compact block, not a dump of monthly tables.
        self.assertLess(len(ops), 2500)
        self.assertLess(len(owner), 3500)

    def test_prompt_with_coverage_stays_under_the_token_cap(self):
        reset_snapshot()
        text = build_context(
            "Why is Kalkaji down, and what is the menu mix, vendors, Grand Economics, and licences?",
            view_for(role="owner"),
        )
        self.assertIn("History coverage", text)
        self.assertLessEqual(len(text) / 4, 12000)
        self.assertNotIn("[truncated", text)

    def test_hr_history_has_no_names(self):
        path = _ROOT / "data" / "history" / "hr_month.csv"
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fields = [name.casefold() for name in (reader.fieldnames or [])]
            for banned in ("name", "employee", "email", "phone", "employee_id"):
                self.assertTrue(all(banned not in field for field in fields), fields)
            blob = " ".join(" ".join(row.values()) for row in reader)
        # The note mentions "No names" and must not include a person.
        self.assertIn("No names", path.read_text(encoding="utf-8"))
        self.assertNotIn("@", blob)

    def test_april_procurement_is_loaded_from_the_backfill(self):
        # April 2026 purchases and prices come from the Entry Report / Purchase
        # Summary backfill, not from Logan as a missing month.
        text = lookup("procurement purchases in April 2026", "ops")
        self.assertIsNotNone(text)
        self.assertNotIn("not loaded", text.casefold())
        self.assertNotIn("would come from Logan", text)
        self.assertIn("April 2026", text)
        self.assertIn("Purchases:", text)
        # Delhi + Kolkata item totals from the April Entry Reports (tax inclusive).
        # 6,155,843.94 + 5,916,913.90 = 12,072,757.84 = ₹120.73L
        self.assertIn("₹120.73L", text)
        self.assertIn("Zomato Hyperpure Delhi", text)
        self.assertTrue(month_loaded("procurement", 2026, 4, "ops"))
        # Prices for April come from the official Purchase Summary, marked complete.
        prices = lookup("ingredient prices in April 2026", "ops")
        self.assertIn("complete", prices)
        self.assertIn("Purchase Summary", prices)
        # Coverage lists April as loaded.
        cov = coverage_line("ops")
        self.assertIn("loaded Apr 2026", cov)
        self.assertIn("1 Apr 2026", cov)
        # A day with no invoice is not invented as zero; June 1 Delhi has no entry.
        with ( _ROOT / "data" / "history" / "purchases_item_month.csv").open(newline="", encoding="utf-8-sig") as handle:
            months = {row["month"] for row in csv.DictReader(handle)}
        self.assertGreaterEqual(months, {"2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"})
        # Parse notes: zero issues, item vs summary gaps within 0.02.
        notes_path = _ROOT / "data" / "history" / "procurement_parse_notes.json"
        self.assertTrue(notes_path.is_file())
        notes = json.loads(notes_path.read_text(encoding="utf-8"))
        self.assertEqual(notes.get("issues") or notes.get("parse_issues") or [], [])

    def test_april_sales_match_alfred_and_june_is_still_missing(self):
        # Alfred: 866 store-days, 30 stores, gross 4,81,10,428.87, bills 92,784. Net blank.
        reset_snapshot()
        calendar = month_sales_answer("total april sales", view_for(role="ops"), False)
        text = calendar["text"]
        self.assertIn("₹481.10L", text)
        self.assertIn("92,784", text)
        self.assertIn("Kolkata ₹234.85L", text)
        self.assertIn("NCR ₹245.73L", text)
        self.assertIn("Events & Catering ₹0.52L", text)
        self.assertIn("outside store comparisons", text)
        self.assertIn("Faridabad is included", text)
        self.assertIn("net is not loaded", text.casefold())
        self.assertNotIn("Network net was ₹0", text)
        # City calendar answer, Food Truck gaps, mall bills as em dash, Events out of Kolkata.
        kol = month_sales_answer("Kolkata sales in April 2026", view_for(role="ops"), False)["text"]
        self.assertIn("₹234.85L", kol)
        self.assertIn("44,403", kol)
        self.assertIn("Manisquare ₹12.43L", kol)
        self.assertIn("Forum ₹6.79L", kol)
        self.assertIn("missing 11, 12, 13, 14, 25, 26 Apr", kol)
        self.assertIn("Food Truck", kol)
        self.assertNotIn("Events", kol)
        self.assertIn("| —", kol)  # mall bills
        ncr = month_sales_answer("NCR sales in April 2026", view_for(role="ops"), False)["text"]
        self.assertIn("₹245.73L", ncr)
        self.assertIn("Faridabad", ncr)
        self.assertIn("46,253", ncr)
        # Channel split and month lookup.
        channel = lookup("channel split in April 2026", "ops")
        self.assertIn("DINEIN: ₹301.27L", channel)
        self.assertIn("ZOMATOONLINE: ₹106.43L", channel)
        self.assertIn("SWIGGYONLINE: ₹60.69L", channel)
        self.assertIn("TAKEOUT: ₹12.71L", channel)
        self.assertIn("ONDC: ₹0.01L", channel)
        # Net cells stay blank: no invented zero net in the store file.
        with (_ROOT / "data" / "history" / "sales_store_month.csv").open(newline="", encoding="utf-8-sig") as handle:
            april = [row for row in csv.DictReader(handle) if row["month"] == "2026-04"]
        self.assertTrue(all(row.get("net") == "" for row in april), "net must stay blank")
        self.assertEqual(len(april), 30)
        gross = sum(Decimal(row["gross"]) for row in april)
        bills = sum(Decimal(row["bills"] or 0) for row in april)
        self.assertEqual(gross, Decimal("48110428.87"))
        self.assertEqual(bills, Decimal("92784"))
        # June is still not loaded.
        june = lookup("Kolkata sales in June 2026", "ops")
        self.assertIn("not in the loaded daily files", june)
        self.assertIn("Alfred", june)
        self.assertNotIn("₹", june)
        self.assertTrue(use_file_answer("Kolkata sales in June 2026", "ops"))
        # October Kolkata is unchanged.
        october = month_sales_answer("total october sales in Kolkata", view_for(role="ops"), False)["text"]
        self.assertIn("₹316.53L", october)
        self.assertIn("1–31 Oct 2026", october)
        # Coverage owners.
        cov = coverage_line("ops")
        self.assertIn("Procurement purchases and ingredient prices (Procurement)", cov)
        self.assertIn("Reelo monthly customers, orders and spend (Logan)", cov)
        self.assertNotIn("purchases and ingredient prices (Logan)", cov)
        self.assertNotIn("Reelo monthly customers, orders and spend (Jarvis)", cov)

    def test_april_wastage_is_loaded_and_september_is_partial(self):
        text = lookup("wastage in April 2026", "ops")
        self.assertIsNotNone(text)
        self.assertNotIn("not loaded", text.casefold())
        self.assertIn("April 2026 wastage", text)
        self.assertIn("Total wastage:", text)
        self.assertIn("Warehouse", text)
        self.assertIn("Base Kitchen", text)
        # Pacific mall comma-split rows were joined.
        self.assertIn("Pacific mall, Jasola", text)
        self.assertTrue(month_loaded("wastage", 2026, 4, "ops"))
        self.assertTrue(month_loaded("wastage", 2026, 9, "ops"))
        sep = lookup("wastage in September 2026", "ops")
        self.assertIn("2026-09-01 to 2026-09-08", sep)
        self.assertIn("not a full calendar month", sep)
        self.assertIn("incomplete", sep.casefold())
        # October wastage is not loaded; it would come from Procurement.
        oct_w = lookup("wastage in October 2026", "ops")
        self.assertIn("not loaded", oct_w.casefold())
        self.assertIn("Procurement", oct_w)
        self.assertNotIn("Logan", oct_w)
        self.assertNotIn("₹", oct_w)
        # Consumption reports were not loaded as a domain.
        self.assertFalse(month_loaded("consumption", 2026, 4, "ops"))


if __name__ == "__main__":
    unittest.main()
