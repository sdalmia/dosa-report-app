import csv
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB.name
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from app.menu_ops.channels import build_channels, build_mix
from app.menu_ops.engineering import build_menu
from app.menu_ops.loader import file_stamp, load_channel_sales, load_sales
from app.menu_ops.tickets import build_tickets

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]

MENU_HEADER = "store,item,total_sales,total_orders,contribution_pct,period_start,period_end\n"
MIX = """store,item,total_sales,total_orders,contribution_pct,period_start,period_end
Ideal Plaza (01/0001),Star Dosa,500,50,50,2026-09-01,2026-09-30
Ideal Plaza (01/0001),Plow Idli,50,30,5,2026-09-01,2026-09-30
Ideal Plaza (01/0001),Puzzle Feast,400,5,40,2026-09-01,2026-09-30
Ideal Plaza (01/0001),Dog Chutney,50,15,5,2026-09-01,2026-09-30
Ideal Plaza (01/0001),Blank Item,,, ,2026-09-01,2026-09-30
"""


def _write(directory, name, text):
    path = Path(directory) / name
    path.write_text(text)
    return path


class LoaderTests(unittest.TestCase):
    def test_newest_dated_file_wins_and_quantity_is_not_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            _write(
                directory,
                "menu_mix_2026-08.csv",
                MENU_HEADER + "A,Old,10,1,100,2026-08-01,2026-08-31\n",
            )
            _write(
                directory,
                "menu_analysis_A_2026-10-08.csv",
                "item,total sales,total orders,% contribution,Sold Qty\nNew Dosa,80,8,100,99\n",
            )
            rows, warnings, sources = load_sales(directory)
            self.assertEqual(warnings, [])
            self.assertEqual([source["name"] for source in sources], ["menu_analysis_A_2026-10-08.csv"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["item"], "New Dosa")
            self.assertEqual(rows[0]["orders"], 8)
            self.assertEqual(rows[0]["quantity"], 99)
            self.assertNotEqual(rows[0]["orders"], rows[0]["quantity"])
            self.assertEqual(rows[0]["gross"], 80)

    def test_per_store_file_replaces_only_that_store(self):
        with tempfile.TemporaryDirectory() as directory:
            _write(
                directory,
                "menu_mix_2026-09.csv",
                MENU_HEADER
                + "Ideal Plaza (01/0001),Old Dosa,10,1,100,2026-09-01,2026-09-30\n"
                + "Connaught Place,Coffee,20,2,100,2026-09-01,2026-09-30\n",
            )
            _write(
                directory,
                "menu_analysis_Ideal_Plaza_2026-10.csv",
                "item,total sales,total orders,% contribution\nNew Dosa,90,9,100\n",
            )
            rows, _warnings, sources = load_sales(directory, posist_labels=["Ideal Plaza (01/0001)", "Connaught Place"])
            by_store = {}
            for row in rows:
                by_store.setdefault(row["store"], []).append(row["item"])
            self.assertEqual(by_store["Ideal Plaza (01/0001)"], ["New Dosa"])
            self.assertEqual(by_store["Connaught Place"], ["Coffee"])
            self.assertIn("menu_analysis_Ideal_Plaza_2026-10.csv", [source["name"] for source in sources])
            self.assertIn("menu_mix_2026-09.csv", [source["name"] for source in sources])

    def test_undated_torqus_is_not_the_sales_source(self):
        with tempfile.TemporaryDirectory() as directory:
            _write(directory, "categorywise_item_daily_sales_0063.csv", "Dish Name,Gross Sale\nButtermilk,10\n")
            rows, warnings, _sources = load_sales(directory)
            self.assertEqual(rows, [])
            self.assertTrue(warnings)

    def test_filename_date_orders_a_day_after_a_month(self):
        self.assertGreater(
            file_stamp(Path("menu_mix_2026-09-15.csv")),
            file_stamp(Path("menu_mix_2026-09.csv")),
        )
        self.assertGreater(
            file_stamp(Path("menu_mix_2026-10.csv")),
            file_stamp(Path("menu_mix_2026-09-30.csv")),
        )
        self.assertGreater(
            file_stamp(Path("channel_sales_2026-09-09_2026-10-08.csv")),
            file_stamp(Path("channel_sales_2026-10-01.csv")),
        )

    def test_two_dates_in_an_analysis_name_are_one_store(self):
        with tempfile.TemporaryDirectory() as directory:
            _write(
                directory,
                "menu_analysis_Ideal_Plaza_2026-09-09_2026-10-08.csv",
                "item,total sales,total orders,% contribution\nNew Dosa,90,9,100\n",
            )
            rows, _warnings, _sources = load_sales(directory)
            self.assertEqual(rows[0]["store"], "Ideal Plaza")
            self.assertEqual(rows[0]["period_start"].isoformat(), "2026-09-09")
            self.assertEqual(rows[0]["period_end"].isoformat(), "2026-10-08")

    def test_blank_category_column_hides_the_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            _write(
                directory,
                "menu_analysis_A_2026-10-08.csv",
                "item,category,total sales,total orders,% contribution\nButtermilk,,80,8,100\n",
            )
            _write(
                directory,
                "categorywise_item_daily_sales_0063.csv",
                "Dish Name,Gross Sale\nBeverages:\n1,Buttermilk,10\n",
            )
            view = build_menu(directory=directory, posist=Path(directory) / "missing.csv", procurement=directory)
            self.assertFalse(view["show_category"])
            self.assertEqual(view["items"][0]["category"], "")


class MatrixTests(unittest.TestCase):
    def test_quadrants_and_blank_orders_are_not_dogs(self):
        with tempfile.TemporaryDirectory() as directory:
            _write(directory, "menu_mix_2026-09.csv", MIX)
            view = build_menu(directory=directory, posist=Path(directory) / "missing.csv", procurement=directory)
            by_name = {}
            # Rebuild without the quadrant filter by reading counts and a full listing.
            full = build_menu(directory=directory, posist=Path(directory) / "missing.csv", procurement=directory)
            for item in full["items"]:
                by_name[item["item"]] = item
            self.assertEqual(by_name["Star Dosa"]["quadrant"], "star")
            self.assertEqual(by_name["Plow Idli"]["quadrant"], "plowhorse")
            self.assertEqual(by_name["Puzzle Feast"]["quadrant"], "puzzle")
            self.assertEqual(by_name["Dog Chutney"]["quadrant"], "dog")
            self.assertEqual(by_name["Blank Item"]["quadrant"], "")
            self.assertEqual(by_name["Blank Item"]["orders"], "")
            self.assertEqual(by_name["Blank Item"]["gross"], "")
            self.assertIn("Orders are missing", by_name["Blank Item"]["reason"])
            self.assertNotIn("0", by_name["Blank Item"]["orders"])
            self.assertIn("True margin is not on file", view["margin_note"])
            self.assertFalse(view["margin_mode"])
            self.assertEqual(by_name["Star Dosa"]["margin"], "")

    def test_base_cost_sets_margin_and_leaves_unpriced_outlets_empty(self):
        with tempfile.TemporaryDirectory() as menu_dir, tempfile.TemporaryDirectory() as cost_dir:
            _write(
                menu_dir,
                "menu_mix_2026-09.csv",
                MENU_HEADER
                + "Ideal Plaza (01/0001),Star Dosa,500,50,50,2026-09-01,2026-09-30\n"
                + "Ideal Plaza (01/0001),No Cost,100,10,10,2026-09-01,2026-09-30\n"
                + "GK1 Cloud Kitchen,Star Dosa,200,20,100,2026-09-01,2026-09-30\n"
                + "Ideal Plaza (01/0001),benne sada dosa,40,4,4,2026-09-01,2026-09-30\n",
            )
            _write(
                cost_dir,
                "menu_item_cost.csv",
                "outlet,item_name,recipe_tab,cost_per_portion_avg,has_unpriced_ingredient,cost_status,as_of\n"
                "Ideal Plaza,Star Dosa,base,4,True,partial_unpriced_ingredients,2026-10-09\n"
                "Ideal Plaza,No Cost,base,,False,no_priced_ingredients,2026-10-09\n"
                "GK1 Cloud Kitchen,Star Dosa,base,,True,no_priced_ingredients,2026-10-09\n"
                "Ideal Plaza,Plain Dosa,base,3,False,fully_priced,2026-10-09\n"
                "Ideal Plaza,Star Dosa,takeout,23,True,partial_unpriced_ingredients,2026-10-09\n",
            )
            _write(
                cost_dir,
                "menu_item_cost_channels_ideal_plaza.csv",
                "item_name,cost_base,cost_takeout,cost_delivery,cost_status\n"
                "Star Dosa,4,23,25,partial_unpriced_ingredients\n",
            )
            _write(
                cost_dir,
                "menu_item_cost_summary.csv",
                "item_name,min_cost_avg,median_cost_avg,max_cost_avg\nStar Dosa,4,4,4\n",
            )
            plaza = build_menu(
                directory=menu_dir,
                posist=Path(menu_dir) / "missing.csv",
                procurement=cost_dir,
                store="Ideal Plaza (01/0001)",
            )
            self.assertTrue(plaza["margin_mode"])
            by_name = {item["item"]: item for item in plaza["items"]}
            # 500/50 - 4 = 6. Takeout 23 and delivery 25 are shown and not subtracted.
            self.assertEqual(by_name["Star Dosa"]["margin"], "₹6")
            self.assertEqual(by_name["Star Dosa"]["recipe_cost"], "₹4")
            self.assertTrue(by_name["Star Dosa"]["partial"])
            self.assertEqual(by_name["Star Dosa"]["channel_costs"]["takeout"], "₹23")
            self.assertEqual(by_name["Star Dosa"]["channel_costs"]["delivery"], "₹25")
            self.assertFalse(by_name["Star Dosa"]["channel_costs"]["same"])
            self.assertEqual(by_name["No Cost"]["margin"], "")
            self.assertEqual(by_name["No Cost"]["recipe_cost"], "")
            self.assertIn("no priced ingredients", by_name["No Cost"]["reason"])
            self.assertEqual(plaza["unmatched_items"], 1)
            self.assertIn("benne sada dosa", plaza["unmatched_names"])
            self.assertEqual(by_name["benne sada dosa"]["margin"], "")

            kitchen = build_menu(
                directory=menu_dir,
                posist=Path(menu_dir) / "missing.csv",
                procurement=cost_dir,
                store="GK1 Cloud Kitchen",
            )
            dosa = next(item for item in kitchen["items"] if item["item"] == "Star Dosa")
            self.assertEqual(dosa["recipe_cost"], "")
            self.assertEqual(dosa["margin"], "")
            self.assertNotEqual(dosa["recipe_cost"], "₹0")

            both = build_menu(directory=menu_dir, posist=Path(menu_dir) / "missing.csv", procurement=cost_dir)
            both_dosa = next(item for item in both["items"] if item["item"] == "Star Dosa")
            # GK1 has no priced cost, so the margin uses Ideal Plaza only: still ₹6.
            self.assertEqual(both_dosa["margin"], "₹6")
            self.assertEqual(both_dosa["cost_coverage"], "1 of 2 stores")
            self.assertIsNone(both_dosa["channel_costs"])

    def test_a_real_zero_cost_is_kept(self):
        with tempfile.TemporaryDirectory() as menu_dir, tempfile.TemporaryDirectory() as cost_dir:
            _write(
                menu_dir,
                "menu_mix_2026-09.csv",
                MENU_HEADER + "Ideal Plaza,Free Dosa,100,10,100,2026-09-01,2026-09-30\n",
            )
            _write(
                cost_dir,
                "menu_item_cost.csv",
                "outlet,item_name,recipe_tab,cost_per_portion_avg,has_unpriced_ingredient,cost_status\n"
                "Ideal Plaza,Free Dosa,base,0,False,fully_priced\n",
            )
            view = build_menu(directory=menu_dir, posist=Path(menu_dir) / "missing.csv", procurement=cost_dir)
            item = view["items"][0]
            self.assertEqual(item["recipe_cost"], "₹0")
            self.assertEqual(item["margin"], "₹10")

    def test_example_channel_numbers_are_not_in_the_source(self):
        text = "\n".join(
            path.read_text(errors="replace")
            for path in (ROOT / "app" / "menu_ops").rglob("*")
            if path.suffix in {".py", ".html", ".css"}
        )
        self.assertNotIn("60619", text)
        self.assertNotIn("42058", text)
        self.assertNotIn("24744", text)


class ChannelTests(unittest.TestCase):
    def test_ratings_sort_worst_zomato_delivery_first_and_keep_blanks(self):
        view = build_channels()
        self.assertTrue(view["ratings_present"])
        self.assertIn("Manisquare", view["ratings"][0]["store"])
        self.assertEqual(view["ratings"][0]["zomato_delivery"], "4.0")
        self.assertIn("Forum", view["ratings"][-1]["store"])
        self.assertEqual(view["ratings"][-1]["zomato_delivery"], "")
        faridabad = next(row for row in view["ratings"] if "Faridabad" in row["store"])
        self.assertEqual(faridabad["google"], "4")
        self.assertEqual(len(view["ratings"]), 25)
        self.assertFalse(view["sales_present"])
        self.assertTrue(any("Channel sales" in warning for warning in view["sales_warnings"]))
        self.assertIn("commission", view["payout_note"].lower())

    def test_sales_mix_uses_gross_and_does_not_treat_a_blank_as_zero(self):
        mix = build_mix(
            [
                {"channel": "POS", "gross": 100, "orders": 10, "when": ""},
                {"channel": "POS", "gross": 10, "orders": None, "when": ""},
                {"channel": "Zomato", "gross": 40, "orders": 5, "when": ""},
            ]
        )
        by_name = {row["channel"]: row for row in mix["channels"]}
        self.assertEqual(by_name["POS"]["orders"], "")
        self.assertEqual(by_name["POS"]["gross"], "₹110")
        self.assertEqual(by_name["Zomato"]["orders_share"], "")

    def test_period_totals_ignore_daily_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            _write(
                directory,
                "channel_sales_2026-09-09_2026-10-08.csv",
                "date,period_from,period_to,store,channel,gross,orders\n"
                ",2026-09-09,2026-10-08,Ideal Plaza,POS,100,10\n"
                ",2026-09-09,2026-10-08,Ideal Plaza,Zomato,40,5\n"
                ",2026-09-09,2026-10-08,Ideal Plaza,Swiggy,20,\n"
                "2026-10-08,2026-09-09,2026-10-08,Ideal Plaza,POS,999,1\n"
                "2026-10-08,2026-09-09,2026-10-08,Ideal Plaza,Rapido,3,1\n"
                "not-a-date,2026-09-09,2026-10-08,Ideal Plaza,POS,5,1\n",
            )
            view = build_channels(famepilot=directory, channels=directory)
            by_name = {row["channel"]: row for row in view["mix"]["channels"]}
            self.assertEqual(by_name["POS"]["gross"], "₹100")
            self.assertEqual(by_name["POS"]["orders"], "10")
            self.assertEqual(by_name["POS"]["apb"], "₹10")
            self.assertEqual(by_name["Swiggy"]["orders"], "")
            self.assertEqual(by_name["Swiggy"]["apb"], "")
            self.assertNotIn("Rapido", by_name)
            self.assertEqual(view["period_label"], "9 Sep–8 Oct 2026")
            days = {day["when"]: day for day in view["trend"]}
            self.assertIn("not-a-date", days)
            daily_names = {row["channel"] for row in days["2026-10-08"]["channels"]}
            self.assertIn("Rapido", daily_names)
            self.assertIn("999", days["2026-10-08"]["channels"][0]["gross"] + days["2026-10-08"]["channels"][-1]["gross"])

    def test_missing_sales_file_names_the_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            loaded = load_channel_sales(directory)
            self.assertFalse(loaded["present"])
            self.assertIn("POS", loaded["warnings"][0])
            self.assertIn("gross", loaded["warnings"][0])


class TicketTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 9, 22, 0, tzinfo=IST)

    def test_real_file_lists_every_case_open_and_flags_by_age(self):
        view = build_tickets(now=self.now)
        self.assertEqual(view["counts"]["cases"], 81)
        self.assertEqual(view["counts"]["open"], 81)
        self.assertTrue(all(case["status"] == "" for case in view["cases"]))
        self.assertTrue(all(case["owner"] == "" for case in view["cases"]))
        self.assertTrue(all(case["resolved_at"] == "" for case in view["cases"]))
        self.assertTrue(all(case["tracker"] == "Open" for case in view["cases"]))
        self.assertTrue(all(case["platform"] for case in view["cases"]))
        self.assertTrue(all(case["customer"] for case in view["cases"]))
        self.assertEqual(sum(1 for case in view["cases"] if not case["rating"]), 23)
        self.assertTrue(all(case["age_basis"] == "since post" for case in view["cases"]))
        self.assertTrue(all(case["age"] for case in view["cases"]))
        stale = next(row for row in view["keywords"] if row["keyword"] == "Stale")
        self.assertEqual(stale["count"], 48)
        self.assertGreaterEqual(view["hotspots"][0]["count"], 2)
        self.assertIn("Ideal Plaza", view["hotspots"][0]["store"])
        self.assertIn("review console", view["open_note"])
        self.assertIn("Rating is on reviews", view["rating_note"])
        self.assertNotIn("console export", view["open_note"])

    def test_age_falls_back_to_the_alert_and_24_hours_is_not_over(self):
        with tempfile.TemporaryDirectory() as directory:
            _write(
                directory,
                "tickets.csv",
                "date_time,store,platform,rating,keyword,customer,status,owner,resolved_at\n"
                "2026-10-09 10:00,Store A,zomato,1,hair,Asha,,,\n"
                "2026-10-08 10:00,Store A,swiggy,,stale,Ravi,,,\n"
                "2026-10-07 10:00,Store B,google,,fungus,Neel,,,\n",
            )
            _write(
                directory,
                "tickets_source_detail.csv",
                "date_time,store,type,review_time_ist,message_id,detail_source,dup_message_ids\n"
                "2026-10-09 10:00,Store A,review,,m1,email body,\n"
                "2026-10-08 10:00,Store A,complaint,2026-10-09 10:00,m2,email body,\n"
                "2026-10-07 10:00,Store B,review,2026-10-08 21:00,m3,email body,\n",
            )
            now = datetime(2026, 10, 9, 22, 0, tzinfo=IST)
            view = build_tickets(directory=directory, now=now)
            by_keyword = {case["keyword"]: case for case in view["cases"]}
            # No post time: age since the alert at 10:00, which is 12 hours.
            self.assertEqual(by_keyword["hair"]["age_basis"], "since alert")
            self.assertEqual(by_keyword["hair"]["over_24_label"], "No")
            self.assertEqual(by_keyword["hair"]["rating"], "1")
            # Post time is used even though the alert is older. 10:00 to 22:00 is 12 hours.
            self.assertEqual(by_keyword["stale"]["age_basis"], "since post")
            self.assertEqual(by_keyword["stale"]["rating"], "")
            self.assertEqual(by_keyword["stale"]["over_24_label"], "No")
            # 21:00 on 8 Oct to 22:00 on 9 Oct is 25 hours.
            self.assertEqual(by_keyword["fungus"]["over_24_label"], "Yes")
            self.assertEqual(view["hotspots"][0]["store"], "Store A")
            self.assertEqual(len(view["hotspots"]), 1)

    def test_missing_ticket_file_names_the_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            view = build_tickets(directory=directory, now=self.now)
            self.assertFalse(view["present"])
            self.assertIn("resolved_at", view["warnings"][0])
            self.assertIn("review_time_ist", view["warnings"][0])


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Asha Rao", "email": "asha@dosacoffee.com"}

    def test_pages_render_real_data_and_empty_states(self):
        menu = self.client.get("/menu")
        self.assertEqual(menu.status_code, 200)
        html = menu.get_data(as_text=True)
        self.assertIn("Gross", html)
        self.assertIn("Star", html)
        self.assertIn("excl. packaging", html)
        self.assertIn("Masala Dosa", html)
        self.assertNotIn("60619", html)
        self.assertNotIn("Buttermilk - 200ml", html)
        self.assertNotIn(".csv", html)
        self.assertNotRegex(html, r"\bblank\b")
        self.assertNotIn('data-theme="dark"', html)

        channels = self.client.get("/channels")
        self.assertEqual(channels.status_code, 200)
        page = channels.get_data(as_text=True)
        self.assertIn("Zomato Delivery", page)
        self.assertIn("Not a 30-day average", page)
        self.assertIn("not in yet", page)
        self.assertIn("Payouts after commission", page)
        self.assertNotIn("60619", page)
        self.assertNotIn(".csv", page)
        self.assertNotRegex(page, r"\bblank\b")

        tickets = self.client.get("/tickets")
        self.assertEqual(tickets.status_code, 200)
        board = tickets.get_data(as_text=True)
        self.assertIn("Open", board)
        self.assertIn("Stale", board)
        self.assertIn("since post", board)
        self.assertIn("review console", board)
        self.assertIn(">Status<", board)
        self.assertNotIn(".csv", board)
        self.assertNotRegex(board, r"\bblank\b")

        dashboard = self.client.get("/dashboard")
        self.assertIn("/menu", dashboard.get_data(as_text=True))
        self.assertIn("/channels", dashboard.get_data(as_text=True))
        self.assertIn("/tickets", dashboard.get_data(as_text=True))

    def test_theme_does_not_follow_the_operating_system(self):
        css = (ROOT / "app" / "menu_ops" / "static" / "menu_ops.css").read_text()
        self.assertNotIn("prefers-color-scheme", css)

    def test_real_recipe_costs_match_names_exactly(self):
        view = build_menu()
        self.assertTrue(view["margin_mode"])
        self.assertGreater(view["unmatched_items"], 0)
        self.assertIn("benne sada dosa", [name.casefold() for name in view["unmatched_names"]])
        self.assertIn("packaging charge", [name.casefold() for name in view["unmatched_names"]])
        outlets = " ".join(view["unmatched_outlets"]).casefold()
        self.assertIn("swiming", outlets)
        self.assertIn("salt lake sec-1", outlets)
        self.assertNotIn("salt lake sec-3", outlets)
        plaza = build_menu(store="Ideal Plaza (01/0001)")
        priced = [item for item in plaza["items"] if item["recipe_cost"] and item["recipe_cost"] != "Not on the report"]
        self.assertTrue(priced)
        self.assertTrue(any(item["channel_costs"] for item in priced))
        self.assertTrue(any(item["partial"] for item in priced))

    def test_login_required(self):
        with self.client.session_transaction() as sess:
            sess.pop("user", None)
        response = self.client.get("/tickets")
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
