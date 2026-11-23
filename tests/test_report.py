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
        self.assertIn("Coverage", pdf_text)
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


if __name__ == "__main__":
    unittest.main()
