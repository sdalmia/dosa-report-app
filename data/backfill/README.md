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
