"""Figures match the files they came from."""

import csv
import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.chat.correctness import (
    channel_exceeds_gross,
    data_footer,
    day_counts_as_loaded,
    day_is_loaded,
    day_status,
    drop_pending,
    like_for_like,
    net_lakh,
    network_net_on,
    network_net_window,
    period_nets,
    precise_day,
    provisional_line,
    quoted_day_net,
    reconcile_note,
    round_lakh,
    variance_basis,
    variance_label,
)
from app.chat.facts import answer_from_data
from app.chat.snapshot import reset_snapshot, view_for

ROOT = Path(__file__).resolve().parents[1]
NET_FILE = ROOT / "data" / "posist" / "sales_pred_vs_actual.csv"


class VarianceBasisTests(unittest.TestCase):
    def test_a_week_without_a_count_flag_is_not_like_for_like(self):
        counted = {"week": "2026-11-16", "stock_count": "yes", "food_cost_pct": "27.1"}
        blank = {"week": "2026-11-09", "food_cost_pct": "26.4"}
        explicit = {"week": "2026-11-02", "physical_count": "no", "food_cost_pct": "25.0"}
        self.assertEqual(variance_basis(counted), "counted")
        self.assertEqual(variance_basis(blank), "uncounted")
        self.assertEqual(variance_basis(explicit), "uncounted")
        self.assertEqual(variance_basis({}), "uncounted")
        self.assertIn("no stock count", variance_label("uncounted"))
        self.assertIn("physical stock count", variance_label("counted"))
        self.assertFalse(like_for_like(variance_basis(counted), variance_basis(blank)))
        self.assertTrue(like_for_like("counted", "counted"))


class NetworkNetTests(unittest.TestCase):
    def test_16_to_22_nov_and_22_nov_match_the_net_file(self):
        reset_snapshot()
        with NET_FILE.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        by_day = {row["date"]: row for row in rows}
        day = by_day["2026-11-22"]["actual_net_L"].strip()
        self.assertEqual(network_net_on("2026-11-22"), day)
        summed, missing, _cells = network_net_window("2026-11-16", "2026-11-22")
        self.assertEqual(missing, [])
        published = sum(Decimal(by_day[f"2026-11-{d:02d}"]["actual_net_L"]) for d in range(16, 23))
        self.assertEqual(published, Decimal("95.96"))
        self.assertEqual(round_lakh(summed), Decimal("95.94"))
        self.assertNotEqual(round_lakh(summed), published)
        found = period_nets("2026-11-16", "2026-11-22")
        self.assertEqual(found["rounded_east"], Decimal("49.37"))
        self.assertEqual(found["rounded_north"], Decimal("46.58"))
        answer = answer_from_data("how did sales do last week", view_for(role="ops"), False)
        text = answer["text"]
        self.assertIn(net_lakh(day), text)
        self.assertIn(net_lakh("95.94"), text)
        self.assertNotIn(net_lakh("95.96"), text)
        self.assertIn("Rs 49.37 L net", text)
        self.assertIn("Rs 46.58 L net", text)
        self.assertIn("gross, not net", text)
        self.assertIn("sales_pred_vs_actual.csv", text)
        self.assertNotIn("doesn't reconcile", text)
        self.assertNotIn("isn't in yet", text)
        from app.chat.report import build_report, render_xlsx
        report = build_report("how did sales do last week", view_for(role="ops"), False, answer["text"])
        self.assertIn("Rs 95.94 L network net", report["sales_through"])
        self.assertNotIn("95.96", report["sales_through"])
        self.assertIn("Post-Diwali", text)
        self.assertIn("own forecast", text)
        book = render_xlsx(report)
        from io import BytesIO
        from openpyxl import load_workbook
        sheet = load_workbook(BytesIO(book))["Cover"]
        cover = " ".join(str(cell.value or "") for row in sheet.iter_rows() for cell in row)
        self.assertIn("Rs 95.94 L network net", cover)
        self.assertNotIn("Rs 95.96 L network net", cover)

    def test_rounding_happens_only_after_summing(self):
        folder = Path(tempfile.mkdtemp())
        path = folder / "sales_pred_vs_actual.csv"
        path.write_text(
            "date,actual_net_L,notes\n"
            "2026-01-01,1.01,East ₹0.505L + North ₹0.500L\n"
            "2026-01-02,1.01,East ₹0.505L + North ₹0.500L\n",
            encoding="utf-8",
        )
        east, north, total = precise_day({
            "actual_net_L": "1.01",
            "notes": "East ₹0.505L + North ₹0.500L",
        })
        self.assertEqual(total, Decimal("1.005"))
        self.assertEqual(round_lakh(east + north), Decimal("1.01"))
        summed, missing, _cells = network_net_window("2026-01-01", "2026-01-02", path)
        self.assertEqual(missing, [])
        self.assertEqual(summed, Decimal("2.010"))
        self.assertEqual(round_lakh(summed), Decimal("2.01"))
        rounded_each = round_lakh(Decimal("1.005")) + round_lakh(Decimal("1.005"))
        self.assertEqual(rounded_each, Decimal("2.02"))
        self.assertNotEqual(round_lakh(summed), rounded_each)

    def test_a_broken_sum_is_labelled(self):
        self.assertEqual(reconcile_note(["10", "5"], "20"), "doesn't reconcile")
        self.assertEqual(reconcile_note(["10", "5"], "15"), "")

    def test_channel_total_above_store_gross_is_flagged(self):
        self.assertTrue(channel_exceeds_gross("1200", "1000"))
        self.assertFalse(channel_exceeds_gross("800", "1000"))


