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
from app.menu_costing.models import MenuItemPrice, MenuVersion
from app.menu_costing.parse_menu import parse_menu_text, parse_upload
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
