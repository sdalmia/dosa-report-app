# Backfill drops

Other bots save files under `/workspace/backfill/<domain>/`. This folder in
the repo is only documentation; the live app on Render does not read
`/workspace/backfill`.

Domains: `posist_sales`, `posist_channel`, `procurement`, `menu_mix`, `tally`.

Run `python scripts/load_backfill.py` (optionally `--rebuild`) from a machine
that has the drop folder, then open a data PR. Expected columns are in
`scripts/load_backfill.py` and in the history pull-request body.

Procurement can also be dropped as `/workspace/backfill/procurement/<YYYY-MM>/`
(or `<YYYY-MM-DDtoDD>/`) with Entry Report `.xlsx` files and Purchase Summary
Item Wise `.xls` files (those are HTML). The loader copies them to
`data/procurement/backfill/` and `scripts/build_history.py` folds them in.

Tally Day Book packs can be dropped as `/workspace/backfill/tally/<company>/<YYYY-MM>/`.
Menu mix (Jarvis) is still pending; the same loader will pick it up when it lands.
Alfred's April–August Posist monthly extracts and 1–3 Sep are loaded (September is a full month: 1–3 Sep extract joined to the 4–30 Sep daily file).

Monthly Posist files (`posist_sales/sales_YYYY-MM.csv` and
`posist_channel/channel_YYYY-MM.csv`) are Alfred's calendar-month format;
April–August 2026 and 1–3 Sep (`sales_2026-09.csv`, `channel_2026-09.csv`) are loaded. Net is left blank when the cell is blank.

Daily store-by-channel workbooks for 1 Oct–12 Nov 2026
(`/workspace/posist_insights/2026-11-13/secondpass_daily_tabs_<tab>_<day>_and_<day>.xlsx`)
are loaded by `scripts/parse_tabwise_channels.py` into `data/posist/daily_sales/channel_YYYY-MM-DD.csv`
(one day counted once; an absent tab or store is not zero; Faridabad out from 23 Oct).
The reconciliation against store gross is `data/history/channel_tabwise_reconciliation.csv`.

Wastage CSVs live at `/workspace/backfill/procurement/wastage/`. Consumption
reports in `procurement/consumption/` are parsed into monthly store and item
aggregates (raw files stay out of the repo). Food cost is (raw + semi) / Posist
gross. Chattarpur and GK1 are excluded. Missing store-months are 'not available'.
