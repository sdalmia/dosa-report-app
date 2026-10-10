"""Things we make: batch recipes, dish costs, and use versus actual."""

import os
import tempfile
import unittest
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB.name
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.gaps import filter_gaps, load_gap_board
from app.menu_costing.batches import (
    batch_line_cost,
    batch_page_context,
    clear_batch_cache,
    load_batches,
    load_batch_use,
)
from app.menu_costing.recipes import clear_caches, load_recipes
from app.store_master import get_index

OWNER = "siddhant@dalgreenfoods.com"
ROOT = Path(__file__).resolve().parents[1]


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class BatchRecipeTests(unittest.TestCase):
    def setUp(self):
        clear_caches()
        clear_batch_cache()

    def test_live_cards_use_the_two_export_recipes_only(self):
        board = load_batches(ROOT / "data" / "procurement")
        cards = {(row["city"], row["item"]): row for row in board["cards"]}
        potato = cards[("Kolkata", "Potato Masala Bucket Outlet")]
        self.assertTrue(potato["has_recipe"])
        self.assertEqual(potato["yield_qty"], 4.5)
        self.assertEqual(potato["cost"], 42.98)
        names = [row["name"] for row in potato["ingredients"]]
        self.assertIn("Onion", names)
        self.assertIn("Boiled & Mashed Potato (1Pkt = 3Kg)", names)
        self.assertIn("RO Water", names)
        self.assertTrue(next(row["unpriced"] for row in potato["ingredients"] if row["name"] == "RO Water"))
        chutney = cards[("Delhi NCR", "Regular White Chutney Bucket Outlet")]
        self.assertTrue(chutney["has_recipe"])
        self.assertEqual(chutney["yield_qty"], 1.3)
        self.assertEqual(chutney["cost"], 79.53)
        batter = cards[("Kolkata", "Dosa Batter Mix")]
        self.assertFalse(batter["has_recipe"])
        self.assertIsNone(batter["cost"])
        imli = cards[("Kolkata", "Imli Water")]
        self.assertFalse(imli["has_recipe"])
        self.assertIsNone(imli["cost"])
        self.assertNotIn(("Kolkata", "Sambar Bucket - Delhi"), cards)
        self.assertIn(("Delhi NCR", "Sambar Bucket - Delhi"), cards)

    def test_live_batch_cost_reaches_a_dish_line_and_skips_the_inactive_name(self):
        self.assertAlmostEqual(batch_line_cost("Kolkata", "Potato Masala Bucket Outlet", 0.15, "Kg"), 0.15 * 42.98)
        self.assertIsNone(batch_line_cost("Kolkata", "Potato Masala Bucket Outlet (Inactive)", 0.15, "Kg"))
        self.assertIsNone(batch_line_cost("Kolkata", "Dosa Batter Mix", 0.2, "Kg"))
        recipes = load_recipes(ROOT / "data" / "procurement")
        ideal = recipes["by_outlet"][("Kolkata", "Ideal Plaza", "masala dosa")]
        self.assertEqual(ideal["cost"], 23.82)
        self.assertEqual(ideal["cost_kind"], "full")
        truck = recipes["by_outlet"][("Kolkata", "Food Truck - 1", "masala dosa")]
        self.assertEqual(truck["cost"], 10.9)
        self.assertEqual(truck["cost_kind"], "incomplete")
        self.assertEqual(truck["unpriced_excl"], 2)

    def test_a_future_recipe_completes_a_dish_and_a_blank_qty_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "menu_item_cost_estimated.csv",
                "outlet,city,item_name,recipe_tab,is_menu_item,still_unpriced_excl_ro_water_count,"
                "cost_status_estimated,cost_per_portion_estimated,still_unpriced_ingredients,baseline_note_estimated\n"
                "Ideal Plaza,Kolkata,Test Dosa,base,True,1,incomplete,,Dosa Batter Mix,row_cost_incomplete\n"
                "Ideal Plaza,Kolkata,Partial Dosa,base,True,2,incomplete,8,Dosa Batter Mix; Mint leaf,row_cost_incomplete\n",
            )
            _write(
                root / "menu_item_cost_lines.csv",
                "outlet,city,recipe_tab,item_name,is_menu_item,ingredient_name,ingredient_qty,ingredient_unit,"
                "ingredient_cost_avg,unpriced,recipe_qty,unit,is_inactive_ingredient\n"
                "Ideal Plaza,Kolkata,base,Test Dosa,True,Dosa Batter Mix,0.5,Kg,,True,1,No.,False\n"
                "Ideal Plaza,Kolkata,base,Partial Dosa,True,Dosa Batter Mix,0.5,Kg,,True,1,No.,False\n"
                "Ideal Plaza,Kolkata,base,Partial Dosa,True,Mint leaf,0.01,Kg,,True,1,No.,False\n"
                "Ideal Plaza,Kolkata,base,Onion Dish,True,Onion,1,Kg,20,False,1,No.,False\n",
            )
            _write(
                root / "batch_recipes.csv",
                "city,batch_item,ingredient,qty,unit,yield_qty,yield_unit,source,as_of\n"
                "Kolkata,Dosa Batter Mix,Onion,1,Kg,2,Kg,Sailesh,2026-10-01\n",
            )
            recipes = load_recipes(root)
            done = recipes["by_outlet"][("Kolkata", "Ideal Plaza", "test dosa")]
            self.assertEqual(done["cost_kind"], "full")
            self.assertEqual(done["cost"], 5)
            self.assertEqual(done["unpriced_names"], [])
            self.assertIn("before this batch cost", done["baseline_text"])
            partial = recipes["by_outlet"][("Kolkata", "Ideal Plaza", "partial dosa")]
            self.assertEqual(partial["cost_kind"], "incomplete")
            self.assertEqual(partial["cost"], 13)
            self.assertEqual(partial["unpriced_names"], ["Mint leaf"])
            batter = next(row for row in load_batches(root)["cards"] if row["item"] == "Dosa Batter Mix")
            self.assertTrue(batter["has_recipe"])
            self.assertEqual(batter["cost"], 10)

            _write(
                root / "batch_recipes.csv",
                "city,batch_item,ingredient,qty,unit,yield_qty,yield_unit,source,as_of\n"
                "Kolkata,Dosa Batter Mix,Onion,,Kg,2,Kg,Sailesh,2026-10-01\n",
            )
            clear_caches()
            priced = next(row for row in load_batches(root)["cards"] if row["item"] == "Dosa Batter Mix")
            self.assertTrue(priced["has_recipe"])
            self.assertIsNone(priced["cost"])

    def test_header_only_recipe_file_does_not_invent_a_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "menu_item_cost_lines.csv",
                "outlet,city,recipe_tab,item_name,is_menu_item,ingredient_name,ingredient_qty,ingredient_unit,unpriced\n"
                "Ideal Plaza,Kolkata,base,Masala Dosa,True,Imli Water,0.02,Ltr,True\n",
            )
            _write(
                root / "batch_recipes.csv",
                "city,batch_item,ingredient,qty,unit,yield_qty,yield_unit,source,as_of\n",
            )
            card = next(row for row in load_batches(root)["cards"] if row["item"] == "Imli Water")
            self.assertFalse(card["has_recipe"])
            self.assertIsNone(card["cost"])


