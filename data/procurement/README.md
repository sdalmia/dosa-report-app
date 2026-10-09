# Procurement drops

Put each export in this folder. The dashboard does not keep a raw table. It picks the newest file whose name matches a topic, using a date in the filename (`2026-10-08`, `8 Oct 2026`). A later dated file replaces the older one. CSV, XLS, and XLSX are read. A `.md` file in this folder is the human summary: its headings can be shown as threat headlines.

Until a file is here, the tile says no data. A blank cell is not shown as zero.

| Topic | Words to put in the filename | Columns the tile looks for |
| --- | --- | --- |
| Bought vs consumed | `bought`, `consumed` | city, bought, consumed |
| Warehouse stock | `warehouse` | item, closing, and change when the column exists |
| Overstock | `overstock` | item, days of cover, value beyond 10 days |
| No purchase or negative stock | `no-purchase`, `negative` | item, stock |
| Packaging cover | `packaging` | item, cover days |
| Wastage | `wastage` | item, wastage |
| Hershey's IN-1854 | `hershey`, `in-1854` | any cell that names IN-1854 |
| Base kitchen purchases | `purchase-summary`, `item-wise`, `base-kitchen` | item, amount |

Name the period in the filename so the tile can show it. Example: `bought-consumed-by-city-2026-10-08.csv`.

# Procurement CSVs for food cost and vendors

Built 9 Oct 2026 (IST) and updated at about 10:45 PM IST with the September GRN, Purchase Detail and Stock Recipe exports. Every input comes from `/workspace/dosa-coffee-mis/posist/`. No new logins or pulls were done.

Ground rules:
- Real figures only.
- A blank cell means missing or not applicable. Zeros are real zeros from the source.
- Build scripts sit next to the outputs. Run them in this order: `build_grn.py` → `build_sup.py` → `build_po.py`. The others are `build_cons.py`, `build_recipe_consumption.py` and `build_recipe_cost.py`.

## 1. grn_lines_warehouses.csv (2,003 rows) and grn_charges_warehouses.csv (19 rows)
**Source:** Restroworks Stock Entry ("Entry Report") xlsx files for the two central warehouses.
- Sept files: `entry_report_{kolkata,delhi}_warehouse_09-30Sep2026.xlsx`.
- Kolkata Oct files: `_01-02Oct2026` and `_03Oct` to `_08Oct`.
- Delhi Oct files: `_01-02Oct2026` (01-Oct rows only) and `_04Oct` to `_08Oct`.
- `entry_report_delhi_warehouse_01-03Oct2026.xlsx` was not used because it is a duplicate.

**Coverage: 9 Sep to 8 Oct 2026.**

| City | Lines | Value | 9–30 Sep | 1–8 Oct |
|---|---|---|---|---|
| Kolkata | 991 | Rs 68,18,677 | Rs 38,05,147 | Rs 30,13,530 |
| Delhi | 1,012 | Rs 68,65,818 | Rs 41,55,501 | Rs 27,10,316 |

- Days with no receipts have no rows. These are true zeros, and the Purchase Detail report agrees. Delhi had none on 10, 11, 17, 18, 20 and 22–23 Sep, or on 2–3 Oct.

**How the columns are built:**
- `date` is the stock-entry date from the SE row.
- `invoice_date` comes from the "Invoice Date" row.
- `sub_total`, `tax` and `total` are line values. Tax is booked as 0 on nearly all lines.
- Super Category Bifurcation, Vendor Total and Store Total rows are skipped.
- Freight is not counted as an item line. It is in `grn_charges_warehouses.csv`: Kolkata Rs 3,390 and Delhi Rs 11,586.

**Checks against the source:**
- **Store Total check:** item lines plus freight match each file's Store Total row within rounding.
  - Sep Kolkata is Rs 378 over Rs 38,05,639.
  - Sep Delhi is Rs 57 over Rs 41,59,560.
  - The Oct files are each within about Rs 100.
  - Checked vendor by vendor, every gap is a small positive rounding difference against Restroworks' Vendor Total (largest Rs 92, Bagrodia).
- **Dedupe:** exact duplicates were removed only across files, and none were found. Repeated identical lines inside one file are kept, because they are real and are included in the Vendor Total. Example: SE-8752 HOSPITALITY Mart garbage bags, entered twice.
- **Missing item codes:** 5 lines have no item code in the source, so `item_code` is left blank.

