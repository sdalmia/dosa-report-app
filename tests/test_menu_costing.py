import io
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB.name
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from app.menu_costing.catalog import build_page, food_cost_pct, margin_amount
from app.menu_costing.recipes import clear_caches, explain_baseline, load_recipes
from app.menu_costing.history import dish_history, load_history
from app.menu_costing.models import MenuItemPrice, MenuVersion
from app.menu_costing.parse_menu import parse_menu_text, parse_upload
from app.menu_costing.pnl import load_pnl
from app.extensions import db

ROOT = Path(__file__).resolve().parents[1]


def _field(html, field, **attrs):
    needle = f'data-field="{field}"'
    start = 0
    while True:
        index = html.find(needle, start)
        if index < 0:
            raise AssertionError(f"missing {field} {attrs}")
        tag_end = html.find(">", index)
        tag = html[index:tag_end]
        if all(f'{key}="{value}"' in tag for key, value in attrs.items()):
            return tag
        start = tag_end


def _attr(html, field, **attrs):
    tag = _field(html, field, **attrs)
    marker = 'data-value="'
    start = tag.find(marker) + len(marker)
    return tag[start : tag.find('"', start)]


class MenuCostingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant Dalmia", "email": "siddhant@dalgreenfoods.com"}
            sess["user_email"] = "siddhant@dalgreenfoods.com"
        with self.app.app_context():
            MenuItemPrice.query.delete()
            MenuVersion.query.delete()
            db.session.commit()

    def test_city_median_is_not_a_cross_city_rank(self):
        recipes = {
            "cities": ["Kolkata", "Delhi NCR"],
            "outlets": {"Kolkata": ["Ideal Plaza"], "Delhi NCR": ["Connaught Place"]},
            "by_outlet": {
                ("Kolkata", "Ideal Plaza", "masala dosa"): {
                    "outlet": "Ideal Plaza",
                    "city": "Kolkata",
                    "item": "Masala Dosa",
                    "key": "masala dosa",
                    "cost": 26.0,
                    "median": 26.0,
                    "vs_pct": 0,
                    "partial": False,
                },
                ("Delhi NCR", "Connaught Place", "masala dosa"): {
                    "outlet": "Connaught Place",
                    "city": "Delhi NCR",
                    "item": "Masala Dosa",
                    "key": "masala dosa",
                    "cost": 41.0,
                    "median": 41.0,
                    "vs_pct": -2.0,
                    "partial": False,
                },
                ("Kolkata", "Ideal Plaza", "thumsup"): {
                    "outlet": "Ideal Plaza",
                    "city": "Kolkata",
                    "item": "Thumsup",
                    "key": "thumsup",
                    "cost": 30.0,
                    "median": 20.0,
                    "vs_pct": 50.0,
                    "partial": False,
                },
            },
            "by_city": {},
            "lines_path": Path("missing"),
        }
        sales = {"available": False, "by_store_item": {}, "period_label": "", "coming": "Data coming."}
        page = build_page(
            recipes,
            sales,
            [],
            city="Delhi NCR",
            channel="Dine-in",
            store="",
            query="",
            today=date(2026, 10, 9),
        )
        self.assertEqual(page["threats_above"], [])
        self.assertIn("Data coming", page["sales_coming"])
        kolkata = build_page(
            recipes,
            sales,
            [],
            city="Kolkata",
            channel="Swiggy",
            store="Ideal Plaza",
            query="",
            today=date(2026, 10, 9),
        )
        self.assertEqual(kolkata["threats_above"][0]["item"], "Thumsup")
        self.assertEqual(kolkata["threats_above"][0]["city"], "Kolkata")
        self.assertIn("Kolkata", kolkata["threats_above"][0]["vs"])
        self.assertNotIn("Delhi", kolkata["threats_above"][0]["vs"])
        self.assertIn("No Swiggy prices", kolkata["price_gap"])
        self.assertIsNone(food_cost_pct(26, None))
        self.assertIsNone(margin_amount(26, None))

    def test_live_menu_uses_the_city_median_and_leaves_price_blank(self):
        html = self.client.get("/menu?city=Kolkata&channel=Dine-in&store=Ideal+Plaza&q=Masala+Dosa").get_data(as_text=True)
        self.assertIn("Delhi serves 3 chutneys with each dish. Kolkata serves 1.", html)
        self.assertNotIn("recipe needs checking", html.lower())
        self.assertNotIn("menu_item_cost", html)
        self.assertEqual(_attr(html, "menu-cost", item="Masala Dosa"), "23.82")
        self.assertEqual(_attr(html, "menu-price", item="Masala Dosa"), "")
        self.assertEqual(_attr(html, "food-cost-pct", item="Masala Dosa"), "")
        self.assertEqual(_attr(html, "menu-margin", item="Masala Dosa"), "")
        self.assertIn("9.2% below the Kolkata median", html)
        self.assertIn('data-field="cost-full" data-item="Masala Dosa"', html)
        self.assertNotIn("₹23.82", html)
        self.assertIn("₹24", html)
        self.assertEqual(_attr(html, "orders", item="Masala Dosa"), "2750")
        self.assertIn("Data coming", html)
        self.assertIn('href="/menu"', self.client.get("/procurement").get_data(as_text=True))
        self.assertIn("Menu", html)

    def test_delhi_threats_stay_inside_delhi(self):
        html = self.client.get("/menu?city=Delhi+NCR&channel=Zomato").get_data(as_text=True)
        self.assertNotIn("recipe needs checking", html.lower())
        self.assertIn("No Zomato prices on file for Delhi NCR", html)
        start = 0
        while True:
            index = html.find('data-field="threat-above"', start)
            if index < 0:
                break
            tag = html[index : html.find(">", index)]
            self.assertIn('data-city="Delhi NCR"', tag)
            self.assertNotIn("Kolkata", tag)
            start = index + 1

    def test_bom_lines_keep_blanks_and_one_city(self):
        html = self.client.get(
            "/menu/item?city=Kolkata&store=Ideal+Plaza&item=Masala+Dosa"
        ).get_data(as_text=True)
        self.assertIn("Kolkata median", html)
        self.assertIn("within Kolkata", html)
        self.assertNotIn("Delhi NCR median", html)
        self.assertIn("9.2% below the Kolkata median", html)
        self.assertEqual(_attr(html, "line-cost", ingredient="RO Water"), "")
        batter = _attr(html, "line-cost", ingredient="Dosa Batter Mix")
        self.assertNotEqual(batter, "")
        self.assertNotIn("₹4.59", html)

    def test_upload_keeps_every_version_and_diffs_them(self):
        first = self._upload(
            "2026-09-01",
            "Item,Price,Category\nMasala Dosa,180,Dosa\nFilter Coffee,80,Drinks\n",
            "sep.csv",
        )
        self.assertEqual(first.status_code, 302)
        second = self._upload(
            "2026-10-01",
            "Item,Price\nMasala Dosa,10\nIdli,70\n",
            "oct.csv",
        )
        self.assertEqual(second.status_code, 302)
        with self.app.app_context():
            versions = MenuVersion.query.order_by(MenuVersion.effective_from).all()
            self.assertEqual(len(versions), 2)
            self.assertEqual(versions[0].effective_to, date(2026, 9, 30))
            self.assertIsNone(versions[1].effective_to)
            old_price = MenuItemPrice.query.filter_by(version_id=versions[0].id, item="Masala Dosa").one()
            self.assertEqual(old_price.price, 180)
            self.assertEqual(old_price.category, "Dosa")
            left, right = versions[0].id, versions[1].id
        history = self.client.get(f"/menu/history?left={left}&right={right}").get_data(as_text=True)
        self.assertIn('data-field="diff-added" data-item="Idli"', history)
        self.assertIn('data-field="diff-removed" data-item="Filter Coffee"', history)
        self.assertIn('data-field="diff-repriced" data-item="Masala Dosa"', history)
        self.assertIn("₹180", history)
        self.assertIn("₹10", history)
        menu = self.client.get("/menu?city=Kolkata&channel=Dine-in&q=Masala+Dosa").get_data(as_text=True)
        self.assertEqual(_attr(menu, "menu-price", item="Masala Dosa"), "10")
        self.assertIn('data-field="priced-below" data-item="Masala Dosa"', menu)
        self.assertIn('data-field="margin-hurt" data-item="Masala Dosa"', menu)
        self.assertNotEqual(_attr(menu, "food-cost-pct", item="Masala Dosa"), "")

    def test_upload_is_owner_only_and_a_bad_file_is_not_saved(self):
        anon = self.app.test_client()
        self.assertEqual(anon.get("/menu/upload").status_code, 302)
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Asha Rao", "email": "asha@dosacoffee.com"}
            sess["user_email"] = "asha@dosacoffee.com"
        blocked = self.client.get("/menu/upload")
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("dashboard", blocked.headers["Location"])
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant Dalmia", "email": "siddhant@dalgreenfoods.com"}
            sess["user_email"] = "siddhant@dalgreenfoods.com"
        rejected = self._upload("2026-10-01", "dish,qty\nMasala,1\n", "notes.csv")
        self.assertEqual(rejected.status_code, 200)
        self.assertIn("not saved", rejected.get_data(as_text=True).lower())
        with self.app.app_context():
            self.assertEqual(MenuVersion.query.count(), 0)
        parsed = parse_menu_text("Item,Price\nMasala Dosa,180\n")
        self.assertEqual(parsed["items"][0]["price"], 180)
        blank = parse_upload("menu.csv", b"Item,Price\nMasala Dosa,\n")
        self.assertIsNone(blank["items"][0]["price"])
        self.assertEqual(parse_upload("menu.xls", b"nope")["items"], [])

    def test_incomplete_dish_never_shows_a_real_food_cost(self):
        recipes = {
            "cities": ["Delhi NCR"],
            "outlets": {"Delhi NCR": ["Chattarpur"]},
            "by_outlet": {
                ("Delhi NCR", "Chattarpur", "abc juice"): {
                    "outlet": "Chattarpur",
                    "city": "Delhi NCR",
                    "item": "ABC Juice",
                    "key": "abc juice",
                    "cost": 9.65,
                    "median": 12.0,
                    "vs_pct": -10.0,
                    "partial": True,
                    "incomplete": True,
                    "unpriced_excl": 3,
                    "unpriced_names": ["Apple", "Beetroot", "Mint leaf", "RO Water"],
                }
            },
            "by_city": {},
            "lines_path": Path("missing"),
        }
        sales = {"available": False, "by_store_item": {}, "period_label": "", "coming": "Data coming."}
        older = {
            "id": 1,
            "city": "Delhi NCR",
            "channel": "Dine-in",
            "store_scope": "All stores",
            "effective_from": date(2026, 9, 1),
            "effective_to": date(2026, 9, 30),
            "items": [{"item": "ABC Juice", "category": "", "price": 80}],
        }
        newer = {
            "id": 2,
            "city": "Delhi NCR",
            "channel": "Dine-in",
            "store_scope": "All stores",
            "effective_from": date(2026, 10, 1),
            "effective_to": None,
            "items": [{"item": "ABC Juice", "category": "", "price": 5}],
        }
        page = build_page(
            recipes,
            sales,
            [newer, older],
            city="Delhi NCR",
            channel="Dine-in",
            store="Chattarpur",
            query="",
            today=date(2026, 10, 9),
        )
        row = page["rows"][0]
        self.assertTrue(row["incomplete"])
        self.assertEqual(row["food_pct"], "")
        self.assertEqual(row["food_attr"], "")
        self.assertEqual(row["margin"], "")
        self.assertEqual(row["cost_attr"], "9.65")
        self.assertEqual(page["priced_below"], [])
        self.assertEqual(page["margin_hurts"], [])
        names = [item["name"] for item in page["unpriced"]]
        self.assertEqual(names, ["Apple", "Beetroot", "Mint leaf"])
        self.assertNotIn("RO Water", names)

    def test_live_unpriced_ingredients_and_recipe_history(self):
        ideal = self.client.get(
            "/menu/item?city=Kolkata&store=Ideal+Plaza&item=Masala+Dosa"
        ).get_data(as_text=True)
        self.assertNotIn("Cost incomplete", ideal)
        self.assertIn("no earlier month", ideal.lower())
        self.assertEqual(_attr(ideal, "recipe-cost", **{"data-month": "2026-10"}), "23.82")
        truck = self.client.get(
            "/menu?city=Kolkata&channel=Dine-in&store=Food+Truck+-+1&q=Masala+Dosa"
        ).get_data(as_text=True)
        self.assertIn('data-field="cost-incomplete" data-item="Masala Dosa"', truck)
        self.assertIn("2 ingredients have no price", truck)
        self.assertEqual(_attr(truck, "menu-cost", item="Masala Dosa"), "10.9")
        self.assertEqual(_attr(truck, "food-cost-pct", item="Masala Dosa"), "")
        truck_item = self.client.get(
            "/menu/item?city=Kolkata&store=Food+Truck+-+1&item=Masala+Dosa"
        ).get_data(as_text=True)
        self.assertEqual(_attr(truck_item, "recipe-cost", **{"data-month": "2026-10"}), "7.49")
        city = self.client.get("/menu?city=Kolkata&channel=Dine-in&q=Masala+Dosa").get_data(as_text=True)
        self.assertNotIn('data-field="cost-incomplete" data-item="Masala Dosa"', city)
        self.assertNotIn('data-field="cost-full" data-item="Masala Dosa"', city)
        buying = self.client.get("/menu?city=Kolkata").get_data(as_text=True)
        self.assertIn(
            'data-field="unpriced-ingredient" data-item="Spicy Coconut Chutney Mix 1Pkt (16gm)"',
            buying,
        )
        self.assertIn("RO water has no purchase price", buying)
        start = 0
        while True:
            index = buying.find('data-field="unpriced-ingredient"', start)
            if index < 0:
                break
            tag = buying[index : buying.find(">", index)]
            self.assertNotIn("RO Water", tag)
            self.assertNotIn("R.O. Water", tag)
            start = index + 1
        history = self.client.get("/menu/history").get_data(as_text=True)
        self.assertIn('data-month="2026-10"', history)
        self.assertIn("October 2026 is the first snapshot", history)
        self.assertIn("no earlier month", history.lower())
        self.assertIn("No menu versions yet", history)
        self.client.post(
            "/menu/upload",
            data={
                "city": "Delhi NCR",
                "channel": "Dine-in",
                "store_scope": "",
                "effective_from": "2026-10-01",
                "menu_file": (io.BytesIO(b"Item,Price\nABC Juice,5\n"), "delhi.csv"),
            },
            content_type="multipart/form-data",
        )
        priced = self.client.get(
            "/menu?city=Delhi+NCR&channel=Dine-in&store=Chattarpur&q=ABC+Juice"
        ).get_data(as_text=True)
        self.assertIn('data-field="cost-incomplete" data-item="ABC Juice"', priced)
        self.assertEqual(_attr(priced, "food-cost-pct", item="ABC Juice"), "")
        self.assertEqual(_attr(priced, "menu-margin", item="ABC Juice"), "")
        self.assertEqual(_attr(priced, "menu-price", item="ABC Juice"), "5")
        self.assertNotEqual(_attr(priced, "menu-cost", item="ABC Juice"), "")
        self.assertNotIn('data-field="priced-below" data-item="ABC Juice"', priced)

    def test_city_median_comes_from_the_file_and_a_blank_percent_has_a_note(self):
        self.assertEqual(explain_baseline("ok", 16), "")
        self.assertIn("1 outlet", explain_baseline("fewer_than_3_fully_priced_outlets", 1))
        self.assertIn("Fewer than 3 outlets", explain_baseline("fewer_than_3_fully_priced_outlets", 1))
        clear_caches()
        recipes = load_recipes()
        ideal = recipes["by_outlet"][("Kolkata", "Ideal Plaza", "masala dosa")]
        self.assertEqual(ideal["median"], 26.22)
        self.assertEqual(ideal["vs_pct"], -9.2)
        self.assertEqual(ideal["baseline_text"], "")
        fanta = recipes["by_city"][("Kolkata", "fanta (regular)")]
        self.assertIsNone(fanta["median"])
        self.assertIn("Fewer than 3 outlets", fanta["baseline_text"])
        self.assertIn("1 outlet", fanta["baseline_text"])
        truck = self.client.get(
            "/menu?city=Kolkata&channel=Dine-in&store=Food+Truck+-+1&q=Masala+Dosa"
        ).get_data(as_text=True)
        self.assertIn("The dish cost is incomplete, so it is left out of the city comparison.", truck)
        self.assertIn("Why this % is blank", truck)

    def test_estimated_cost_names_the_receipt_and_skips_wild_medians(self):
        fanta = self.client.get(
            "/menu?city=Kolkata&channel=Dine-in&q=Fanta+%28Regular%29"
        ).get_data(as_text=True)
        self.assertEqual(_attr(fanta, "menu-cost", item="Fanta (Regular)"), "")
        self.assertNotIn("4782", fanta)
        self.assertNotIn("47510", fanta)
        forum = self.client.get(
            "/menu/item?city=Kolkata&store=Forum&item=Fanta+%28Regular%29"
        ).get_data(as_text=True)
        self.assertIn('data-field="cost-full"', forum)
        self.assertNotIn("4782", forum)
        self.assertNotIn("47510", forum)
        papad = self.client.get(
            "/menu?city=Delhi+NCR&channel=Dine-in&store=Chattarpur&q=Appalam+Papad+%281pc%29"
        ).get_data(as_text=True)
        self.assertIn('data-field="cost-estimated" data-item="Appalam Papad (1pc)"', papad)
        self.assertIn("SE-7875", papad)
        self.assertNotIn(".csv", papad)
        self.assertNotIn("po_vs_grn", papad)
        self.assertEqual(_attr(papad, "menu-cost", item="Appalam Papad (1pc)"), "4.1")
        delhi = self.client.get("/menu?city=Delhi+NCR").get_data(as_text=True)
        self.assertGreater(float(_attr(delhi, "stale-price", item="Ghee")), 10)
        self.assertIn('data-field="stale-restroworks" data-item="Ghee">₹722', delhi)
        self.assertIn('data-field="stale-receipt" data-item="Ghee">₹841', delhi)
        self.assertIn("Recipe price out of date", delhi)
        self.assertIn("Why this % is blank", forum)
        self.assertIn("The baseline has 1 outlet", forum)

    def test_recipe_looks_incomplete_flags_selling_stubs_and_the_container(self):
        kolkata = self.client.get("/menu?city=Kolkata").get_data(as_text=True)
        self.assertIn("Recipe looks incomplete", kolkata)
        self.assertIn("Stock under-deduction risk for Sailesh", kolkata)
        self.assertIn('data-field="threat-stub" data-city="Kolkata" data-store="" data-item="Regular Masala Dosa"', kolkata)
        self.assertIn("Coriander Leaves", kolkata)
        self.assertEqual(_attr(kolkata, "threat-stub", item="Regular Masala Dosa"), "0.1")
        self.assertIn('data-field="threat-stub" data-city="Kolkata" data-store="" data-item="Extra Sambar - 250ml"', kolkata)
        self.assertIn("Glen Container", kolkata)
        self.assertNotIn("recipe needs checking", kolkata.lower())
        delhi = self.client.get("/menu?city=Delhi+NCR").get_data(as_text=True)
        self.assertIn('data-field="threat-stub" data-city="Delhi NCR" data-store="" data-item="Extra Sambar - 250ml"', delhi)
        self.assertIn("only the container", delhi.lower())
        dish = self.client.get(
            "/menu/item?city=Kolkata&store=Ideal+Plaza&item=Regular+Masala+Dosa"
        ).get_data(as_text=True)
        self.assertIn('data-field="recipe-stub" data-item="Regular Masala Dosa"', dish)
        self.assertIn("Coriander Leaves", dish)
        self.assertIn("Sailesh", dish)

    def test_recipe_snapshots_show_cost_and_ingredient_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes").mkdir()
            (root / "2026-13").mkdir()
            self._month(
                root / "2026-09",
                "20",
                [("Oil", "0.02", "Kg", "1"), ("Dosa Batter Mix", "0.10", "Kg", "2")],
            )
            self._month(
                root / "2026-10",
                "24",
                [("Dosa Batter Mix", "0.14", "Kg", "4"), ("Ghee", "0.01", "Kg", "1")],
            )
            detail = dish_history(load_history(root), "Kolkata", "Ideal Plaza", "Masala Dosa")
        self.assertEqual([row["key"] for row in detail["months"]], ["2026-09", "2026-10"])
        self.assertEqual([row["cost"] for row in detail["points"]], [20, 24])
        self.assertEqual(detail["note"], "")
        change = detail["changes"][0]
        self.assertEqual(change["added"], ["Ghee"])
        self.assertEqual(change["removed"], ["Oil"])
        self.assertEqual(change["qty_changed"][0]["ingredient"], "Dosa Batter Mix")
        self.assertEqual(change["qty_changed"][0]["old_qty"], "0.1")
        self.assertEqual(change["qty_changed"][0]["new_qty"], "0.14")

    def test_company_pl_is_owner_only_and_blank_until_tally(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = load_pnl(Path(tmp) / "missing")
            self.assertEqual([row["name"] for row in empty["companies"]], ["Kolkata", "Delhi", "UP", "Haryana"])
            self.assertTrue(all(line["coming"] for row in empty["companies"] for line in row["lines"]))
            folder = Path(tmp) / "2026-10"
            folder.mkdir()
            (folder / "pl.csv").write_text(
                "company,month,book_food_cost,recipe_cost,rent,salaries,aggregator_commissions\n"
                "Kolkata,2026-10,,1200,50000,,\n",
                encoding="utf-8",
            )
            filled = load_pnl(Path(tmp))
            kolkata = filled["companies"][0]
            self.assertEqual(kolkata["lines"][0]["text"], "Data coming")
            self.assertEqual(kolkata["lines"][1]["attr"], "1200")
            self.assertEqual(kolkata["lines"][2]["attr"], "50000")
            self.assertTrue(kolkata["lines"][4]["coming"])
            self.assertTrue(filled["companies"][1]["lines"][2]["coming"])
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Asha Rao", "email": "asha@dosacoffee.com"}
            sess["user_email"] = "asha@dosacoffee.com"
        menu = self.client.get("/menu?city=Kolkata").get_data(as_text=True)
        self.assertNotIn("Aggregator commissions", menu)
        self.assertNotIn("/menu/pl", menu)
        blocked = self.client.get("/menu/pl")
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("dashboard", blocked.headers["Location"])
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Siddhant Dalmia", "email": "siddhant@dalgreenfoods.com"}
            sess["user_email"] = "siddhant@dalgreenfoods.com"
        page = self.client.get("/menu/pl").get_data(as_text=True)
        for company in ("Kolkata", "Delhi", "UP", "Haryana"):
            self.assertIn(f'data-company="{company}"', page)
        self.assertIn("Aggregator commissions", page)
        self.assertIn("Data coming", page)
        self.assertEqual(_attr(page, "pl-line", **{"data-company": "Kolkata", "data-line": "rent"}), "")
        self.assertIn('href="/menu/pl"', self.client.get("/menu").get_data(as_text=True))

    def _month(self, folder, cost, lines):
        folder.mkdir()
        (folder / "menu_item_cost.csv").write_text(
            "outlet,city,recipe_tab,item_name,is_menu_item,cost_per_portion_avg\n"
            f"Ideal Plaza,Kolkata,base,Masala Dosa,True,{cost}\n",
            encoding="utf-8",
        )
        body = ["outlet,recipe_tab,item_name,ingredient_name,ingredient_qty,ingredient_unit,ingredient_cost_avg_per_portion\n"]
        for name, qty, unit, line in lines:
            body.append(f"Ideal Plaza,base,Masala Dosa,{name},{qty},{unit},{line}\n")
        (folder / "menu_item_cost_lines.csv").write_text("".join(body), encoding="utf-8")

    def _upload(self, day, text, name):
        return self.client.post(
            "/menu/upload",
            data={
                "city": "Kolkata",
                "channel": "Dine-in",
                "store_scope": "",
                "effective_from": day,
                "menu_file": (io.BytesIO(text.encode("utf-8")), name),
            },
            content_type="multipart/form-data",
        )


if __name__ == "__main__":
    unittest.main()