class BatchUseTests(unittest.TestCase):
    def test_missing_files_are_data_coming(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = load_batch_use(root, root / "posist")
            self.assertFalse(bundle["available"])
            self.assertEqual(bundle["coming"], "Data coming")
            page = batch_page_context(
                city="Kolkata",
                store="",
                store_id="",
                query="",
                filters={},
                procurement=ROOT / "data" / "procurement",
                posist=root,
            )
            self.assertEqual(page["batch_use_note"], "Data coming")
            self.assertEqual(page["batch_threats"], [])
            self.assertFalse(page["batch_use_ready"])

    def test_variance_is_wastage_or_leakage_and_five_percent_is_not_a_threat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / "procurement"
            posist = root / "posist"
            period = "2026-09-09 to 2026-10-08"
            _write(
                posist / "batch_theoretical_use.csv",
                "store,batch_item,period,expected_qty,unit\n"
                f"Ideal Plaza,Potato Masala Bucket Outlet,{period},10,Kg\n"
                f"Ideal Plaza,Dosa Batter Mix,{period},100,Kg\n"
                f"Ideal Plaza,Imli Water,{period},10,Ltr\n"
                f"Ideal Plaza,Special Daal Bucket,{period},4,Kg\n"
                f"Connaught Place,Imli Water,{period},3,Ltr\n",
            )
            _write(
                proc / "batch_actual_use.csv",
                "store,batch_item,period,made_qty,issued_qty,unit,source\n"
                f"Ideal Plaza,Potato Masala Bucket Outlet,{period},12,12,Kg,kitchen\n"
                f"Ideal Plaza,Dosa Batter Mix,{period},105,105,Kg,kitchen\n"
                f"Ideal Plaza,Imli Water,{period},8,,Ltr,kitchen\n"
                f"Ideal Plaza,Special Daal Bucket,{period},, ,Kg,kitchen\n"
                f"Connaught Place,Imli Water,{period},9,9,Ltr,kitchen\n",
            )
            page = batch_page_context(
                city="Kolkata",
                store="Ideal Plaza",
                store_id="dosa-coffee-ideal-plaza-01-0001",
                query="",
                filters={},
                procurement=proc,
                posist=posist,
                recipes=ROOT / "data" / "procurement",
            )
            by_item = {row["item"]: row for row in page["batch_use_rows"]}
            self.assertNotIn("Imli Water", {row["item"] for row in page["batch_use_rows"] if row["store"] == "Connaught Place"})
            potato = by_item["Potato Masala Bucket Outlet"]
            self.assertEqual(potato["kind"], "Wastage")
            self.assertTrue(potato["threat"])
            self.assertEqual(potato["pct"], "20.0%")
            self.assertEqual(potato["rupee"], "₹86")
            self.assertEqual(potato["rupee_attr"], "85.96")
            self.assertEqual(potato["made"], "12 kg")
            batter = by_item["Dosa Batter Mix"]
            self.assertFalse(batter["threat"])
            self.assertEqual(batter["pct"], "5.0%")
            self.assertEqual(batter["rupee"], "")
            imli = by_item["Imli Water"]
            self.assertEqual(imli["kind"], "Leakage")
            self.assertTrue(imli["threat"])
            self.assertEqual(imli["issued_missing"], True)
            daal = by_item["Special Daal Bucket"]
            self.assertTrue(daal["actual_missing"])
            self.assertEqual(daal["actual"], "")
            self.assertFalse(daal["threat"])
            self.assertNotEqual(daal["qty"], "0")
            hidden = batch_page_context(
                city="Kolkata",
                store="",
                store_id="",
                query="",
                filters={"cc_range": "7"},
                procurement=proc,
                posist=posist,
                recipes=ROOT / "data" / "procurement",
            )
            self.assertIn("Data coming", hidden["batch_use_note"])
            self.assertEqual(hidden["batch_use_rows"], [])


class BatchVerdictTests(unittest.TestCase):
    def test_city_totals_follow_the_comparison_file(self):
        from app.menu_costing.batches import batch_page_context

        page = batch_page_context(city="", store="", store_id="", query="", filters={})
        kinds = [row["kind"] for row in page["batch_alerts"]]
        self.assertEqual(kinds[0], "physical")
        self.assertEqual(kinds[1], "recipe")
        self.assertIn("info", kinds)
        physical = page["batch_alerts"][0]
        figures = {pair["left_label"]: pair["left"] for pair in physical["pairs"]}
        self.assertEqual(figures["Jain sambar sent"], "2,594 L")
        self.assertEqual(figures["Dosa batter"], "900 kg short")
        self.assertEqual(figures["Benne batter"], "308 kg short")
        self.assertIn("Floor check by Sanjoy.", physical["action"])
        recipe = page["batch_alerts"][1]
        coconut = recipe["pairs"][0]
        self.assertEqual(coconut["left"], "+2,660 kg")
        self.assertEqual(coconut["right"], "₹5.9L")
        sambar = recipe["pairs"][1]
        self.assertEqual(sambar["left"], "+5,257 L")
        self.assertEqual(sambar["right"], "+102 kg")
        info = next(row for row in page["batch_alerts"] if row["kind"] == "info")
        self.assertEqual(info["pairs"][0]["left"], "1,02,178")
        self.assertEqual(info["pairs"][0]["right"], "20,436 L")
        receive = next(row for row in page["batch_alerts"] if row["kind"] == "receive")
        self.assertEqual(receive["pairs"][0]["left"], "₹43,547")
        self.assertEqual(page["batch_kitchens"][0]["name"], "Kolkata kitchen")
        self.assertEqual(page["batch_kitchens"][1]["name"], "Delhi kitchen")
        self.assertEqual(page["batch_period"], "24 Sep–8 Oct 2026")
        hidden = batch_page_context(
            city="",
            store="",
            store_id="",
            query="",
            filters={"cc_range": "7"},
        )
        self.assertEqual(hidden["batch_alerts"], [])
        self.assertIn("Data coming", hidden["batch_use_note"])
        club = batch_page_context(
            city="Kolkata",
            store="Calcutta Swimming Club",
            store_id="",
            query="",
            filters={},
        )
        coconut_row = next(row for row in club["batch_use_rows"] if row["item"] == "Coconut Shredded")
        self.assertEqual(coconut_row["verdict"], "Recipe over-deducts")
        self.assertNotIn("read", coconut_row)

    def test_a_batch_that_contains_coconut_puts_the_dish_under_review(self):
        from app.menu_costing.review import clear_review_cache, dish_under_review, highest_food_cost

        clear_review_cache()
        self.assertTrue(dish_under_review("Kolkata", "Masala Dosa"))
        self.assertFalse(dish_under_review("Kolkata", "ABC Juice"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "menu_item_cost_lines.csv",
                "outlet,city,recipe_tab,item_name,is_menu_item,ingredient_name,is_inactive_ingredient\n"
                "Ideal Plaza,Kolkata,base,Plain Dosa,True,Regular White Chutney Bucket Outlet,False\n"
                "Ideal Plaza,Kolkata,base,Regular White Chutney Bucket Outlet,False,Coconut Shredded,False\n"
                "Ideal Plaza,Kolkata,base,Onion Uttapam,True,Onion,False\n"
                "Ideal Plaza,Kolkata,base,Chana Plate,True,Fried Chana Daal,False\n",
            )
            clear_review_cache()
            self.assertTrue(dish_under_review("Kolkata", "Plain Dosa", root))
            self.assertFalse(dish_under_review("Kolkata", "Onion Uttapam", root))
            self.assertFalse(dish_under_review("Kolkata", "Chana Plate", root))
            clear_review_cache()
            self.assertFalse(dish_under_review("Kolkata", "Plain Dosa", root, names=()))
        ranked = highest_food_cost(
            [
                {"item": "Masala Dosa", "food_pct": 80, "under_review": True},
                {"item": "ABC Juice", "food_pct": 40, "under_review": False},
                {"item": "Filter Coffee", "food_pct": 55, "under_review": False},
            ]
        )
        self.assertEqual([row["item"] for row in ranked], ["Filter Coffee", "ABC Juice"])


class BatchPassTests(unittest.TestCase):
    def test_the_longer_window_becomes_the_default_when_it_is_on_file(self):
        from app.menu_costing.batch_pass import pass_view

        header = (
            "city,store,batch_item,unit,period,city_made_qty,issued_qty,issued_amt,"
            "returned_qty,consumption_qty,consumption_amt,wastage_qty,wastage_amt,"
            "opening_qty,closing_qty,avg_price,status,source\n"
        )
        cover = (
            "city,batch_item,unit,stores_active,made,issued,consumed,cost,issued_qty,"
            "issued_amt,consumption_qty,consumption_amt,wastage_qty,avg_price_max,"
            "stores_consumed_without_issue,period\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "batch_actual_use_detail.csv",
                header
                + "Kolkata,Ideal Plaza,Dosa Batter Mix,Kg,2026-10-01 to 2026-10-08,,10,,,,5,,,,,,,,\n"
                + "Kolkata,Ideal Plaza,Dosa Batter Mix,Kg,2026-09-24 to 2026-10-08,12,80,,,40,,,,,,,,\n",
            )
            _write(
                root / "batch_item_coverage.csv",
                cover
                + "Kolkata,Dosa Batter Mix,Kg,1,no,yes,yes,yes,10,1,5,1,0,32,0,2026-10-01 to 2026-10-08\n"
                + "Kolkata,Dosa Batter Mix,Kg,1,yes,yes,yes,yes,80,1,40,1,0,33,0,2026-09-24 to 2026-10-08\n",
            )
            view = pass_view(root, city="Kolkata")
        self.assertEqual(view["period"], "24 Sep–8 Oct 2026")
        self.assertEqual(view["tiles"][0]["issued"], "80 kg")
        self.assertEqual(view["tiles"][0]["made"], "12 kg")
        self.assertNotIn("unrecorded", [row["kind"] for row in view["alerts"]])

    def test_a_blank_made_quantity_is_not_recorded(self):
        from app.menu_costing.batch_pass import pass_view

        view = pass_view(ROOT / "data" / "procurement", city="Kolkata")
        self.assertEqual(view["period"], "1–8 Oct 2026")
        self.assertTrue(all(row["made"] == "Not recorded" for row in view["tiles"]))
        self.assertNotIn("0", [row["made"] for row in view["tiles"]])
        kinds = [row["kind"] for row in view["alerts"]]
        self.assertEqual(kinds[0], "unrecorded")
        self.assertNotIn("tomato", kinds)


class BatchGapTests(unittest.TestCase):
    def test_missing_recipes_belong_to_sailesh_and_follow_the_city(self):
        index = get_index()
        board = load_gap_board(index.rows, email=OWNER)
        titles = [gap["title"] for gap in board["gaps"]]
        self.assertIn("No batch recipe: Dosa Batter Mix", titles)
        self.assertIn("No batch recipe: Imli Water", titles)
        self.assertNotIn("No batch recipe: Potato Masala Bucket Outlet", titles)
        self.assertNotIn("No batch recipe: Regular White Chutney Bucket Outlet", titles)
        kolkata = [gap["title"] for gap in filter_gaps(board["gaps"], {"cc_city": "Kolkata"}, index)]
        delhi = [gap["title"] for gap in filter_gaps(board["gaps"], {"cc_city": "Delhi NCR"}, index)]
        one = [
            gap["title"]
            for gap in filter_gaps(board["gaps"], {"cc_store": "connaught-place-02-0012"}, index)
        ]
        self.assertIn("No batch recipe: Dosa Batter Mix", kolkata)
        self.assertNotIn("No batch recipe: Sambar Bucket - Delhi", kolkata)
        self.assertIn("No batch recipe: Sambar Bucket - Delhi", delhi)
        self.assertIn("No batch recipe: Jain Sambar - Delhi", one)
        self.assertNotIn("No batch recipe: Jain Sambar Bucket", one)
        sailesh = next(gap for gap in board["gaps"] if gap["title"] == "No batch recipe: Imli Water" and gap["store"] == "Kolkata")
        self.assertEqual(sailesh["owner"], "Sailesh")
        self.assertTrue(sailesh["threat"])
        self.assertIn("Recipe coming from Sailesh", sailesh["why_it_matters"])

        with tempfile.TemporaryDirectory() as tmp:
            quiet = load_gap_board([], directory=Path(tmp), email=OWNER)
            self.assertFalse(any(gap["title"].startswith("No batch recipe") for gap in quiet["gaps"]))


class BatchPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import create_app

        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant Dalmia", "email": OWNER}
            sess["user_email"] = OWNER
            for key in ("cc_store", "cc_city", "cc_range", "cc_start", "cc_end"):
                sess.pop(key, None)

    def test_menu_page_shows_batch_cards_and_does_not_invent_use(self):
        html = self.client.get("/menu-costing?city=Kolkata").get_data(as_text=True)
        self.assertIn("Things we make", html)
        self.assertIn('id="things-we-make"', html)
        self.assertIn('data-field="batch-item" data-city="Kolkata" data-item="Potato Masala Bucket Outlet" data-value="42.98"', html)
        self.assertIn('data-field="batch-yield" data-item="Potato Masala Bucket Outlet" data-value="4.5"', html)
        self.assertIn('data-field="batch-cost" data-item="Potato Masala Bucket Outlet">₹43', html)
        self.assertIn('data-ingredient="Onion"', html)
        self.assertIn('data-field="batch-coming" data-city="Kolkata" data-item="Dosa Batter Mix"', html)
        self.assertIn("recipe coming from Sailesh", html)
        self.assertIn('data-field="batch-item" data-city="Kolkata" data-item="Imli Water" data-value=""', html)
        self.assertIn('data-field="booked-note"', html)
        self.assertIn("Booked to match what is sent out, not physically measured.", html)
        self.assertIn("Booked output", html)
        self.assertIn('data-field="batch-alert" data-kind="physical"', html)
        self.assertIn("2,594 L", html)
        self.assertIn("794 L", html)
        self.assertIn("Recipe over-deducts", html)
        self.assertIn("Food cost for these dishes is likely overstated. Recipe quantities are being corrected by Sailesh.", html)
        self.assertNotIn("stores likely making extra", html)
        self.assertNotIn("do not record", html.lower())
        self.assertNotIn("+83%", html)
        self.assertNotIn("+238%", html)
        self.assertNotIn('data-field="batch-variance"', html)
        self.assertNotIn('data-field="batch-item" data-city="Delhi NCR"', html)
        masala = self.client.get("/menu-costing?city=Kolkata&store=Ideal+Plaza&q=Masala+Dosa").get_data(as_text=True)
        self.assertIn('data-field="recipe-review" data-item="Masala Dosa"', masala)
        self.assertIn('data-review="yes"', masala)
        self.assertEqual(_cost_attr(masala), "23.82")
        juice = self.client.get("/menu-costing?city=Kolkata&q=ABC+Juice").get_data(as_text=True)
        self.assertIn('data-review="no"', juice)
        self.assertNotIn('data-field="recipe-review" data-item="ABC Juice"', juice)
        dish = self.client.get("/menu-costing/item?city=Kolkata&store=Ideal+Plaza&item=Masala+Dosa").get_data(as_text=True)
        self.assertIn('data-field="recipe-review" data-item="Masala Dosa"', dish)
        self.assertIn("Recipe quantities are being corrected by Sailesh.", dish)
        self.assertIn('id="bom"', dish)
        food = self.client.get("/food-cost").get_data(as_text=True)
        self.assertIn('data-field="recipe-review" data-item="Masala Dosa" data-city="Kolkata"', food)
        self.assertIn("Food cost for these dishes is likely overstated.", food)
        delhi = self.client.get("/menu-costing?cc_city=Delhi+NCR&cc_store=&cc_range=").get_data(as_text=True)
        self.assertIn('data-field="batch-item" data-city="Delhi NCR" data-item="Regular White Chutney Bucket Outlet" data-value="79.53"', delhi)
        self.assertNotIn('data-field="batch-item" data-city="Kolkata"', delhi)
        self.assertIn("900 kg short", delhi)
        self.assertIn("₹43,547", delhi)
        self.assertNotIn("2,594 L", delhi)
        self.assertIn("Not recorded", html)
        self.assertIn('data-field="batch-pass-alert" data-kind="unrecorded"', html)
        self.assertIn("yield and wastage", html)
        self.assertIn("Sailesh, Kolkata", html)
        self.assertIn("Shanker, Delhi", html)
        self.assertIn('data-field="batch-pass-issued" data-item="Sambar Bucket" data-value="3627"', html)
        self.assertIn("3,627 L", html)
        self.assertIn('data-field="batch-pass-rate" data-item="Coconut Shredded"', html)
        self.assertIn("₹196/kg", html)
        self.assertIn("not recipe cost", html)
        self.assertIn("data-list", html)
        self.assertIn("list-search.js", html)
        self.assertNotIn('data-kind="tomato"', html)
        self.assertNotIn("entp_consumption", html)
        self.assertIn('data-field="batch-pass-alert" data-kind="tomato"', delhi)
        self.assertIn("986 kg", delhi)
        self.assertIn("₹1.2L", delhi)
        self.assertIn("4,204 L", delhi)
        hidden = self.client.get("/menu-costing?city=Kolkata&cc_city=Kolkata&cc_store=&cc_range=7").get_data(as_text=True)
        self.assertIn('data-field="batch-pass-note"', hidden)
        self.assertNotIn('data-field="batch-pass" data-city=', hidden)


def _cost_attr(html):
    marker = 'data-field="menu-cost" data-item="Masala Dosa" data-value="'
    start = html.index(marker) + len(marker)
    return html[start:html.index('"', start)]
