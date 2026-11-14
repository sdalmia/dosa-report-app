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
    def test_june_menu_mix_says_not_loaded_and_names_jarvis(self):
        # June sales is now loaded; menu mix for June is still pending from Jarvis.
        question = "menu mix in June 2026"
        self.assertTrue(use_file_answer(question, "ops"))
        text = lookup(question, "ops")
        self.assertIn("June 2026", text)
        self.assertIn("not loaded yet", text)
        self.assertIn("Jarvis", text)
        self.assertIn("No figure is invented", text)
        self.assertNotIn("₹", text)
        self.assertNotIn("estimate", text.casefold())
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
            return ("June 2026 Kolkata menu mix was about ₹2.5Cr, estimated from October.", None)

        reset_snapshot()
        result = produce_answer(
            "menu mix in June 2026",
            view_for(role="ops"),
            False,
            client=fake_client,
        )
        self.assertIn("Jarvis", result["text"])
        self.assertIn("not loaded yet", result["text"])
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
        result = dispatch("month_lookup", {"question": "menu mix in June 2026"}, "ops")
        self.assertIn("Jarvis", result["text"])
        self.assertIn("not loaded yet", result["text"])

    def test_tool_accepts_month_and_domain_arguments(self):
        result = dispatch(
            "month_lookup",
            {"question": "", "month": "2026-06", "domain": "menu_mix"},
            "ops",
        )
        self.assertEqual(result["text"], missing_text("menu_mix", 2026, 6))

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

    def test_april_sales_match_alfred(self):
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
        # June, July and August match Alfred's totals; 1–3 Sep is loaded too.
        # (Full Jun–Aug checks live in test_june_july_august_sales_match_alfred.)
        self.assertFalse(use_file_answer("Kolkata sales in June 2026", "ops"))
        self.assertTrue(month_loaded("sales", 2026, 6, "ops"))
        self.assertTrue(month_loaded("sales", 2026, 7, "ops"))
        self.assertTrue(month_loaded("sales", 2026, 8, "ops"))
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
        # Official consumption for April is loaded as its own domain.
        self.assertTrue(month_loaded("consumption", 2026, 4, "ops"))


    def test_june_july_august_sales_match_alfred(self):
        # Alfred: Jun ₹5,03,80,883.93 / 99,254 bills; Jul ₹5,03,12,513.50 / 1,00,561;
        # Aug ₹5,53,93,886.06 / 1,09,833. Net blank. Faridabad in; Chattarpur and GK1 out.
        expected = {
            "june": ("₹503.81L", "99,254", "₹248.21L", "₹254.27L", "₹1.33L", Decimal("50380883.93"), Decimal("99254")),
            "july": ("₹503.13L", "100,561", "₹255.67L", "₹245.88L", "₹1.58L", Decimal("50312513.50"), Decimal("100561")),
            "august": ("₹553.94L", "109,833", "₹279.70L", "₹274.18L", "₹0.06L", Decimal("55393886.06"), Decimal("109833")),
        }
        channels = {
            "2026-06": [("DINEIN", "₹316.78L"), ("ZOMATOONLINE", "₹107.55L"), ("SWIGGYONLINE", "₹66.95L"), ("TAKEOUT", "₹12.51L"), ("ONDC", "₹0.02L")],
            "2026-07": [("DINEIN", "₹312.94L"), ("ZOMATOONLINE", "₹106.15L"), ("SWIGGYONLINE", "₹71.00L"), ("TAKEOUT", "₹13.03L"), ("ONDC", "₹0.01L")],
            "2026-08": [("DINEIN", "₹338.22L"), ("ZOMATOONLINE", "₹124.36L"), ("SWIGGYONLINE", "₹77.20L"), ("TAKEOUT", "₹14.12L"), ("ONDC", "₹0.04L")],
        }
        month_num = {"june": 6, "july": 7, "august": 8}
        for name, (net_lakh, bills, kol, ncr, events, gross, bill_n) in expected.items():
            reset_snapshot()
            text = month_sales_answer(f"total {name} sales", view_for(role="ops"), False)["text"]
            self.assertIn(net_lakh, text, msg=name)
            self.assertIn(bills, text, msg=name)
            self.assertIn(f"Kolkata {kol}", text, msg=name)
            self.assertIn(f"NCR {ncr}", text, msg=name)
            self.assertIn("Events & Catering", text, msg=name)
            self.assertIn(events, text, msg=name)
            self.assertIn("outside store comparisons", text, msg=name)
            self.assertIn("Faridabad is included", text, msg=name)
            self.assertNotIn("Chattarpur", text, msg=name)
            self.assertNotRegex(text, r"GK1|GK 1", msg=name)
            self.assertIn("net is not loaded", text.casefold(), msg=name)
            self.assertNotIn("Network net was ₹0", text, msg=name)
            mon = f"2026-{month_num[name]:02d}"
            with (_ROOT / "data" / "history" / "sales_store_month.csv").open(newline="", encoding="utf-8-sig") as handle:
                rows = [row for row in csv.DictReader(handle) if row["month"] == mon]
            self.assertTrue(all(row.get("net") == "" for row in rows), f"net must stay blank in {mon}")
            self.assertFalse(any("chattarpur" in (row.get("store") or "").casefold() for row in rows))
            self.assertFalse(any("gk1" in (row.get("store") or "").casefold() or "gk 1" in (row.get("store") or "").casefold() for row in rows))
            self.assertTrue(any("faridabad" in (row.get("store") or "").casefold() for row in rows))
            loaded_gross = sum(Decimal(row["gross"]) for row in rows)
            loaded_bills = sum(Decimal(row["bills"] or 0) for row in rows)
            self.assertEqual(loaded_gross, gross)
            self.assertEqual(loaded_bills, bill_n)
            channel = lookup(f"channel split in {name} 2026", "ops")
            for source, amount in channels[mon]:
                self.assertIn(f"{source}: {amount}", channel, msg=f"{mon} {source}")
        # May files are still the committed extracts (already in the branch).
        self.assertTrue(month_loaded("sales", 2026, 5, "ops"))
        self.assertTrue((_ROOT / "data" / "posist" / "daily_sales" / "sales_2026-05.csv").is_file())
        self.assertTrue((_ROOT / "data" / "posist" / "monthly" / "sales_2026-05.csv").is_file())
        # 1–3 Sep is loaded, so September is a full calendar month.
        reset_snapshot()
        sep = month_sales_answer("Kolkata sales in September 2026", view_for(role="ops"), False)["text"]
        self.assertNotIn("missing 1, 2, 3 Sep", sep)
        self.assertIn("full calendar month 1–30 Sep 2026", sep)
        self.assertNotIn("Chattarpur", sep)

    def test_april_to_september_consumption_and_june_food_cost(self):
        # 179 store-months: 30 stores × Apr–8 Sep, minus Sec 31 April; Chattarpur and GK1 excluded.
        self.assertTrue(month_loaded("consumption", 2026, 4, "ops"))
        self.assertTrue(month_loaded("consumption", 2026, 8, "ops"))
        self.assertTrue(month_loaded("consumption", 2026, 9, "ops"))
        self.assertFalse(month_loaded("consumption", 2026, 10, "ops"))
        with (_ROOT / "data" / "history" / "consumption_store_month.csv").open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 179)
        self.assertFalse(any("chattarpur" in (r.get("store") or "").casefold() for r in rows))
        self.assertFalse(any("gk1" in (r.get("store") or "").casefold() for r in rows))
        april = [r for r in rows if r["month"] == "2026-04"]
        june = [r for r in rows if r["month"] == "2026-06"]
        self.assertEqual(len(april), 29)  # no Sec 31
        self.assertEqual(len(june), 30)
        self.assertFalse(any("sec 31" in (r.get("store") or "").casefold() for r in april))
        self.assertTrue(any("sec 31" in (r.get("store") or "").casefold() for r in june))
        # Raw files stay out of the repo.
        raw_dir = _ROOT / "data" / "procurement" / "backfill" / "consumption"
        self.assertFalse(raw_dir.is_dir() and any(raw_dir.glob("*.xls")))

        # Ideal Plaza (Kolkata) and Connaught Place (NCR) June food cost.
        # Ideal Plaza: raw 3,08,867.74 + semi 3,14,966.25 = 6,23,833.99 / gross 32,59,481.26 = 19.1%.
        # Packaging 2,00,563.11 = 6.2% of gross.
        ideal = lookup("Ideal Plaza food cost in June 2026", "ops")
        self.assertIn("June 2026 consumption", ideal)
        self.assertIn("Ideal Plaza", ideal)
        self.assertIn("Food cost 19.1%", ideal)
        self.assertIn("Packaging is 6.2% of gross", ideal)
        self.assertIn("shown separately", ideal)
        self.assertIn("(raw + semi-processed consumption) / Posist gross", ideal)
        self.assertIn("₹32.59L", ideal)  # gross
        self.assertIn("₹6.24L", ideal)  # food 623833.99
        # Connaught Place: raw 4,59,605.10 + semi 5,40,527.96 = 10,00,133.06 / 41,25,156.50 = 24.2%.
        # Packaging 75,615.03 = 1.8% of gross.
        cp = lookup("Connaught Place food cost in June 2026", "ops")
        self.assertIn("Connaught place", cp)
        self.assertIn("Food cost 24.2%", cp)
        self.assertIn("Packaging is 1.8% of gross", cp)
        self.assertIn("₹41.25L", cp)
        self.assertIn("₹10.00L", cp)

        # Missing store-months: 'not available', no figure.
        sec31 = lookup("Sec 31 Gurgaon consumption in April 2026", "ops")
        self.assertIn("not available", sec31.casefold())
        self.assertIn("No figure is given", sec31)
        self.assertNotIn("₹", sec31)
        fra = lookup("North FRA consumption in June 2026", "ops")
        self.assertIn("not available", fra.casefold())
        self.assertIn("02/0017", fra)
        self.assertNotIn("₹", fra)
        chat = lookup("Chattarpur consumption in June 2026", "ops")
        self.assertIn("excluded", chat.casefold())
        self.assertIn("No figure is given", chat)
        self.assertNotIn("₹", chat)
        events = lookup("Events & Catering consumption in June 2026", "ops")
        self.assertIn("not available", events.casefold())
        self.assertNotIn("₹", events)
        # October is not loaded; would come from Procurement.
        oct_c = lookup("food cost in October 2026", "ops")
        self.assertIn("not loaded", oct_c.casefold())
        self.assertIn("Procurement", oct_c)
        self.assertNotIn("₹", oct_c)
        # September is 1–8 only; food cost % is not stated.
        sep = lookup("consumption in September 2026", "ops")
        self.assertIn("2026-09-01 to 2026-09-08", sep)
        self.assertIn("not a full calendar month", sep)
        self.assertIn("food-cost percent is not stated", sep.casefold())


