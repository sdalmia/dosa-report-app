"""Rendered reports stay inside the page and carry no markdown."""

import os
import tempfile
import unittest
from io import BytesIO

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _DB.name)
os.environ.setdefault("SECRET_KEY", "test-secret")

from pypdf import PdfReader

from app.chat.pdf_layout import fit_widths, plain
from app.chat.report import build_report, render_pdf
from app.chat.sizing import delhi_text
from app.chat.snapshot import reset_snapshot, view_for


def _text(pdf):
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)


class LayoutTests(unittest.TestCase):
    def test_columns_fit_the_content_width(self):
        widths = fit_widths(
            ["Store", "A very long header that must shrink"],
            [["Ideal Plaza", "x" * 80]],
            174,
        )
        self.assertLessEqual(sum(widths), 174.01)
        self.assertGreater(min(widths), 0)

    def test_plain_copy_drops_markdown_and_file_names(self):
        cleaned = plain("**Behind** # title | sales_2026-11-23.csv and ₹1")
        self.assertNotIn("**", cleaned)
        self.assertNotIn("#", cleaned)
        self.assertNotIn("|", cleaned)
        self.assertNotIn(".csv", cleaned)

    def test_sample_pdfs_have_no_markdown_and_stay_a_page(self):
        reset_snapshot()
        owner = view_for(role="owner")
        samples = {
            "daily": build_report("give me a pdf of the daily review", owner, True, "Daily review"),
            "delhi": build_report(
                "what is the real problem in Delhi - give me a pdf",
                owner,
                True,
                delhi_text(True),
            ),
            "procurement": build_report("give me a pdf of food cost by store", owner, True, "Food cost."),
        }
        for name, report in samples.items():
            pdf = render_pdf(report)
            self.assertTrue(pdf.startswith(b"%PDF"), name)
            text = _text(pdf)
            self.assertNotIn("**", text, name)
            self.assertNotIn("|", text, name)
            self.assertNotRegex(text, r"(?m)^#", name)
            self.assertNotIn(".csv", text, name)
            self.assertNotIn(".xlsx", text, name)
            self.assertIn("Dosa Coffee", text, name)
            self.assertNotIn("...", text, name)
            self.assertNotIn("…", text, name)
            self.assertNotIn("IST IST", text, name)
            self.assertNotRegex(text, r"20\d{2}-\d{2}-\d{2}", name)
            self.assertGreaterEqual(len(PdfReader(BytesIO(pdf)).pages), 1, name)

    def test_a_delhi_report_is_ncr_only_and_uses_the_analysis_window(self):
        reset_snapshot()
        report = build_report(
            "what is the real problem in Delhi - give me a pdf",
            view_for(role="owner"),
            True,
            "Delhi",
        )
        self.assertEqual(report["coverage"], "17-23 Nov 2026 against 20 Oct-2 Nov 2026")
        self.assertNotIn("16 Nov", report["coverage"])
        names = [row[0] for row in report["tables"][0]["rows"]]
        joined = " ".join(names)
        for east in ("Ideal Plaza", "Salt Lake", "Lake Road", "Manisquare", "Quest", "Rangoli"):
            self.assertNotIn(east, joined)
        self.assertTrue(any("Sec 18" in name or "Connaught" in name for name in names))
        titles = [report["chart"]["title"], *[table["name"] for table in report["tables"]]]
        self.assertEqual(len(titles), len(set(titles)))
        pdf = _text(render_pdf(report))
        self.assertNotIn("...", pdf)
        self.assertNotIn("Store performance", pdf)


if __name__ == "__main__":
    unittest.main()