## 2. supplier_summary.csv (65 rows) and supplier_item_rates.csv (383 rows)
**Source:** `grn_lines_warehouses.csv`, 9 Sep to 8 Oct.

**supplier_summary.csv** has one row per city and supplier, with these columns:
- lines, distinct_items, bills, sub_total, tax and total_value
- first_date and last_date
- share_of_city_spend_pct, calculated on line totals excluding freight

**supplier_item_rates.csv** has one row per item, unit, city and supplier, with these columns:
- lines, qty, wavg_rate (sub_total / qty, pre-tax), min_rate, max_rate, last_rate and last_date
- item_wavg_all and pct_vs_item_wavg_all
- pct_vs_cheapest_supplier
- n_suppliers_for_item and n_cities_for_item

**Caveats:**
- Items are matched on name and unit.
- This is a 30-day window, not a 90-day one.
- Single odd lines can distort the gaps. For example, one cash can of Ecolab sink detergent at Rs 94 (SE-7862, Delhi) makes the Devine & Conquer rate of Rs 432.65 look 360% above the cheapest. It is probably a mis-booked item, not a real quote.

## 3. Purchase Detail (PO vs received): po_coverage.csv (65 rows) and the reconciliation files
**Source:** Restroworks Purchase Detail with PO details:
- `po_vs_grn_purchase_detail_kolkata_09Sep-08Oct2026.csv` (Base Kitchen, 991 lines)
- `po_vs_grn_purchase_detail_delhi_09Sep-08Oct2026.csv` (Warehouse, 1,012 lines)

**PO data is blank in the source.** PO Qty, PO Number, PO Date and PO Amount are blank ("-") on every line. Receipts are not linked to POs in Restroworks, so short deliveries cannot be computed and no short-delivery file was built.

**po_coverage.csv** has one row per city and supplier, with these columns:
- received_lines, received_bills and received_value
- lines_with_po_qty and lines_with_po_number. Both are 0 everywhere because the source fields are blank; the 0 is derived, not reported by Restroworks.
- pct_lines_with_po
- first_date and last_date

Use this file for the "no PO discipline" tile.

**po_vs_grn_reconciliation_summary.csv (2 rows) and po_vs_grn_reconciliation_by_se.csv (500 rows)** reconcile Purchase Detail against the Entry Report GRN for 9 Sep to 8 Oct:
- Line counts match exactly: Kolkata 991 = 991, Delhi 1,012 = 1,012.
- Dates match on every SE.
- 498 of 500 SEs match on amount. The 2 that differ:

| City | SE | What differs | Purchase Detail | Entry Report | Gap |
|---|---|---|---|---|---|
| Kolkata | SE-8780 (Cash Purchase, Rice Powder, 2 Oct) | Quantity | 45 Kg = Rs 4,500 | 15 Kg = Rs 1,500 | +Rs 3,000 |
| Delhi | SE-8012 (MANDI FRESH, 4 Oct) | Onion rate | Rs 40 | Rs 41 | -Rs 286 |

- Both look like edits made after the early-October Entry Reports were pulled. Purchase Detail was pulled at 10:37 PM IST on 9 Oct and is likely the current value. Re-pull those two days' Entry Reports to confirm.
- Purchase Detail also nets discounts out of Total: Kolkata Rs 550 and Delhi Rs 203. The Entry Report totals do not show these.
- **City-level net gap, Purchase Detail Total minus GRN:** Kolkata +Rs 2,450 and Delhi -Rs 489. That is under 0.04% in both cities.

## 4. store_consumption_wastage.csv (70 rows) and store_item_wastage_top.csv (306 rows)
**Unchanged.** Source is `entp_consumption_east_north_01-08Oct2026.csv`, the Enterprise Consumption report for all deployments, 1 to 8 Oct.

**Fixes applied:**
- 940 "Pacific mall, Jasola" rows were split by the comma in the name and have been merged back.
- There were no Total rows in the source.

**How it is split:**
- Each amount is split into `_raw` (Food+Beverage), `_semi` (Semi Process) and `_other`.
- Physical and variance columns are blank where no physical count was taken (42 of 70 rows).

**Caveats:**
- **Warehouse and Central Kitchen physical stock is Rs 0, so their variance is not meaningful.**
- The Sec 18 Noida variance of about -Rs 1.67L is distorted by the IN-1854 Hershey's syrup unit error.
- Events & Catering has a blank city.

## 5. Recipe cost

