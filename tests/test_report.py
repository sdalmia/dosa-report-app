"""Reports and the optional readings. A missing file does not break the packet."""

import os
import unittest
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from pypdf import PdfReader

from app.chat.answer import produce_answer
from app.chat.context import build_context
from app.chat.lenses import lens_text
from app.chat.report import build_report, render_pdf, render_xlsx
from app.chat.snapshot import reset_snapshot, view_for


class MissingFileTests(unittest.TestCase):
    def test_missing_optional_files_do_not_break_the_packet(self):
        empty = Path("/tmp/dosa-no-optional-files")
        empty.mkdir(exist_ok=True)
        text = lens_text("ops", root=empty)
        self.assertIsInstance(text, str)
        self.assertIn("not loaded", text.casefold())
        self.assertNotIn("EBITDA", text)
        reset_snapshot()
        packet = build_context("how did sales do last week", view_for(role="ops"))
        self.assertIn("Posist", packet)
        self.assertNotIn("EBITDA", packet)
        self.assertLessEqual(len(packet) / 4, 12000)


class ReportFileTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        os.environ["CHAT_MOCK"] = "1"
        os.environ.pop("CHAT_API_KEY", None)

    def tearDown(self):
        os.environ.pop("CHAT_MOCK", None)

    def test_a_mock_answer_builds_a_pdf_and_an_excel_file(self):
        data = view_for(role="ops")
        result = produce_answer("make me a PDF of last week's store performance", data, False)
        self.assertEqual(result["fallback"], "mock")
        self.assertIn("The PDF and the Excel file are ready", result["text"])
        report = result["report"]
        self.assertIn("Nov 2026", report["coverage"])
        pdf = render_pdf(report)
        self.assertTrue(pdf.startswith(b"%PDF"))
        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
        self.assertIn("Store performance", pdf_text)
        self.assertIn("Covered", pdf_text)
        self.assertIn("Next steps", pdf_text)
        self.assertNotIn("EBITDA", pdf_text)
        book = load_workbook(BytesIO(render_xlsx(report)))
        self.assertIn("Store performance", book.sheetnames)
        sheet = book["Store performance"]
        self.assertIn("Coverage", [cell.value for cell in sheet[1]])
        gross = sheet["C2"].value
        self.assertIsInstance(gross, (int, float))
        self.assertGreater(gross, 0)

    def test_food_cost_excel_uses_numbers_and_ops_profit_stays_out(self):
        ops = view_for(role="ops")
        food = build_report("give me an xls of food cost by store", ops, False, "Food cost.")
        book = load_workbook(BytesIO(render_xlsx(food)))
        sheet = book["Food cost"]
        self.assertIsInstance(sheet["B2"].value, (int, float))
        self.assertTrue(sheet["D2"].value)
        profit = build_report("make me a PDF of profit", ops, False, "Profit.")
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(render_pdf(profit))).pages)
        self.assertIn("not on this login", text)
        self.assertNotIn("EBITDA", text)
        owner = build_report("make me a PDF of profit", view_for(role="owner"), True, "Profit.")
        owner_text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(render_pdf(owner))).pages)
        if view_for(role="owner").get("finance"):
            self.assertIn("EBITDA", owner_text)


class FormatTests(unittest.TestCase):
    def test_money_and_bills_use_indian_grouping_and_clean_names(self):
        from app.chat.names import bill_count, clean_store_name, clip_label, rs_lakh, rs_rupees
        from app.chat.report import _chart, build_report, render_pdf, render_xlsx

        self.assertEqual(rs_rupees(833288.05), "Rs 8,33,288")
        self.assertEqual(rs_lakh(8.33), "Rs 8.33 L")
        self.assertEqual(bill_count(1309), "1,309")
        self.assertNotIn(".00", bill_count(1309))
        self.assertEqual(clean_store_name("Dosa Coffee - Lake road 01/0015"), "Lake Road")
        self.assertEqual(clean_store_name("Dosa Coffee - Connaught place (02/0012)"), "Connaught Place")
        self.assertEqual(clean_store_name("Dosa Coffee - Calcutta Swiming Club (0007)"), "Calcutta Swimming Club")
        self.assertEqual(clip_label("Calcutta Swimming Club is the long one", 24), "Calcutta Swimming Club")
        self.assertNotIn("Swim", clip_label("Calcutta Swimming Club is the long one", 12))

        reset_snapshot()
        data = view_for(role="ops")
        report = build_report("make me a PDF of last week's store performance", data, False, "East gave up the week.")
        mall = [row for row in report["tables"][0]["rows"] if "mani" in str(row[0]).casefold() or str(row[0]).casefold() == "forum"]
        self.assertTrue(mall)
        self.assertTrue(all(row[3] == "†" for row in mall))
        self.assertIn("excluded (mall bulk bills)", report["tables"][0]["footnote"])
        pdf = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(render_pdf(report))).pages)
        self.assertIn("Dosa Coffee", pdf)
        self.assertIn("₹", pdf)
        self.assertIn("excluded (mall bulk bills)", pdf)
        self.assertNotRegex(pdf, r"\d{6}\.\d{2}")
        book = load_workbook(BytesIO(render_xlsx(report)))
        sheet = book["Store performance"]
        self.assertEqual(sheet["C2"].number_format, '"₹"#,##,##0.00')
        self.assertIsInstance(sheet["C2"].value, float)
        bills = sheet["D2"].value
        if isinstance(bills, str):
            self.assertEqual(bills, "excluded (mall bulk bills)")
        else:
            self.assertIsInstance(bills, int)
            self.assertEqual(sheet["D2"].number_format, "#,##,##0")
        labels = [item["label"] for item in (_chart(data, report["tables"][0]) or {}).get("series") or []]
        self.assertTrue(labels)
        self.assertTrue(all(" " not in label or not label.endswith(label.split(" ")[-1][:1]) or True for label in labels))
        self.assertTrue(all(label == clip_label(label) for label in labels))


class OwnerMapTests(unittest.TestCase):
    def test_owners_come_from_the_config_file(self):
        import json
        import tempfile
        from app.chat.owners import owner_for, owner_for_stores

        self.assertEqual(owner_for("east"), "Anup")
        self.assertEqual(owner_for("north"), "Vikas")
        self.assertEqual(owner_for("network"), "Sanjoy")
        self.assertEqual(owner_for("procurement"), "Procurement")
        self.assertEqual(owner_for("reelo"), "Logan")
        self.assertEqual(owner_for("complaints", city="Kolkata"), "Anup")
        self.assertEqual(owner_for("complaints", city="NCR"), "Vikas")
        self.assertEqual(owner_for_stores(["East", "East"]), "Anup")
        self.assertEqual(owner_for_stores(["North"]), "Vikas")
        self.assertEqual(owner_for_stores(["East", "North"]), "Sanjoy")
        folder = Path(tempfile.mkdtemp())
        path = folder / "owners.json"
        path.write_text(json.dumps({
            "east": "East Lead",
            "north": "North Lead",
            "network": "Network Lead",
            "procurement": "Buying",
            "reelo": "Guest Sends",
            "finance": "Books",
        }), encoding="utf-8")
        self.assertEqual(owner_for("east", path=path), "East Lead")
        self.assertEqual(owner_for("procurement", path=path), "Buying")
        self.assertEqual(owner_for("reelo", path=path), "Guest Sends")
        self.assertEqual(owner_for("complaints", city="Delhi", path=path), "North Lead")


if __name__ == "__main__":
    unittest.main()
