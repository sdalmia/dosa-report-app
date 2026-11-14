# Procurement backfill (1 Apr–8 Sep 2026)

Source: PurchaseEasy Entry Reports and Purchase Summary Item Wise files
dropped under `/workspace/backfill/procurement/<month>/`.

Each month folder has, for the Delhi and Kolkata central warehouses:

- `entry_report_*_warehouse_*.xlsx` — invoice item lines (date, vendor, item, qty, rate, totals)
- `purchase_summary_itemwise_*.xls` — officially named .xls, actually HTML

April–August are calendar months. `2026-09-01to08` is 1–8 Sep only, and is
combined with the existing 9 Sep–8 Oct GRN file for September purchases.

The Wizard uses item lines for purchases (tax inclusive). Freight, transport
and TCS charges are in `data/history/purchases_charges_month.csv`, not in
item totals. Item-line subtotals match the Purchase Summary item subtotals
within ₹0.02. The Entry Report "Store Total" includes charges and is not used
as the purchase figure. September Delhi's Store Total sits below item lines
plus charges; the item-line and summary item subtotals still match, and
purchases use the item lines.

These files were parsed by `scripts/parse_procurement_backfill.py` and
folded in by `scripts/build_history.py`.
