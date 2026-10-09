import csv
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

_DB = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB.name
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from app.procurement.loader import load_procurement, newest_file
from app.procurement.numbers import (
    dates_in_filename,
    format_compact_inr,
    format_inr,
    parse_number,
    sum_present,
)
from app.procurement.recipe import ideal_plaza_recipe_costs, recipe_costs
from app.procurement.vendors import SHORT_DELIVERY_MESSAGE

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "procurement"


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
            close = html.find("<", tag_end + 1)
            return html[tag_end + 1 : close].strip(), tag
        start = tag_end


class ProcurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {"name": "Asha Rao", "email": "asha@dosacoffee.com"}

    def get(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.data[:400])
        return response.get_data(as_text=True)

    def test_blank_is_not_zero(self):
        self.assertIsNone(parse_number(""))
        self.assertIsNone(parse_number(None))
        self.assertEqual(parse_number("0"), 0.0)
        self.assertIsNone(sum_present([None, None]))
        self.assertEqual(sum_present([None, 0]), 0.0)
        self.assertEqual(format_inr(None), "")
        self.assertEqual(format_inr(0), "₹0")
        self.assertEqual(format_compact_inr(None), "")
        self.assertEqual(format_compact_inr(0), "₹0")
        self.assertEqual(format_compact_inr(7573666.12), "₹75.74L")
        self.assertEqual(format_compact_inr(26636745.7), "₹2.66Cr")
        self.assertEqual(format_compact_inr(9144.98), "₹9,145")

    def test_newest_file_uses_the_date_in_the_name(self):
        self.assertEqual(dates_in_filename("grn_lines_01-30Sep2026.csv")[1], date(2026, 9, 30))
        self.assertEqual(dates_in_filename("purchase_08Sep-08Oct2026.xls")[1], date(2026, 10, 8))
        self.assertEqual(dates_in_filename("report_01-08Oct2026.csv"), (date(2026, 10, 1), date(2026, 10, 8)))
        with tempfile.TemporaryDirectory() as folder:
            older = Path(folder, "grn_lines_warehouses_01-30Sep2026.csv")
            newer = Path(folder, "grn_lines_warehouses_01-08Oct2026.csv")
            undated = Path(folder, "grn_lines_warehouses.csv")
            older.write_text("date\n", encoding="utf-8")
            newer.write_text("date\n", encoding="utf-8")
            undated.write_text("date\n", encoding="utf-8")
            self.assertEqual(newest_file(folder, "grn_lines_warehouses*.csv").name, newer.name)

    def test_login_required(self):
        anon = self.app.test_client()
        response = anon.get("/food-cost")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.headers["Location"])
        vendors = anon.get("/vendors")
        self.assertEqual(vendors.status_code, 302)

    def test_city_food_cost_uses_real_windows(self):
        html = self.get("/food-cost")
        self.assertIn("September consumption is not on file", html)
        self.assertNotIn("September purchases are not in these files", html)
        self.assertIn("Net is blank", html)
        self.assertIn("Posist gross", html)
        self.assertIn("Purchases (all categories)", html)

        week_grn, _ = _field(html, "grn-all", window="week", city="kolkata")
        self.assertEqual(_attr(html, "grn-all", window="week", city="kolkata"), "3013530.15")
        self.assertEqual(_attr(html, "grn-all", window="week", city="delhi"), "2710316.47")
        self.assertEqual(_attr(html, "grn-all", window="span", city="kolkata"), "6818676.98")
        self.assertEqual(_attr(html, "grn-all", window="span", city="delhi"), "6865817.74")
        self.assertEqual(_attr(html, "grn-raw", window="week", city="kolkata"), "2090655.02")
        self.assertEqual(_attr(html, "grn-raw", window="week", city="delhi"), "1500003.85")
        self.assertEqual(_attr(html, "consumption", window="week", city="kolkata"), "1249845.52")
        self.assertEqual(_attr(html, "consumption", window="week", city="delhi"), "1195155.47")
        self.assertEqual(_attr(html, "gross", window="week", city="kolkata"), "7573666.12")
        self.assertEqual(_attr(html, "gross", window="week", city="delhi"), "6459983.13")
        self.assertEqual(_attr(html, "gross", window="span", city="kolkata"), "26636745.7")
        self.assertEqual(_attr(html, "gross", window="span", city="delhi"), "24958355.98")
        self.assertIn("16.5%", _field(html, "consumption-pct", window="week", city="kolkata")[0])
        self.assertEqual(week_grn, "₹30.14L")
        self.assertIn("₹75.74L", html)
        self.assertIn("₹75,73,666.12", html)
        self.assertIn(">More</summary>", html)
        self.assertNotIn("Command Centre", html)
        self.assertNotIn("repeat(3, 1fr)", (ROOT / "app/procurement/static/procurement.css").read_text(encoding="utf-8"))
        self.assertIn(week_grn, html)
        self.assertIn("Consumption is on file for", html)
        self.assertNotIn(".csv", html)
        self.assertNotIn(".xlsx", html)
        self.assertNotIn("recipe-cost.json", html)
        self.assertIn("theme-toggle", html)
        buying = self.get("/procurement")
        self.assertIn('href="/food-cost"', buying)
        self.assertIn('href="/vendors"', buying)
        self.assertNotIn("prefers-color-scheme", html)
        self.assertNotIn("data-field=\"grn-raw\" data-window=\"span\"", html)

    def test_store_match_and_blank_gross(self):
        html = self.get("/food-cost")
        ideal_cons = _attr(html, "store-consumption", key="ideal plaza")
        ideal_gross = _attr(html, "store-gross", key="ideal plaza")
        self.assertEqual(ideal_cons, "94016.17")
        self.assertNotEqual(ideal_gross, "")
        self.assertNotEqual(_attr(html, "store-pct", key="ideal plaza"), "")
        self.assertEqual(_attr(html, "store-consumption", key="chattarpur"), "0")
        self.assertEqual(_attr(html, "store-gross", key="chattarpur"), "")
        self.assertEqual(_attr(html, "store-pct", key="chattarpur"), "")
        self.assertIn("Warehouse and central-kitchen variance is not shown", html)
        self.assertNotIn('data-key="central warehouse"', html)
        self.assertNotIn('data-key="central kitchen"', html)

    def test_alerts_and_hershey(self):
        html = self.get("/food-cost")
        self.assertEqual(_attr(html, "cover-days", city="kolkata", item="Idli Daal (Rajkot)"), "63.13")
        excess = float(_attr(html, "excess-value", city="kolkata", item="Idli Daal (Rajkot)"))
        self.assertAlmostEqual(excess, 177145.87, delta=0.1)
        self.assertIn("Fried Chana Daal", html)
        stock_items = _all_attrs(html, "stock-alert", "data-item")
        self.assertIn("Fried Chana Daal", stock_items)
        self.assertNotIn("Paneer", stock_items)
        self.assertEqual(_attr(html, "hershey-qty", ref="IN-1854"), "623")
        self.assertIn("IN-1854", html)

    def test_recipe_cost_excludes_packaging_and_has_no_margin(self):
        html = self.get("/food-cost")
        self.assertIn("recipe cost excl. packaging", html.lower())
        self.assertIn("Masala Dosa", html)
        self.assertIn("Costs within each city", html)
        self.assertIn("three chutneys", html)
        self.assertEqual(_attr(html, "consumed-cost", item="Masala Dosa"), "41.67")
        self.assertIn("Margin is blank", html)
        self.assertIn("Connaught Place", html)
        payload = recipe_costs(outlet="Ideal Plaza", menu_item="Masala Dosa")
        self.assertTrue(payload["available"])
        self.assertEqual(payload["source_kind"], "menu_item_cost")
        self.assertEqual(payload["label"], "recipe cost excl. packaging")
        self.assertIsNone(payload["margin"])
        base = next(row for row in payload["items"] if row["recipe_tab"] == "base")
        self.assertEqual(base["cost_per_unit_avg_price"], 23.82)
        self.assertEqual(base["region"], "East")
        self.assertEqual(base["city"], "Kolkata")
        self.assertEqual(base["city_baseline_median"], 26.22)
        self.assertEqual(base["vs_city_baseline_pct"], -9.2)
        self.assertIsNone(base["selling_price"])
        self.assertIsNone(base["margin"])
        self.assertEqual({row["recipe_tab"] for row in payload["items"]}, {"base", "delivery", "table", "takeout"})
        self.assertAlmostEqual(payload["packaging_gap"]["share"], 24.9, delta=0.1)
        ideal = ideal_plaza_recipe_costs(menu_item="Masala Dosa", include_lines=True)
        self.assertEqual(ideal["lines"], [])
        self.assertIn("Ingredient lines", ideal["lines_note"])

    def test_menu_item_cost_is_preferred_when_present(self):
        with tempfile.TemporaryDirectory() as folder:
            folder_path = Path(folder)
            (folder_path / "recipe_cost_by_item.csv").write_text(
                "deployment,city,menu_item,is_menu_item,recipe_unit,"
                "cost_per_unit_avg_price,cost_per_unit_last_price\n"
                "Ideal Plaza,Kolkata,Masala Dosa,True,No.,1.00,1.00\n",
                encoding="utf-8",
            )
            (folder_path / "menu_item_cost_summary.csv").write_text(
                "item_name,unit,is_menu_item,outlets_with_recipe,min_cost_avg,"
                "median_cost_avg,max_cost_avg,outlet_min,outlet_max,spread_pct\n"
                "Masala Dosa,No.,True,2,23.82,26.91,30.00,Ideal Plaza,Connaught Place,26.0\n",
                encoding="utf-8",
            )
            (folder_path / "menu_item_cost.csv").write_text(
                "outlet,city,item_name,is_menu_item,recipe_tab,unit,"
                "cost_per_portion_avg,cost_per_portion_last,has_unpriced_ingredient,"
                "unpriced_ingredient_count\n"
                "Ideal Plaza,Kolkata,Masala Dosa,True,base,No.,23.82,24.10,False,0\n"
                "Connaught Place,Delhi,Masala Dosa,True,base,No.,30.00,31.00,True,1\n"
                "Ideal Plaza,Kolkata,Masala Dosa,True,takeout,No.,40.00,41.00,False,0\n"
                "GK1 Cloud Kitchen,Delhi,Filter Coffee,True,base,No.,,,True,2\n",
                encoding="utf-8",
            )
            payload = recipe_costs(directory=folder, outlet="Ideal Plaza", menu_item="Masala Dosa")
            self.assertEqual(payload["source_kind"], "menu_item_cost")
            self.assertEqual(payload["label"], "recipe cost excl. packaging")
            tabs = {row["recipe_tab"]: row for row in payload["items"]}
            self.assertEqual(set(tabs), {"base", "takeout"})
            self.assertEqual(tabs["base"]["cost_per_unit_avg_price"], 23.82)
            self.assertEqual(tabs["base"]["cost_per_portion_avg"], 23.82)
            self.assertFalse(tabs["base"]["partial"])
            self.assertIsNone(tabs["base"]["margin"])
            takeout = recipe_costs(
                directory=folder,
                outlet="Ideal Plaza",
                menu_item="Masala Dosa",
                recipe_tab="takeout",
            )
            self.assertEqual(len(takeout["items"]), 1)
            self.assertEqual(takeout["items"][0]["cost_per_portion_avg"], 40.0)
            blank_cost = recipe_costs(directory=folder, outlet="GK1 Cloud Kitchen", menu_item="Filter Coffee")
            self.assertIsNone(blank_cost["items"][0]["cost_per_portion_avg"])
            self.assertTrue(blank_cost["items"][0]["partial"])
            (folder_path / "menu_item_cost.csv").unlink()
            fallback = recipe_costs(directory=folder, menu_item="Masala Dosa")
            self.assertEqual(fallback["source_kind"], "recipe_cost_by_item")
            self.assertEqual(fallback["items"][0]["cost_per_unit_avg_price"], 1.0)

    def test_recipe_endpoint(self):
        response = self.client.get("/food-cost/recipe-cost.json?outlet=Ideal%20Plaza&item=Masala%20Dosa")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["items"][0]["cost_per_unit_avg_price"], 23.82)
        self.assertIsNone(body["margin"])
        self.assertIn("Ideal Plaza", body["consumption"]["outlet"])
        anon = self.app.test_client()
        self.assertEqual(anon.get("/food-cost/recipe-cost.json").status_code, 302)

    def test_vendors_rates_gaps_and_short_delivery(self):
        html = self.get("/vendors")
        self.assertIn(SHORT_DELIVERY_MESSAGE, html)
        self.assertIn("498 of 500 bills match", html)
        self.assertIn("SE-8780", html)
        self.assertIn("SE-8012", html)
        self.assertIn('data-field="above-cheapest"', html)
        gap = _attr(
            html,
            "above-cheapest",
            item="Ecolab-Multi Purpose SINK Detergent (1can = 1ltr)",
            supplier="Devine &amp; Conquer Store",
            city="Delhi",
        )
        self.assertEqual(gap, "360.3")
        self.assertIn("9 Sep–8 Oct 2026", html)
        self.assertNotIn("September purchases are not in these files", html)
        self.assertNotIn(".csv", html)
        self.assertNotIn(".xlsx", html)
        moves = _all_attrs(html, "rate-move", "data-item")
        self.assertTrue(moves)

    def test_shipped_grn_matches_the_readme_totals(self):
        bundle = load_procurement(DATA)
        totals = {}
        for row in bundle["grn_lines"]:
            totals[row["city"]] = totals.get(row["city"], 0.0) + row["total"]
        self.assertEqual(len(bundle["grn_lines"]), 2003)
        self.assertEqual(round(totals["Kolkata"], 2), 6818676.98)
        self.assertEqual(round(totals["Delhi"], 2), 6865817.74)
        self.assertEqual(min(row["date"] for row in bundle["grn_lines"]), date(2026, 9, 9))
        self.assertEqual(max(row["date"] for row in bundle["grn_lines"]), date(2026, 10, 8))
        po_qty = [row["lines_with_po_qty"] for row in bundle["po_coverage"]]
        self.assertTrue(po_qty)
        self.assertTrue(all(value == 0 for value in po_qty))
        matched = sum(1 for row in bundle["po_by_se"] if row["status"] == "match")
        self.assertEqual(matched, 498)
        self.assertEqual(len(bundle["po_by_se"]), 500)


def _attr(html, field, **attrs):
    _text, tag = _field(html, field, **attrs)
    marker = 'data-value="'
    start = tag.find(marker)
    if start < 0:
        raise AssertionError(tag)
    start += len(marker)
    end = tag.find('"', start)
    return tag[start:end]


def _all_attrs(html, field, attr):
    found = []
    needle = f'data-field="{field}"'
    start = 0
    while True:
        index = html.find(needle, start)
        if index < 0:
            break
        tag_end = html.find(">", index)
        tag = html[index:tag_end]
        marker = f'{attr}="'
        at = tag.find(marker)
        if at >= 0:
            at += len(marker)
            found.append(tag[at : tag.find('"', at)])
        start = tag_end
    return found


if __name__ == "__main__":
    unittest.main()