if __name__ == "__main__":
    unittest.main()


class SeptemberAndTabwiseChannelTests(unittest.TestCase):
    def test_first_three_days_of_september_reconcile_and_complete_the_month(self):
        path = _ROOT / "data" / "posist" / "daily_sales" / "sales_2026-09.csv"
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual({row["date"] for row in rows}, {"2026-09-01", "2026-09-02", "2026-09-03"})
        self.assertEqual(sum(Decimal(row["gross"]) for row in rows), Decimal("4256196.99"))
        self.assertEqual(sum(int(row["bills"]) for row in rows), 8954)
        self.assertTrue(all(row["net"] == "" for row in rows))
        with (_ROOT / "data" / "history" / "sales_store_month.csv").open(newline="", encoding="utf-8-sig") as handle:
            sep = [row for row in csv.DictReader(handle) if row["month"] == "2026-09"]
        # 30 stores, one row each (no duplicate names from the two sources).
        self.assertEqual(len(sep), 30)
        self.assertEqual(sum(Decimal(row["gross"]) for row in sep), Decimal("50772723.19"))
        self.assertEqual(sum(Decimal(row["bills"]) for row in sep), Decimal("101330"))
        self.assertTrue(all(row["first_day"] == "2026-09-01" for row in sep))
        self.assertFalse(any("chattarpur" in row["store"].casefold() or "gk1" in row["store"].casefold() for row in sep))
        self.assertTrue(any("faridabad" in row["store"].casefold() for row in sep))
        with (_ROOT / "data" / "history" / "sales_city_month.csv").open(newline="", encoding="utf-8-sig") as handle:
            cities = {row["city"]: row for row in csv.DictReader(handle) if row["month"] == "2026-09"}
        self.assertEqual(cities["Kolkata"]["gross"], "25740673.85")
        self.assertEqual(cities["NCR"]["gross"], "25032049.34")
        self.assertEqual(cities["Kolkata"]["complete"], "yes")
        self.assertEqual(cities["NCR"]["complete"], "yes")
        text = lookup("Kolkata sales in September 2026", "ops")
        self.assertIn("₹257.41L", text)
        self.assertNotIn("not on file", text)
        self.assertNotIn("still coming", coverage_line("ops"))

    def test_tabwise_channel_days_cover_october_to_twelve_november(self):
        manifest = json.loads((_ROOT / "data" / "posist" / "channel_tabwise_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["days"]), 43)
        self.assertEqual(manifest["days"][0], "2026-10-01")
        self.assertEqual(manifest["days"][-1], "2026-11-12")
        self.assertEqual(manifest["duplicate_days"], ["2026-11-11"])
        self.assertEqual(manifest["duplicate_keys_disagreeing"], 0)
        folder = _ROOT / "data" / "posist" / "daily_sales"
        for day in manifest["days"]:
            with (folder / f"channel_{day}.csv").open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            keys = [(row["store"], row["source"]) for row in rows]
            self.assertEqual(len(keys), len(set(keys)), day)
            self.assertFalse(any("network" in row["store"].casefold() for row in rows), day)
            self.assertFalse(any("chattarpur" in row["store"].casefold() for row in rows), day)
            if day >= "2026-10-23":
                self.assertFalse(any("faridabad" in row["store"].casefold() for row in rows), day)
        # ONDC is absent on 1 Oct, not written as zero.
        with (folder / "channel_2026-10-01.csv").open(newline="", encoding="utf-8-sig") as handle:
            self.assertNotIn("ONDC", {row["source"] for row in csv.DictReader(handle)})
        october = lookup("channel split in October 2026", "ops")
        self.assertIn("DINEIN: ₹333.55L", october)
        self.assertIn("ZOMATOONLINE: ₹116.29L", october)
        self.assertIn("2026-10-01 to 2026-10-31", october)
        with (_ROOT / "data" / "history" / "channel_tabwise_reconciliation.csv").open(newline="", encoding="utf-8-sig") as handle:
            status = defaultdict(int)
            for row in csv.DictReader(handle):
                status[row["status"]] += 1
        self.assertEqual(status["match"], 1216)
        self.assertEqual(status["no store gross loaded"], 8)
        self.assertEqual(status["mismatch"], 32)
