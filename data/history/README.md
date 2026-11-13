# Wizard monthly history (1 Apr 2026 onward)

These files are the month-by-month figures the Wizard looks up. The prompt
only gets a short coverage line from `coverage.json`. A named month is
returned by `app.chat.history.lookup` or the `month_lookup` tool.

Every figure is copied or summed from a source file. A missing month is left
out and the Wizard says it is not loaded yet, naming who the data would come
from. Nothing is estimated or filled with zero.

Owner-only domains (finance, Tally, HR) are in this folder because the tidy
sources already live in the repo, but the lookup is role-gated. HR files are
counts only and have no names. Famepilot history is ticket counts only; customer
names are not stored.

## Files

| File | What it holds |
| --- | --- |
| `coverage.json` | Window, loaded and missing months, owner, roles, for every domain |
| `sales_store_month.csv` | Store gross (and bills, net when present) by calendar month |
| `sales_city_month.csv` | Kolkata, NCR, and Events city totals |
| `channel_store_month.csv` | Channel sales (Swiggy, Zomato, POS, …) by store and month |
| `purchases_item_month.csv` | Purchases by item, 1 Apr–8 Oct 2026 (Oct is 1–8 only). April–August from Entry Reports; September combines 1–8 Sep backfill with 9–30 Sep GRN |
| `purchases_vendor_month.csv` | Purchases by vendor (same window) |
| `purchases_charges_month.csv` | Freight, transport and TCS invoice charges, kept out of item totals |
| `prices_item_month.csv` | Item unit prices, 1 Apr–12 Nov. Apr–Aug from the official Purchase Summary; Sep is a qty-weighted average of 1–8 Sep entries plus 9–30 Sep GRN; Oct complete, Nov 1–12 |
| `procurement_parse_notes.json` | Parser checks: item vs summary subtotal gaps, Store Total notes, zero parse issues |
| `menu_item_month.csv` | Calendar Sep and Oct menu mix |
| `reelo_month.csv` | Reelo customers, orders, AOV, Apr–Oct (Nov incomplete) |
| `aggregator_store_month.csv` | Sanjoy Aug–Oct Swiggy/Zomato, Faridabad left out |
| `aggregator_outlet_map.csv` | How workbook outlet names were mapped |
| `finance_city_month.csv` | Grand Economics city lines, Apr–Sep 2026, owner/finance only |
| `tally_company_month.csv` | Tally voucher totals by company and type, owner/finance only |
| `hr_month.csv` | Joiner and exit counts by location, no names, owner only |
| `famepilot_tickets_month.csv` | Ticket counts by store and platform, no customer names |
| `wastage_store_month.csv` | PurchaseEasy wastage by store, 1 Apr–8 Sep 2026 (Sep is 1–8 only) |
| `wastage_item_month.csv` | Item-level wastage (stock, billing, total, and wastage %). Consumption reports are not loaded |
| `extra/` | Optional drops from `scripts/load_backfill.py`; the lookup concatenates them |

Regenerate with `python scripts/build_history.py`. Add a later month without
code changes by dropping files as described in `scripts/load_backfill.py` and
in the pull-request body, then re-running the builder (or placing a monthly
CSV in `extra/`).
