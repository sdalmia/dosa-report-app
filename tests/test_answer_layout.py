"""Markdown answers keep their lines, lists, and tables."""

import unittest

from app.chat.answer import stream_pieces

SAMPLE = """Dosa Coffee is performing moderately well overall, with strong sales in the East, weaker performance in the North, and some recent week-on-week softness across the network.

**Breakdown:**
- **Network Sales Pace:** As of 2026-11-11, the network is at 85.8% of target pace for the month, with a net sales MTD of ₹1,61,27,000 and a mid forecast of ₹1,58,50,000.
  - East region pace: 91.6%
  - North region pace: 79.9%
- **Top Stores (MTD, up to 2026-11-08):**
  - Ideal Plaza (East): ₹9,85,280
  - Connaught Place (North): ₹7,90,155
  - Salt Lake (East): ₹7,26,579
- **Quality & Loyalty:** Mystery audit scores mostly above 90% (Pacific mall, Jasola 74.2%). Reelo repeat share: Lake Road 57.18%, Noida Sec143 60.92%.
- **Profitability:** Kolkata Sep 2026 EBITDA after ads and kitchen ₹15L (6.8%); NCR -₹8.8L (-4.1%).

**Key Numbers Table:**
| Metric | Network | East | North |
|---|---|---|---|
| Target Pace (%) | 85.8 | 91.6 | 79.9 |
| MTD Net Sales (₹) | 1,61,27,000 | — | — |
| Top Store MTD (₹) | 9,85,280 (Ideal Plaza) | 9,85,280 (Ideal Plaza) | 7,90,155 (Connaught Place) |
| EBITDA (Sep 2026) | — | ₹15L (6.8%) | -₹8.8L (-4.1%) |

**Recent Week-on-Week Trend:**

**Next Actions:**
1. Focus on boosting North region sales (79.9% of pace).
2. Fix quality at low audit stores (Pacific mall, Jasola 74.2%).
3. Use high repeat rates at Lake Road and Noida Sec143 for loyalty growth.
"""


class StreamTests(unittest.TestCase):
    def test_streaming_keeps_newlines(self):
        joined = "".join(stream_pieces(SAMPLE))
        self.assertEqual(joined, SAMPLE)
        self.assertIn("\n| Metric |", joined)
        self.assertIn("\n- **Network Sales Pace:**", joined)


class RenderTests(unittest.TestCase):
    def test_sample_becomes_lists_and_a_table_and_drops_the_empty_heading(self):
        import subprocess
        from pathlib import Path

        script = r"""
const {renderMarkdown} = require("./static/js/markdown.js");
const fs = require("fs");
const sample = fs.readFileSync("/tmp/answer-sample.md", "utf8");
const html = renderMarkdown(sample + "\n<script>alert(1)</script>\n");
if (html.indexOf("<ul>") < 0) process.exit(1);
if (html.indexOf("<ol>") < 0) process.exit(2);
if (html.indexOf("<table") < 0) process.exit(3);
if (html.indexOf("85.8") < 0) process.exit(4);
if (html.indexOf("Recent Week-on-Week Trend") >= 0) process.exit(5);
if (html.indexOf("<script") >= 0) process.exit(6);
if (html.indexOf("&lt;script&gt;") < 0) process.exit(7);
if (html.indexOf("Next Actions") < 0) process.exit(8);
"""
        Path("/tmp/answer-sample.md").write_text(SAMPLE, encoding="utf-8")
        done = subprocess.run(
            ["node", "-e", script],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
        )
        self.assertEqual(done.returncode, 0, done.stderr or done.stdout)


if __name__ == "__main__":
    unittest.main()
