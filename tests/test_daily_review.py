"""One check per daily-review question, plus a missing file and a sign check."""

import csv
import os
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _DB.name)
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.chat.daily_review import answer_text, build, money, section_id
from app.chat.facts import answer_from_data
from app.chat.report import build_report

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 24, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture(with_net=True, lift=False):
    folder = Path(tempfile.mkdtemp())
    sales = folder / "data" / "posist" / "daily_sales"
    sales.mkdir(parents=True)
    (sales / "_DONE_2026-11-23").write_text("", encoding="utf-8")
    days = [date(2026, 11, 17) + __import__("datetime").timedelta(i) for i in range(7)]
    days += [date(2026, 10, 20) + __import__("datetime").timedelta(i) for i in range(14)]
    lines = ["store,store_code,date,gross,net,bills,source,pulled_at"]
    for day in days:
        gross = "1000" if day < date(2026, 11, 17) else "700"
        net = "900" if with_net and day >= date(2026, 11, 17) else ""
        if day < date(2026, 11, 17) and with_net:
            net = "900"
        bills = "10" if day < date(2026, 11, 17) else "8"
        lines.append(f"Dosa Coffee - Sec 18 Noida (02/0001),02/0001,{day.isoformat()},{gross},{net},{bills},test,")
    _write(sales / "sales_2026-11-23.csv", "\n".join(lines) + "\n")
    _write(sales / "network_2026-11-23.csv", "date,region,gross,net,bills\n2026-11-23,East,0,0,0\n2026-11-23,North,700,630,8\n2026-11-23,Total,700,630,8\n")
    _write(sales / "channel_2026-11-23.csv", "store,store_code,source,sales\nDosa Coffee - Sec 18 Noida,02/0001,DINEIN,400\nDosa Coffee - Sec 18 Noida,02/0001,SWIGGYONLINE,300\n")
    _write(
        folder / "data" / "targets" / "store_targets.csv",
        "store_code,month,target_gross,target_net,includes_aggregators,daily_split,target_net_dinein,target_net_aggregator,budget_outlet_name,budget_sheet,notes\n"
        "02/0001,2026-11,,30000,yes,,,,Sec 18,Monthly Input Nov-26,own ratio\n",
    )
    _write(
        folder / "data" / "reelo" / "reelo_storewise_latest.csv",
        "Store,Total Orders,Total Dine-in & Take-away Orders,Orders with valid mobile numbers,%,Customers visited,New Customers,Repeat Customers,Derived repeat customer share (%),avg_rating,total_feedbacks_submitted,times_reward_redeemed,redemption_rate_in_percentage\n"
        "Sec 18,10,8,7,80,9,4,5,40,4.5,2,1,10\n",
    )
    _write(folder / "data" / "famepilot" / "open_complaints_export.csv", "date_time,store,platform,rating,keyword,status,owner,resolved_at\n2026-10-01,Sec 18,swiggy,1,Stale,,, \n")
    _write(folder / "data" / "store_health" / "famepilot.csv", "posist_store,famepilot_location,rating,review_count\nSec 18,Sec 18,4.2,3\n")
    _write(folder / "data" / "procurement" / "procurement_summary.json", '{"as_of":"2026-11-22","yesterday_grn":{"Delhi":{"date":"2026-11-22","value":1000}}}\n')
    _write(folder / "data" / "flags" / "procurement.csv", "area,severity,title,detail,owner,as_of,source\nprocurement,amber,Hold the daal,hold orders,Sailesh,2026-10-09,file\n")
    if lift:
        _write(
            folder / "data" / "reelo" / "marketing_plans.csv",
            "activity,store,start,end,channel,lift\nThank-you,Sec 18,2026-11-13,2026-11-30,WhatsApp,0.04\n",
        )
    return folder