class LoadMarkerTests(unittest.TestCase):
    def test_an_old_day_with_an_actual_counts_as_loaded(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Afternoon of 24 Nov: the latest expected day is 23 Nov, which has no marker.
        afternoon = datetime(2026, 11, 24, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        self.assertTrue(day_is_loaded("2026-11-22"))
        self.assertFalse(day_is_loaded("2026-11-09"))
        self.assertTrue(day_counts_as_loaded("2026-11-09", now=afternoon))
        self.assertFalse(drop_pending("2026-11-09", now=afternoon))
        self.assertEqual(day_status("2026-11-09", asked_start="2026-11-16", asked_end="2026-11-22", now=afternoon), "")
        quoted = quoted_day_net("2026-11-09", now=afternoon)
        self.assertNotIn("isn't in yet", quoted)
        self.assertIn(net_lakh(network_net_on("2026-11-09")), quoted)
        self.assertIn(net_lakh(network_net_on("2026-11-22")), quoted_day_net("2026-11-22", now=afternoon))

    def test_isnt_in_yet_is_only_the_latest_expected_day_inside_the_period(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        afternoon = datetime(2026, 11, 24, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        inside = day_status(
            "2026-11-23",
            asked_start="2026-11-16",
            asked_end="2026-11-23",
            now=afternoon,
        )
        self.assertIn("2026-11-23 isn't in yet", inside)
        outside = day_status(
            "2026-11-23",
            asked_start="2026-11-16",
            asked_end="2026-11-22",
            now=afternoon,
        )
        self.assertEqual(outside, "")
        self.assertEqual(
            day_status("2026-11-09", asked_start="2026-11-09", asked_end="2026-11-09", now=afternoon),
            "",
        )
        self.assertTrue(drop_pending("2026-11-23", now=afternoon))
        self.assertFalse(drop_pending("2026-11-22", now=afternoon))
        from app.chat.lenses import bill_driver
        self.assertNotIn("2026-11-09 isn't in yet", bill_driver())


class FinanceFlagTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()

    def test_owner_profit_is_provisional_and_ops_does_not_see_the_flag(self):
        with (ROOT / "data" / "flags" / "accountant.csv").open(newline="", encoding="utf-8-sig") as handle:
            title = next(csv.DictReader(handle))["title"]
        owner = answer_from_data("What's each company's profit this month?", view_for(role="owner"), True)
        self.assertIn("Provisional:", owner["text"])
        self.assertIn(title, owner["text"])
        ops = answer_from_data("What's each company's profit this month?", view_for(role="ops"), False)
        self.assertNotIn("Provisional:", ops["text"])
        self.assertNotIn(title, ops["text"])
        self.assertNotIn("EBITDA", ops["text"])

    def test_tally_states_the_last_day_the_books_run_through(self):
        answer = answer_from_data("What did we pay in Delhi on 2 Nov?", view_for(role="owner"), True)
        self.assertIn("Books run through", answer["text"])


class VarianceFileTests(unittest.TestCase):
    def test_an_uncounted_week_is_labelled_and_not_compared(self):
        from app.chat.lenses import lens_text

        root = Path(tempfile.mkdtemp())
        folder = root / "data" / "procurement"
        folder.mkdir(parents=True)
        path = folder / "kolkata_variance_weekly_2026-11-16.csv"
        path.write_text(
            "week,food_cost_pct,stock_count\n"
            "2026-11-02,27.1,yes\n"
            "2026-11-09,26.4,\n",
            encoding="utf-8",
        )
        text = lens_text("ops", root)
        self.assertIn("2026-11-02: true food cost (physical stock count)", text)
        self.assertIn("2026-11-09: recipe use + booked wastage, no stock count", text)
        self.assertIn("not compared like-for-like", text)


class ChannelGuardTests(unittest.TestCase):
    def test_a_channel_total_above_store_gross_is_not_used(self):
        from app.chat.lenses import _channel_shift

        root = Path(tempfile.mkdtemp())
        folder = root / "data" / "posist" / "daily_sales"
        folder.mkdir(parents=True)
        (folder / "_DONE_2026-11-15").write_text("ok", encoding="utf-8")
        (folder / "_DONE_2026-11-22").write_text("ok", encoding="utf-8")
        (folder / "sales_2026-11-15.csv").write_text(
            "store,gross,bills\nStore A,100,10\n", encoding="utf-8"
        )
        (folder / "sales_2026-11-22.csv").write_text(
            "store,gross,bills\nStore A,100,10\n", encoding="utf-8"
        )
        (folder / "channel_2026-11-15.csv").write_text(
            "store,source,sales\nStore A,DINEIN,40\nStore A,SWIGGYONLINE,10\n",
            encoding="utf-8",
        )
        (folder / "channel_2026-11-22.csv").write_text(
            "store,source,sales\nStore A,DINEIN,90\nStore A,SWIGGYONLINE,80\n",
            encoding="utf-8",
        )
        text = _channel_shift(root)
        self.assertIn("exceeds store gross", text)
        self.assertIn("not used", text)
        self.assertNotIn("mix moved", text)


class TrackerThroughTests(unittest.TestCase):
    def test_a_price_answer_states_the_last_stock_entry_date(self):
        from app import create_app
        from app.extensions import db
        from app.models import IngredientPrice

        handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        handle.close()
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "sqlite:///" + handle.name
        try:
            app = create_app()
            app.config["TESTING"] = True
            with app.app_context():
                db.session.add(IngredientPrice(
                    ingredient_name="Test Spice 999",
                    unit_price=13,
                    quantity=1,
                    date=date(2026, 11, 2),
                ))
                db.session.add(IngredientPrice(
                    ingredient_name="Later Onion 999",
                    unit_price=40,
                    quantity=1,
                    date=date(2026, 11, 20),
                ))
                db.session.commit()
                reset_snapshot()
                answer = answer_from_data(
                    "What did we pay for Test Spice 999?",
                    view_for(role="ops"),
                    False,
                )
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
        self.assertIn("₹13", answer["text"])
        self.assertIn("Stock entries run through 20 Nov 2026", answer["text"])


class FooterTests(unittest.TestCase):
    def test_every_sales_answer_names_the_through_date_and_the_sources(self):
        reset_snapshot()
        answer = answer_from_data("how did sales do last week", view_for(role="ops"), False)
        self.assertIn("Data through", answer["text"])
        self.assertIn("Sources:", answer["text"])
        self.assertIn("sales_pred_vs_actual.csv", answer["text"])
        footer = data_footer(view_for(role="ops"), "how did sales do last week")
        self.assertTrue(footer.startswith("Data through"))


if __name__ == "__main__":
    unittest.main()
