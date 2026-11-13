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
Menu mix (Jarvis) and Posist sales (Alfred) are still pending; the same loader
will pick them up when they land.

Monthly Posist files (`posist_sales/sales_YYYY-MM.csv` and
`posist_channel/channel_YYYY-MM.csv`) are Alfred's calendar-month format;
May–August will arrive the same way. Net is left blank when the cell is blank.

Wastage CSVs live at `/workspace/backfill/procurement/wastage/`. Consumption
reports in `procurement/consumption/` are still being pulled and are not loaded.