### 5a. recipe_cost_by_item.csv (441 rows) and recipe_cost_lines.csv (4,055 rows)
**Source:** Restroworks Stock Recipe Report (Base Recipe, with Avg Price and Last Price):
- `posist/recipe_cost_ideal_plaza.csv` (Ideal Plaza, Kolkata, 2,020 lines, 213 recipes)
- `posist/recipe_cost_connaught_place.csv` (Connaught Place, Delhi, 2,033 lines, 228 recipes)

The source files were not modified.

**recipe_cost_by_item.csv:**
- `cost_per_unit_avg_price` = Avg Yield Total / Recipe Qty.
- `cost_per_unit_last_price` is the same, using Last Yield Total.
- `last_vs_avg_pct` compares the two.
- `ingredient_count` and `unpriced_ingredient_count` count lines whose avg cost is NA or 0. The last-price version is in `unpriced_ingredient_count_last`.
- `is_menu_item` marks the "(MI)" recipes. 4 rows are not menu items. They are batter kits or packs sized in Kg or Pkt.
- In every recipe, the ingredient lines sum exactly to Restroworks' recipe total.

**Caveats:**
- Restroworks has separate items whose names end in "." (for example "Masala Dosa." vs "Masala Dosa"), probably channel variants. They are kept as separate rows.
- Unpriced ingredients are mostly RO Water, Paper Tray Mat and CO2. 134 Ideal Plaza and 154 Connaught Place recipes have at least one.

### 5b. recipe_consumption_cost_ideal_plaza.csv (107) and recipe_consumption_cost_ideal_plaza_lines.csv (1,265)
**Renamed** from the earlier `recipe_cost_ideal_plaza*.csv` so they do not clash with the Restroworks exports. Built by `build_recipe_consumption.py`.

**Source:** `consumption_recipeConsumption_IdealPlaza-Kolkata_01-08Oct2026.csv` (Billing). This is the theoretical cost per unit sold at Restroworks average price, for Ideal Plaza only, 1 to 8 Oct.

### 5c. recipe_cost_ideal_plaza_check_vs_consumption.csv (213 rows)
This compares Stock Recipe cost with the Recipe Consumption cost for Ideal Plaza.
- All 107 sold items match a recipe. The other 106 recipes did not sell between 1 and 8 Oct.
- Only 40 items are within 5%. 67 differ by more than 5%, and the Stock Recipe cost is always the lower one.
- **The difference is packaging, not the food recipe.** On the shared ingredients, the two sources agree (median gap 0%, and 101 of 107 items within 5%).
- What makes up the gap: billing consumption adds order-type packaging (takeaway boxes, carry bags, Glen containers, spoons) and banana leaves that the base recipe does not have. Examples:
  - Idli Plate: Rs 14.11 base vs Rs 29.27 consumed.
  - Masala Dosa: Rs 23.82 vs Rs 41.67.
- Over 1 to 8 Oct at Ideal Plaza, those extras were about Rs 62.6k of Rs 2.51L in theoretical consumed cost, roughly 25%.
- The few residual gaps above 5% on shared ingredients are Ghee/Butter Idli pc, Iced Filter Coffee and some Uttapam/Rasam Vada lines, mostly banana leaf quantities.
- **For food cost:** use Recipe Consumption for actual mix-weighted cost and Stock Recipe for menu-level base cost.

### 5d. menu_item_cost.csv, menu_item_cost_summary.csv, menu_item_cost_channels_ideal_plaza.csv
**menu_item_cost_summary.csv** is one row per item per city. `city_baseline_median_cost` is that city's own median. Outlets in `outlets_excluded` are already left out of it. `spread_within_city_pct` and `max_vs_city_baseline_pct` stay inside that city.

**menu_item_cost.csv** is one row per outlet, recipe tab, and item. `vs_city_baseline_pct` is that outlet versus its own city's median. A blank cost is not zero.

**menu_item_cost_channels_ideal_plaza.csv** is Ideal Plaza only (base, table, takeout, delivery). It is not the item file.

Delhi NCR costs more than Kolkata because Delhi serves 3 chutneys with each dish and Kolkata serves 1. Compare each city with its own median. Do not label a Delhi or North margin as a recipe that needs checking.

## Missing / pending
- **Short deliveries:** cannot be built, because PO quantities are blank in Restroworks.
- **Older recipe export:** `recipe_cost_by_item.csv` covers Ideal Plaza and Connaught Place only. `menu_item_cost.csv` replaces it for the panel when both are on disk.
- **Store consumption and wastage:** covers 1 to 8 Oct only. There is no September consumption file.