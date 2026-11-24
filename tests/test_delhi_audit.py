"""The live Delhi answer, checked against the files."""

import csv
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.chat.facts import answer_from_data
from app.chat.sizing import (
    commission_on_delivery,
    delhi_text,
    ge_ratio,
    load_hourly_compare,
    ncr_window,
    october_store_gross,
    posist_net,
    ratio_drift,
    repair_directions,
    repeat_story,
    store_rates,
    week_ratio,
)
from app.chat.snapshot import reset_snapshot, view_for


class WindowTests(unittest.TestCase):
    def test_ncr_uses_matched_days_and_strips_faridabad(self):
        base, recent, bill_effect, apb_effect, driver = ncr_window()
        self.assertEqual(round(base["gross_per_day"]), 745787)
        self.assertEqual(round(recent["gross_per_day"]), 722134)
        self.assertAlmostEqual(float(recent["gross_per_day"] / base["gross_per_day"] - 1), -0.032, places=3)
        self.assertEqual(round(bill_effect), -11071)
        self.assertEqual(round(apb_effect), -12582)
        self.assertEqual(driver, "both the bill count and the average bill")
        self.assertLess(october_store_gross(), Decimal("17000000"))

    def test_the_drop_is_four_stores_and_the_risers_are_not_listed(self):
        rows = {row["name"]: row for row in store_rates()}
        self.assertEqual(round(rows["Sec 18 Noida"]["gap_per_day"]), -7513)
        self.assertEqual(round(rows["Sec 143 Noida"]["gap_per_day"]), -5417)
        self.assertEqual(round(rows["Gurgaon Sec-15"]["gap_per_day"]), -5372)
        self.assertAlmostEqual(round(rows["Pacific Mall, Jasola"]["gap_per_day"]), -5095, delta=2)
        self.assertEqual(round(rows["Pacific Mall, Jasola"]["base_apb"]), 570)
        self.assertEqual(round(rows["Pacific Mall, Jasola"]["recent_apb"]), 519)
        for name in ("Rohini Sec-7", "Model Town", "Connaught Place"):
            self.assertTrue(rows[name]["up"], name)
        self.assertAlmostEqual(float(rows["Rohini Sec-7"]["recent_per_day"] / rows["Rohini Sec-7"]["base_per_day"] - 1), 0.033, places=3)

    def test_october_is_not_a_full_month_and_cp_bills_rose(self):
        bills = 0
        folder = Path(__file__).resolve().parents[1] / "data" / "posist" / "daily_sales"
        for path in folder.glob("sales_2026-10-*.csv"):
            day = path.stem.replace("sales_", "")
            if not ("2026-10-09" <= day <= "2026-10-31"):
                continue
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    if "connaught" in (row.get("store") or "").casefold():
                        bills += float(row.get("bills") or 0)
        self.assertEqual(bills, 3316)


class NetTests(unittest.TestCase):
    def test_posist_net_prefers_the_column_and_otherwise_estimates(self):
        amount, label = posist_net("1000", explicit=Decimal("901"))
        self.assertEqual(amount, Decimal("901"))
        self.assertEqual(label, "posist net")
        amount, label = posist_net("109864.94")
        self.assertEqual(label, "estimated net")
        self.assertEqual(amount, Decimal("98878.45"))
        # Ideal Plaza's checked day is 90.1%, Santoshpur 90.6%. A drift over 0.5 points is flagged.
        ideal = Decimal("98963.19") / Decimal("109864.94")
        santosh = Decimal("29108.38") / Decimal("32128.72")
        self.assertAlmostEqual(float(ideal), 0.901, places=3)
        self.assertAlmostEqual(float(santosh), 0.906, places=3)

    def test_a_store_ratio_that_drifts_is_flagged_and_ge_is_not_cut_again(self):
        self.assertIsNone(week_ratio("02/0001"))
        self.assertEqual(ratio_drift("02/0001"), [])
        ratio, row = ge_ratio("Noida Sec - 18")
        self.assertAlmostEqual(float(ratio), 0.829, places=3)
        commission = commission_on_delivery(row["gross"], Decimal("0.517"), tax=row["tax"])
        self.assertAlmostEqual(float(commission), 234500, delta=1500)
        booked = Decimal(row["commission"])
        self.assertAlmostEqual(float(booked), 237881, delta=1)

    def test_october_ratios_match_the_accountant(self):
        expected = {
            "Noida Sec - 18": 0.829,
            "Noida Sec -143": 0.822,
            "Gurgaon Sec-15": 0.875,
            "Paschim Vihar": 0.856,
            "Rohini": 0.831,
            "CP": 0.928,
            "Kalkaji": 0.797,
            "Chinar Park": 0.723,
            "Quest Mall": 0.952,
        }
        for name, ratio in expected.items():
            got, _row = ge_ratio(name)
            self.assertAlmostEqual(float(got), ratio, places=3, msg=name)

    def test_rent_columns_are_not_food_cost(self):
        _ratio, cp = ge_ratio("CP")
        self.assertAlmostEqual(float(Decimal(cp["rent"]) / Decimal(cp["net"])), 0.391, places=3)
        _ratio, sec31 = ge_ratio("Gurgaon Sector 31")
        self.assertAlmostEqual(float(Decimal(sec31["food_pct"])), 29.79, places=2)
        self.assertAlmostEqual(float(Decimal(sec31["rent"]) / Decimal(sec31["net"])), 0.330, places=3)
        _ratio, sec10 = ge_ratio("Gurgaon Sec - 10")
        self.assertAlmostEqual(float(Decimal(sec10["rent"]) / Decimal(sec10["net"])), 0.307, places=3)
        _ratio, model = ge_ratio("Model Town")
        self.assertAlmostEqual(float(Decimal(model["rent"]) / Decimal(model["net"])), 0.261, places=3)


