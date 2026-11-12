"""The model is what the visitor reads when a key is set."""

import os
import subprocess
import unittest
from pathlib import Path

from app.chat.answer import produce_answer
from app.chat.context import build_context
from app.chat.snapshot import reset_snapshot, view_for

ROOT = Path(__file__).resolve().parents[1]


class ContextTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.data = view_for(role="ops")

    def test_a_sales_question_gets_store_rows_not_a_one_line_summary(self):
        context = build_context("How did sales do yesterday?", self.data)
        self.assertIn("Each store on the latest sales day", context)
        self.assertIn("gross", context)
        self.assertGreater(context.count("\n"), 30)
        self.assertNotIn("EBITDA", context)
        self.assertIn("People: not included", context)

    def test_owner_context_includes_finance(self):
        owner = view_for(role="owner")
        context = build_context("What's each company's profit this month?", owner)
        if owner.get("finance"):
            self.assertIn("Finance (this role may see it)", context)
        else:
            self.assertIn("Finance:", context)


class ModelPathTests(unittest.TestCase):
    def setUp(self):
        reset_snapshot()
        self.data = view_for(role="ops")
        os.environ["CHAT_API_KEY"] = "test-key-not-a-secret"
        os.environ.pop("CHAT_MOCK", None)
        os.environ.pop("CHAT_MODEL", None)

    def tearDown(self):
        os.environ.pop("CHAT_API_KEY", None)

    def test_the_model_reply_is_kept_whole_including_a_markdown_table(self):
        reply = "\n".join([
            "Yesterday's sales were led by the stores in the packet.",
            "",
            "| Store | Gross |",
            "| --- | --- |",
            "| Lake Town | ₹1,00,000 |",
            "",
            "The file's latest day is the day to use if yesterday is not in yet.",
            "",
            "- Check the softest store before the next rush.",
        ])

        def client(messages, model):
            packet = messages[-1]["content"]
            self.assertIn("Each store on the latest sales day", packet)
            self.assertIn("gross", packet)
            self.assertGreater(len(packet), 500)
            return reply, None

        result = produce_answer("How did sales do yesterday?", self.data, False, client=client)
        self.assertIsNone(result["fallback"])
        self.assertEqual(result["model"], "gpt-4.1")
        self.assertIn("| Store | Gross |", result["text"])
        self.assertIn("Lake Town", result["text"])
        self.assertIn("Check the softest store", result["text"])
        self.assertNotIn("AI unavailable", result["text"])
        self.assertGreater(len(result["text"]), 120)

    def test_a_failed_call_says_the_ai_is_unavailable(self):
        def client(messages, model):
            return None, "http_500"

        result = produce_answer("How did sales do yesterday?", self.data, False, client=client)
        self.assertEqual(result["fallback"], "http_500")
        self.assertIsNone(result["model"])
        self.assertTrue(result["text"].startswith("AI unavailable"))


class MarkdownRenderTests(unittest.TestCase):
    def test_a_markdown_table_survives_rendering(self):
        script = r"""
const {renderMarkdown} = require("./static/js/markdown.js");
const html = renderMarkdown("| Store | Gross |\n| --- | --- |\n| Lake Town | ₹1,00,000 |\n\n**Led** the day.\n");
if (html.indexOf("<table") < 0) process.exit(1);
if (html.indexOf("Lake Town") < 0) process.exit(2);
if (html.indexOf("₹1,00,000") < 0) process.exit(3);
if (html.indexOf("<strong>Led</strong>") < 0) process.exit(4);
if (html.indexOf("<script") >= 0) process.exit(5);
"""
        done = subprocess.run(["node", "-e", script], cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr or done.stdout)


if __name__ == "__main__":
    unittest.main()
