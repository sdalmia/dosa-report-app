import csv
import os
import tempfile
import unittest

from tests.stitch import page, stitch
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB.name
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from app.owner_tools.metrics import (
    audit_score,
    bills_score,
    build_brief,
    build_goals,
    build_labour,
    build_scorecard,
    combine,
    percent_change,
    productivity_scores,
    rating_score,
    sales_score,
    wastage_score,
)
from app.owner_tools.sources import (
    clear_procurement_scan_cache,
    load_goals,
    load_wastage,
    scan_famepilot,
    scan_procurement,
)
from app.owner_tools.text import render_brief_text
from app.store_health.contract import load_feeds

POSIST_HEADER = (
    "store,date,net,gross,bills,apb,net_wow_pct,bills_wow_pct,apb_wow_pct,"
    "net_last_same_weekday,bills_last_same_weekday,apb_last_same_weekday,"
    "unsettled_bills,unsettled_amount,void_bills,source,provisional,region"
)
CALENDAR_HEADER = (
    "store,date,weekday,tier,pred_low,pred_high,pred_mid,actual_net,"
    "variance_vs_mid,variance_pct,status,drivers,notes"
)


def component(store, key):
    for part in store["components"]:
        if part["key"] == key:
            return part
    raise AssertionError(key)


class ScoreMathTests(unittest.TestCase):
    def test_missing_inputs_stay_blank_and_a_real_zero_scores(self):
        self.assertIsNone(percent_change(None, 8))
        self.assertIsNone(percent_change(8, None))
        self.assertIsNone(percent_change(8, 0))
        self.assertIsNone(sales_score(None, 800))
        self.assertIsNone(sales_score(1000, None))
        self.assertIsNone(sales_score(1000, 0))
        self.assertEqual(sales_score(0, 800), 0)
        self.assertEqual(sales_score(1000, 800), 125)
        self.assertIsNone(bills_score(None, 8))
        self.assertEqual(bills_score(0, 8), 0)
        self.assertEqual(bills_score(10, 8), 125)
        self.assertEqual(bills_score(8, 8), 100)
        self.assertIsNone(rating_score(None))
        self.assertEqual(rating_score(0), 0)
        self.assertEqual(rating_score(4), 80)
        self.assertIsNone(rating_score(6))
        self.assertIsNone(audit_score(""))
        self.assertIsNone(audit_score("not in cycle"))
        self.assertIsNone(audit_score("not provided in one-pager"))
        self.assertEqual(audit_score("0%"), 0)
        self.assertEqual(audit_score("88.3%"), 88.3)
        self.assertIsNone(wastage_score(None))
        self.assertEqual(wastage_score(0), 100)
        self.assertEqual(wastage_score(10), 90)

    def test_reweight_drops_missing_parts_and_keeps_a_real_zero(self):
        composite, parts = combine(
            [
                {"key": "sales", "weight": 25, "score": 50},
                {"key": "bills", "weight": 15, "score": 100},
                {"key": "rating", "weight": 20, "score": None},
                {"key": "waste", "weight": 10, "score": 0},
            ]
        )
        self.assertAlmostEqual(composite, (50 * 25 + 100 * 15 + 0 * 10) / 50)
        by_key = {part["key"]: part for part in parts}
        self.assertFalse(by_key["rating"]["included"])
        self.assertIsNone(by_key["rating"]["effective_weight"])
        self.assertTrue(by_key["waste"]["included"])
        self.assertAlmostEqual(by_key["sales"]["effective_weight"], 50)

    def test_productivity_index_skips_blank_counts(self):
        scores, median = productivity_scores({"Alpha": 180, "Beta": None, "Gamma": 30})
        self.assertEqual(median, 105)
        self.assertIsNone(scores["Beta"])
        self.assertAlmostEqual(scores["Alpha"], 180 / 105 * 100)
        self.assertAlmostEqual(scores["Gamma"], 30 / 105 * 100)

    def test_all_missing_components_leave_the_store_unscored(self):
        composite, parts = combine(
            [
                {"key": "sales", "weight": 25, "score": None},
                {"key": "bills", "weight": 15, "score": None},
            ]
        )
        self.assertIsNone(composite)
        self.assertTrue(all(part["included"] is False for part in parts))


class OwnerFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        self.data = tempfile.TemporaryDirectory()
        self.goals = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        self.procurement = tempfile.TemporaryDirectory()
        os.environ["STORE_HEALTH_DATA_DIR"] = self.data.name
        os.environ["OWNER_GOALS_FILE"] = self.goals.name
        os.environ["OWNER_PROCUREMENT_DIR"] = self.procurement.name
        os.environ.pop("OWNER_WASTAGE_FILE", None)
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant Dalmia", "email": "siddhant@dosacoffee.com"}
        self.write_feeds()

    def tearDown(self):
        os.environ.pop("STORE_HEALTH_DATA_DIR", None)
        os.environ.pop("OWNER_GOALS_FILE", None)
        os.environ.pop("OWNER_PROCUREMENT_DIR", None)
        os.environ.pop("OWNER_WASTAGE_FILE", None)
        self.data.cleanup()
        self.procurement.cleanup()
        Path(self.goals.name).unlink(missing_ok=True)

    def write(self, name, text):
        Path(self.data.name, name).write_text(text, encoding="utf-8")

    def write_feeds(self):
        self.write(
            "posist_daily.csv",
            POSIST_HEADER
            + "\n"
            + "\n".join(
                [
                    "Alpha,2026-10-01,,800,8,100,,,,,,,,,,historical,false,North",
                    "Alpha,2026-10-08,999,1000,10,100,50,,,,,,,,,,historical,false,North",
                    "Beta,2026-10-01,,500,5,100,,,,,,,,,,historical,false,East",
                    "Beta,2026-10-08,,500,5,100,,,,,,,,,,historical,false,East",
                    "Gamma,2026-10-01,,200,4,50,,,,,,,,,,historical,false,East",
                    "Gamma,2026-10-08,,100,2,50,,,,,,,,,,historical,false,East",
                ]
            )
            + "\n",
        )
        self.write(
            "sales_pred_vs_actual.csv",
            CALENDAR_HEADER
            + "\n"
            + "Alpha,2026-10-08,Thursday,Normal,700,900,800,,,,share_of_network_band,Working weekday,note\n"
            + "Beta,2026-10-08,Thursday,Normal,800,1200,1000,,,,share_of_network_band,Working weekday,note\n"
            + "Gamma,2026-10-08,Thursday,Normal,80,120,100,,,,share_of_network_band,Working weekday,note\n"
            + "Alpha,2026-10-17,Saturday,Festival,1,2,1.5,,,,share_of_network_band,Durga Puja peak band,note\n"
            + "Alpha,2026-10-31,Saturday,Festival,1,2,1.5,,,,share_of_network_band,Normal Saturday + light Diwali-prep uplift,note\n",
        )
        self.write(
            "famepilot.csv",
            "posist_store,famepilot_location,rating,review_count,main_threat,private_rating,private_review_count,overall_reviews\n"
            "Alpha,Alpha,4.0,10,Emergency: gas leak,3,1,11\n"
            "Beta,Beta,,,,, \n"
            "Gamma,Gamma,5,2,\"Pest in the kitchen, food safety\",4,1,3\n",
        )
        self.write(
            "mystery_audit.csv",
            "store,period,avg_score,weekday_score,weekend_score,note,status\n"
            "Alpha,August 2026,80%,not provided,not provided,Scored,scored\n"
            "Beta,August 2026,not in cycle,not in cycle,not in cycle,Out,not in cycle\n",
        )
        self.write(
            "keka_active.csv",
            "posist_store,active_employees,keka_location,match_status,definition\n"
            "Alpha,10,Alpha,matched,snapshot\n"
            "Beta,,Beta,unmatched,snapshot\n"
            "Gamma,10,Gamma,matched,snapshot\n",
        )
        Path(self.goals.name).write_text(
            "store,month,target_gross\nAlpha,2026-10,4000\n",
            encoding="utf-8",
        )

    def feeds(self):
        return load_feeds(self.data.name)

    def test_brief_uses_gross_and_leaves_net_blank(self):
        payload = build_brief(self.feeds(), scan_famepilot(self.data.name), scan_procurement())
        self.assertEqual(payload["as_of"], "2026-10-08")
        self.assertIsNone(payload["net"])
        self.assertEqual(payload["sales_basis"], "gross")
        self.assertAlmostEqual(payload["network"]["gross"]["value"], 1600)
        self.assertAlmostEqual(payload["network"]["bills"]["value"], 17)
        self.assertAlmostEqual(payload["network"]["apb"]["value"], 1600 / 17)
        self.assertEqual(payload["network"]["apb_label"], "APB")
        alpha = next(store for region in payload["regions"] for store in region["stores"] if store["label"] == "Alpha")
        self.assertAlmostEqual(alpha["gross"]["value"], 1000)
        self.assertNotEqual(alpha["gross"]["value"], 999)
        self.assertAlmostEqual(alpha["gross_change_pct"]["value"], 25)
        self.assertAlmostEqual(alpha["apb"]["value"], 100)
        self.assertEqual(payload["worst_vs_mid"][0]["label"], "Beta")
        self.assertAlmostEqual(payload["worst_vs_mid"][0]["variance_pct"]["value"], -50)
        self.assertEqual(payload["worst_vs_last_week"][0]["label"], "Gamma")
        self.assertEqual(payload["food_safety"][0]["store"], "Gamma")
        self.assertEqual(payload["emergency"][0]["store"], "Alpha")
        self.assertEqual(payload["procurement"], [])
        self.assertIn("No procurement flags yet", payload["procurement_empty"])
        text = render_brief_text(payload)
        self.assertIn("Sales are gross", text)
        self.assertNotIn("Nothing is sent", text)
        self.assertNotIn("999", text)

    def test_scorecard_reweights_and_does_not_zero_a_blank(self):
        payload = build_scorecard(self.feeds(), load_wastage(self.data.name), "2026-10")
        stores = {store["label"]: store for store in payload["stores"]}
        alpha = stores["Alpha"]
        beta = stores["Beta"]
        gamma = stores["Gamma"]
        self.assertAlmostEqual(component(alpha, "sales_vs_mid")["score"]["value"], 125)
        self.assertAlmostEqual(component(alpha, "bills_wow")["score"]["value"], 125)
        self.assertAlmostEqual(component(alpha, "famepilot")["score"]["value"], 80)
        self.assertAlmostEqual(component(alpha, "audit")["score"]["value"], 80)
        self.assertAlmostEqual(component(alpha, "productivity")["score"]["value"], 180 / 105 * 100)
        self.assertIsNone(component(alpha, "wastage")["score"]["value"])
        self.assertFalse(component(alpha, "wastage")["included"])
        self.assertIsNone(component(beta, "famepilot")["score"]["value"])
        self.assertFalse(component(beta, "famepilot")["included"])
        self.assertIsNone(component(beta, "audit")["score"]["value"])
        self.assertIsNone(component(beta, "productivity")["score"]["value"])
        self.assertAlmostEqual(component(beta, "sales_vs_mid")["score"]["value"], 50)
        self.assertAlmostEqual(component(beta, "bills_wow")["score"]["value"], 100)
        self.assertAlmostEqual(beta["score"]["value"], (50 * 25 + 100 * 15) / 40)
        self.assertIsNone(component(gamma, "audit")["score"]["value"])
        self.assertEqual(stores["Alpha"]["rank"], 1)
        self.assertTrue(all(store["rank"] is not None for store in payload["stores"]))
        weights = {item["key"]: item["weight"] for item in payload["weights"]}
        self.assertEqual(weights, {
            "sales_vs_mid": 25,
            "bills_wow": 15,
            "famepilot": 20,
            "audit": 15,
            "productivity": 15,
            "wastage": 10,
        })

    def test_wastage_percent_joins_the_score_and_a_bare_amount_does_not(self):
        path = Path(self.data.name, "wastage.csv")
        path.write_text("store,month,wastage_pct,wastage_amount\nAlpha,2026-10,10,500\nGamma,2026-10,,250\n", encoding="utf-8")
        payload = build_scorecard(self.feeds(), load_wastage(self.data.name), "2026-10")
        stores = {store["label"]: store for store in payload["stores"]}
        self.assertAlmostEqual(component(stores["Alpha"], "wastage")["score"]["value"], 90)
        self.assertTrue(component(stores["Alpha"], "wastage")["included"])
        self.assertIsNone(component(stores["Gamma"], "wastage")["score"]["value"])
        self.assertIn("not scored", component(stores["Gamma"], "wastage")["raw"])
        self.assertIsNone(component(stores["Beta"], "wastage")["score"]["value"])

    def test_labour_leaves_unmatched_stores_blank(self):
        payload = build_labour(self.feeds())
        stores = {store["label"]: store for store in payload["stores"]}
        self.assertEqual(stores["Alpha"]["employees"]["value"], 10)
        self.assertAlmostEqual(stores["Alpha"]["day_gross_per"]["value"], 100)
        self.assertAlmostEqual(stores["Alpha"]["day_bills_per"]["value"], 1)
        self.assertAlmostEqual(stores["Alpha"]["mtd_gross_per"]["value"], 180)
        self.assertIsNone(stores["Beta"]["employees"]["value"])
        self.assertIsNone(stores["Beta"]["day_gross_per"]["value"])
        self.assertIsNone(stores["Beta"]["day_bills_per"]["value"])
        self.assertIsNone(stores["Beta"]["mtd_gross_per"]["value"])
        self.assertAlmostEqual(stores["Beta"]["day_gross"]["value"], 500)
        self.assertAlmostEqual(payload["network"]["gross_per"]["value"], (1000 + 100) / 20)

    def test_goals_bar_needs_a_target_and_festive_mode_uses_driver_text(self):
        payload = build_goals(self.feeds(), load_goals(), "2026-10", True)
        stores = {store["label"]: store for store in payload["stores"]}
        self.assertAlmostEqual(stores["Alpha"]["mtd_gross"]["value"], 1800)
        self.assertAlmostEqual(stores["Alpha"]["target"]["value"], 4000)
        self.assertAlmostEqual(stores["Alpha"]["progress_pct"]["value"], 45)
        self.assertEqual(stores["Alpha"]["bar_pct"], 45)
        self.assertIsNone(stores["Beta"]["target"]["value"])
        self.assertIsNone(stores["Beta"]["bar_pct"])
        self.assertIn("No target for this month", stores["Beta"]["empty"])
        dates = {day["iso"]: day for day in payload["festive_dates"]}
        self.assertEqual(dates["2026-10-17"]["kinds"], ["Puja"])
        self.assertIn("Puja", dates["2026-10-17"]["driver"])
        self.assertEqual(dates["2026-10-31"]["kinds"], ["Diwali"])
        self.assertNotIn("2026-10-08", dates)
        off = build_goals(self.feeds(), load_goals(), "2026-10", False)
        self.assertFalse(off["festive_on"])
        self.assertTrue(off["festive_dates"])

    def test_pages_render_the_fixture(self):
        brief = self.client.get("/brief")
        self.assertEqual(brief.status_code, 200)
        html = stitch(self.client, brief.get_data(as_text=True))
        self.assertIn("total gross divided by total bills", html)
        self.assertIn("No procurement flags yet", html)
        self.assertNotIn("posist_daily.csv", html)
        self.assertNotIn("Email HTML", html)
        self.assertNotIn("brief.json", html)
        self.assertIn("Pest in the kitchen, food safety", html)
        self.assertIn("Emergency: gas leak", html)
        scorecard = self.client.get("/scorecard")
        self.assertEqual(scorecard.status_code, 200)
        scorecard_html = stitch(self.client, scorecard.get_data(as_text=True))
        self.assertIn("Not scored as zero", scorecard_html)
        self.assertIn("/store-health/alpha", scorecard_html)
        goals = self.client.get("/goals")
        self.assertEqual(goals.status_code, 200)
        goals_html = stitch(self.client, goals.get_data(as_text=True))
        self.assertIn("Durga Puja peak band", goals_html)
        self.assertIn("No target for this month", goals_html)
        hidden = self.client.get("/goals?festive=0")
        self.assertNotIn("Durga Puja peak band", stitch(self.client, hidden.get_data(as_text=True)))
        email = self.client.get("/brief/email")
        self.assertNotIn("Nothing is sent", email.get_data(as_text=True))
        self.assertIn("Gross sales", email.get_data(as_text=True))
        text = self.client.get("/brief.txt")
        self.assertEqual(text.mimetype, "text/plain")
        self.assertIn("Sales are gross", text.get_data(as_text=True))


class ShippedOwnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        os.environ.pop("STORE_HEALTH_DATA_DIR", None)
        os.environ.pop("OWNER_GOALS_FILE", None)
        os.environ.pop("OWNER_PROCUREMENT_DIR", None)
        os.environ.pop("OWNER_WASTAGE_FILE", None)
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant Dalmia", "email": "siddhant@dosacoffee.com"}

    def test_goals_file_is_headers_only(self):
        path = Path(__file__).resolve().parents[1] / "data" / "goals.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(rows, [["store", "month", "target_gross"]])

    def test_login_is_required(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        response = self.client.get("/brief")
        self.assertEqual(response.status_code, 302)

    def test_shipped_brief_json_and_renders(self):
        response = self.client.get("/brief.json")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNone(payload["net"])
        self.assertEqual(payload["sales_basis"], "gross")
        self.assertIsNotNone(payload["as_of"])
        gross = payload["network"]["gross"]["value"]
        bills = payload["network"]["bills"]["value"]
        apb = payload["network"]["apb"]["value"]
        self.assertGreater(gross, 0)
        self.assertGreater(bills, 0)
        self.assertGreater(apb, 0)
        # Mall food-court gross stays in the total. Their bills do not, so APB is not gross divided by every bill.
        self.assertNotAlmostEqual(apb, gross / bills, places=1)
        forum = next(
            store for region in payload["regions"] for store in region["stores"] if "Forum" in store["label"]
        )
        self.assertTrue(forum["mall_bills"])
        self.assertIsNone(forum["apb"]["value"])
        self.assertIsNone(forum["bills_change_pct"]["value"])
        self.assertLessEqual(len(payload["worst_vs_mid"]), 5)
        self.assertGreater(len(payload["worst_vs_mid"]), 0)
        variances = [item["variance_pct"]["value"] for item in payload["worst_vs_mid"]]
        self.assertEqual(variances, sorted(variances))
        week = [item["variance_pct"]["value"] for item in payload["worst_vs_last_week"]]
        self.assertEqual(week, sorted(week))
        self.assertEqual(payload["food_safety"], [])
        self.assertEqual(payload["emergency"], [])
        self.assertEqual(payload["procurement"], [])
        self.assertIn("No food-safety notes", payload["food_safety_empty"])
        self.assertIn("No procurement flags yet", payload["procurement_empty"])
        brief_html = stitch(self.client, self.client.get("/brief").get_data(as_text=True))
        self.assertIn("Gross sales", brief_html)
        self.assertIn(">APB<", brief_html)
        self.assertNotIn("posist_daily.csv", brief_html)
        self.assertNotIn("Email HTML", brief_html)
        self.assertNotIn("Plain text", brief_html)
        self.assertNotIn('class="card"', brief_html)
        self.assertIn('content="#f7f6f3"', brief_html)
        self.assertIn('stored === "dark" ? "dark" : "light"', brief_html)
        self.assertNotIn("prefers-color-scheme", brief_html)
        self.assertNotIn('aria-label="Owner tools"', brief_html)
        self.assertEqual(brief_html.count('aria-label="Primary"'), 1)
        self.assertEqual(brief_html.count("<header"), 1)
        text = self.client.get("/brief.txt")
        self.assertEqual(text.mimetype, "text/plain")
        self.assertIn("Sales are gross", text.get_data(as_text=True))
        self.assertNotIn("Nothing is sent", text.get_data(as_text=True))
        email = self.client.get("/brief/email").get_data(as_text=True)
        self.assertNotIn("Nothing is sent", email)
        self.assertIn("Gross sales", email)

    def test_shipped_scorecard_labour_and_goals(self):
        scorecard = page(self.client, "/scorecard")
        self.assertIn("No wastage figure yet", scorecard)
        self.assertIn("Not scored as zero", scorecard)
        self.assertIn("Sales vs forecast mid", scorecard)
        self.assertIn('href="/store-health/', scorecard)
        shalimar = scorecard.split('data-store="Shalimar Bagh (02/0015)"', 1)[1].split("</article>", 1)[0]
        self.assertIn("Public rating is blank.", shalimar)
        self.assertIn('data-component="famepilot"', shalimar)
        fame = shalimar.split('data-component="famepilot"', 1)[1].split('data-component=', 1)[0]
        self.assertIn("Left out", fame)
        self.assertNotIn("Score 0.0", fame)
        labour = page(self.client, "/labour")
        salt = labour.split('data-store="Dosa Coffee - Salt Lake (002)"', 1)[1].split("</article>", 1)[0]
        employees = salt.split('data-field="employees"', 1)[1].split("</div>", 1)[0]
        per_person = salt.split('data-field="day-gross-per"', 1)[1].split("</div>", 1)[0]
        self.assertIn("Blank", employees)
        self.assertIn("Blank", per_person)
        self.assertIn("Staff count is blank", salt)
        goals = page(self.client, "/goals")
        self.assertIn("No targets yet", goals)
        self.assertIn("Durga Puja peak band", goals)
        self.assertIn("Diwali-prep", goals)
        self.assertIn("Sun 1 Nov 2026", goals)
        self.assertNotIn('role="progressbar"', goals)
        hidden = page(self.client, "/goals?festive=0")
        self.assertNotIn("Durga Puja peak band", hidden)
        self.assertIn("Festive days are hidden", hidden)


class ProcurementScanTests(unittest.TestCase):
    def test_cost_line_files_are_not_loaded_when_they_have_no_flag_column(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        # A long text column with no flag header. Reading every row is the spike.
        lines = ["outlet,item_name,receipt_ref"]
        lines.extend(f"Ideal Plaza,Masala Dosa,{'x' * 400}" for _ in range(500))
        Path(folder.name, "menu_item_cost_lines.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        Path(folder.name, "notes.csv").write_text(
            "store,status\nAlpha,late delivery\nBeta,match\n",
            encoding="utf-8",
        )
        previous = os.environ.get("OWNER_PROCUREMENT_DIR")
        os.environ["OWNER_PROCUREMENT_DIR"] = folder.name
        clear_procurement_scan_cache()

        def restore():
            if previous is None:
                os.environ.pop("OWNER_PROCUREMENT_DIR", None)
            else:
                os.environ["OWNER_PROCUREMENT_DIR"] = previous
            clear_procurement_scan_cache()

        self.addCleanup(restore)
        payload = scan_procurement()
        self.assertEqual(payload["items"], [{"file": "notes.csv", "store": "Alpha", "text": "status: late delivery"}])
        self.assertEqual(payload["empty"], "")
        again = scan_procurement()
        self.assertIs(again, payload)


if __name__ == "__main__":
    unittest.main()