class DirectionTests(unittest.TestCase):
    def test_an_up_word_that_contradicts_the_figures_is_repaired(self):
        fixed = repair_directions("APB up (652 vs 670)")
        self.assertIn("down", fixed.casefold())
        self.assertNotIn("up", fixed.casefold())
        self.assertEqual(repair_directions("APB up (670 vs 652)").casefold().split()[1], "up")


class YearColumnTests(unittest.TestCase):
    def test_vs_2025_files_have_the_year_columns_swapped_back(self):
        folder = Path(tempfile.mkdtemp())
        swapped = folder / "hourly_vs_2025.csv"
        swapped.write_text("hour,2026,2025\n12,100,200\n", encoding="utf-8")
        rows = load_hourly_compare(swapped)
        self.assertEqual(rows[0]["2026"], "200")
        self.assertEqual(rows[0]["2025"], "100")
        source = folder / "source_hourly.csv"
        source.write_text("hour,2026,2025\n12,100,200\n", encoding="utf-8")
        rows = load_hourly_compare(source)
        self.assertEqual(rows[0]["2026"], "100")
        self.assertEqual(rows[0]["2025"], "200")
        long = folder / "hourly_store_vs_2025.csv"
        long.write_text(
            '"Category","1 October 2025 - 12 November 2025","1 October 2026 - 12 November 2026"\n'
            '"POS",10,30\n',
            encoding="utf-8",
        )
        rows = load_hourly_compare(long)
        self.assertEqual(rows[0]["1 October 2025 - 12 November 2025"], "30")
        self.assertEqual(rows[0]["1 October 2026 - 12 November 2026"], "10")
        labelled = folder / "source_store_vs_2025.csv"
        labelled.write_text(
            '"Category","1 October 2025 - 12 November 2025","1 October 2026 - 12 November 2026"\n'
            '"POS",10,30\n',
            encoding="utf-8",
        )
        rows = load_hourly_compare(labelled)
        self.assertEqual(rows[0]["1 October 2025 - 12 November 2025"], "10")
        self.assertEqual(rows[0]["1 October 2026 - 12 November 2026"], "30")


class DelhiAnswerTests(unittest.TestCase):
    def test_the_delhi_answer_does_not_repeat_the_audit_errors(self):
        reset_snapshot()
        ops = answer_from_data("what is the real problem in Delhi - give me a deep insight", view_for(role="ops"), False)
        text = ops["text"]
        self.assertIn("Rs 7,45,787", text)
        self.assertIn("Rs 7,22,134", text)
        self.assertIn("No November budget is loaded", text)
        self.assertNotIn("235.17", text)
        self.assertNotIn("187.0", text)
        self.assertNotIn("14.56", text)
        self.assertNotIn("16.47", text)
        self.assertNotIn("4,850", text)
        self.assertNotIn("652 vs 670", text)
        self.assertNotIn("31.3", text)
        self.assertNotIn("57.5", text)
        self.assertNotIn("38.1", text)
        self.assertNotIn("EBITDA", text)
        self.assertIn("24.96%", text)
        self.assertIn("44.55%", text)
        self.assertIn("both the bill count and the average bill", text)
        self.assertIn("Sec 18 Noida", text)
        self.assertIn("51.3%", text)
        self.assertIn("57.0%", text)
        self.assertIn("No added commission", text)
        self.assertIn("-2.1%", text)
        self.assertIn("dine-in +9%", text)
        self.assertIn("delivery +74%", text)
        self.assertIn("Sec 18 Noida -12%", text)
        self.assertIn("Sec 143 Noida -10%", text)
        self.assertIn("Gurgaon Sec-15 -14%", text)
        self.assertNotIn("not in this drop", text)
        self.assertIn("not a problem list", text)
        self.assertIn("Sales through", text)
        self.assertIn("Reelo through", text)
        owner = delhi_text(True)
        self.assertIn("39.93%", owner)
        self.assertIn("-8.5%", owner)
        self.assertIn("20.6%", owner)
        self.assertIn("39.1%", owner)
        self.assertIn("33.0%", owner)
        self.assertIn("30.7%", owner)
        self.assertIn("26.1%", owner)
        self.assertNotIn("29.7%", owner.split("food")[0] if False else owner)
        self.assertIn("food cost", owner.casefold())


if __name__ == "__main__":
    unittest.main()