class QuestionTests(unittest.TestCase):
    def test_each_question_has_its_own_section(self):
        root = _fixture()
        asked = {
            "target": "yesterday vs sales target",
            "growth": "are we growing or de-growing, with the bills effect",
            "outlets": "which are the underperforming outlets",
            "channel": "channel performance for yesterday",
            "marketing": "what marketing is planned and what was the impact",
            "reelo": "reelo enrolments and repeat visits",
            "quality": "guest complaints and hygiene",
            "cost": "is wastage under control",
            "people": "any manpower shortages or stock-outs",
            "actions": "today's key actions and yesterday's commitments",
        }
        for name, question in asked.items():
            self.assertEqual(section_id(question), name, question)
            text = answer_text(question, True, True, root, NOW)
            self.assertIn("## ", text, question)
            self.assertIn("Why:", text, question)
            self.assertIn("Owner:", text, question)
            self.assertIn("Coverage:", text, question)

    def test_a_combined_daily_review_has_all_ten(self):
        text = answer_text("how did we do yesterday", True, True, _fixture(), NOW)
        for number in range(1, 11):
            self.assertIn(f"## {number}.", text)

    def test_missing_files_say_not_on_file(self):
        root = Path(tempfile.mkdtemp())
        text = answer_text("daily review", True, True, root, NOW)
        self.assertIn("yesterday's numbers land by 8:50 AM", text)
        self.assertIn("Not on file", text)

    def test_a_decline_is_not_called_ahead(self):
        text = answer_text("daily review", True, True, _fixture(with_net=True), NOW)
        growth = text.split("## 2.", 1)[1].split("## 3.", 1)[0]
        verdict = growth.split("**", 2)[1]
        self.assertTrue(verdict.startswith("De-growing"))
        self.assertNotIn("Growing", verdict)
        self.assertIn("down", growth.casefold())
        target = text.split("## 1.", 1)[1].split("## 2.", 1)[0]
        self.assertIn("behind", target.casefold())
        self.assertNotIn("ahead", target.casefold())

    def test_store_net_uses_the_week_ratio_and_switches_to_the_column(self):
        estimated = answer_text("yesterday vs sales target", True, False, _fixture(with_net=False), NOW)
        self.assertIn("estimated net", estimated)
        self.assertIn("90% of gross", estimated)
        root = _fixture(with_net=True)
        path = root / "data" / "posist" / "daily_sales" / "sales_2026-11-23.csv"
        path.write_text(path.read_text(encoding="utf-8").replace("2026-11-23,700,900,8", "2026-11-23,700,,8"), encoding="utf-8")
        real = build(root, True, False, NOW)
        row = next(section for section in real["sections"] if section["id"] == "target")
        joined = " ".join(" ".join(item) for item in row["full_rows"])
        self.assertIn("estimated net", joined)
        self.assertNotIn("90% of gross", row["why"])

    def test_a_drift_above_half_a_point_is_flagged(self):
        root = _fixture(with_net=True)
        path = root / "data" / "posist" / "daily_sales" / "sales_2026-11-23.csv"
        text = path.read_text(encoding="utf-8")
        text = text.replace("2026-11-23,700,900,8", "2026-11-23,700,500,8")
        path.write_text(text, encoding="utf-8")
        built = build(root, True, False, NOW)
        row = next(section for section in built["sections"] if section["id"] == "target")
        joined = " ".join(" ".join(item) for item in row["full_rows"])
        self.assertIn("drift", joined)
        self.assertIn("posist net", joined)

    def test_marketing_lift_is_read_when_the_column_is_present(self):
        quiet = answer_text("what marketing is planned", False, False, _fixture(), NOW)
        self.assertIn("impact not measured yet", quiet.casefold())
        lifted = answer_text("what marketing is planned", False, False, _fixture(lift=True), NOW)
        self.assertIn("0.04", lifted)

    def test_tony_lift_sits_beside_reelo_and_spend_stays_with_the_owner(self):
        root = _fixture()
        _write(
            root / "data" / "marketing" / "marketing_lift.csv",
            "activity,scope,posist,comparison,reelo_attributed_inr,verdict,note\n"
            "Reelo Sunday,Network,-3.5% versus flanking Sundays,,370000,no measurable lift yet,messaged guests\n"
            "Meta ads,Five outlets,+0.6% versus 20-31 Oct,Other NCR -1.2%,,within noise,agency may have run October too\n",
        )
        _write(
            root / "data" / "marketing" / "marketing_activities.csv",
            "record_type,month,activity_name,type,stores_or_city,channel,start_date,end_date,budget_inr,actual_spend_or_attributed_inr,owner,status,expected_or_notes,sales_impact,source,source_date_ist\n"
            "budget,2026-11,November total,budget_total,Brand,,2026-11-01,2026-11-30,1760400,,Sanjoy,budget,Subhra approved; Siddhant approval requested,,mail,2026-11-24\n"
            "budget,2026-10,October total,budget_total,Brand,,2026-10-01,2026-10-31,1815000,,Sanjoy,budget,,,mail,2026-11-24\n"
            "budget,2026-11,Aggregators,ad,All,Swiggy,2026-11-01,2026-11-30,1300000,,Sanjoy,budget,October budget ₹12.00L,,mail,2026-11-24\n"
            "activity,2026-11,Cold Coffee reel,shoot,Brand,social,,,,,Nikita,in_progress,target 2 Nov,,sheet,2026-11-24\n",
        )
        owner = answer_text("what marketing is planned", True, False, root, NOW)
        ops = answer_text("what marketing is planned", False, False, root, NOW)
        self.assertIn("No measurable lift yet", owner)
        self.assertIn("within noise", owner)
        self.assertIn("Reelo-attributed, not measured lift", owner)
        self.assertIn("₹3.70 L", owner)
        self.assertIn("₹17.60 L", owner)
        self.assertIn("₹18.15 L", owner)
        self.assertIn("27 Nov", owner)
        self.assertIn("ROAS", owner)
        self.assertIn("Siddhant", owner)
        self.assertNotIn("₹17.60 L", ops)
        self.assertNotIn("₹13.00 L", ops)
        self.assertIn("within noise", ops)
        self.assertIn("Reelo-attributed, not measured lift", ops)

    def test_november_targets_match_tony_and_the_workbook(self):
        built = build(ROOT, True, True, datetime(2026, 11, 25, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
        target = next(section for section in built["sections"] if section["id"] == "target")
        self.assertIn("estimated net", target["why"])
        self.assertNotIn("Workbook mismatches", target["why"])
        self.assertIn("Faridabad", target["why"])
        from app.chat.daily_review import _targets
        rows = _targets(ROOT, "2026-11")
        self.assertEqual(len(rows), 29)
        self.assertEqual(sum(row["month"] for row in rows), Decimal(51250000))

    def test_the_answer_and_the_workbook_download_use_the_same_review(self):
        text = answer_from_data("daily review", {"role": "owner"}, True)["text"]
        self.assertIn("## 1.", text)
        self.assertNotIn("**So what**", text)
        report = build_report("give me a pdf of the daily review", {"role": "owner"}, True, text)
        self.assertEqual(report["title"], "Daily review")
        self.assertGreaterEqual(len(report["tables"]), 10)


if __name__ == "__main__":
    unittest.main()
