"""Copy backfill drops into the repo so a later data PR needs no code change.

Other bots (or a drop folder) save files under /workspace/backfill/<domain>/.
This script copies them into the repo paths the Wizard already reads, then
optionally refreshes monthly aggregates.

It is a packaging step for a data PR. The deployed app on Render does not
read /workspace/backfill at request time.

Expected drops (any subset):

  /workspace/backfill/posist_sales/sales_YYYY-MM-DD.csv
      columns: store, store_code, date, gross, net, bills, source, pulled_at
      copied to data/posist/daily_sales/

  /workspace/backfill/posist_sales/sales_YYYY-MM.csv
      same columns, one calendar month in a single file (Alfred's April 2026
      format; May–August will follow). Copied to data/posist/daily_sales/ and
      data/posist/monthly/. The date column is used. Net is left blank when
      the cell is blank, not filled with zero.

  /workspace/backfill/posist_sales/sales_store_month.csv   (optional pre-aggregate)
      columns: month, store, region, city, gross, bills, net, days_present,
               days_in_month, complete, mall_bulk, first_day, last_day
      copied to data/history/extra/

  /workspace/backfill/posist_channel/channel_YYYY-MM-DD.csv
      columns: store, store_code, date, source, sales, orders
      copied to data/posist/daily_sales/

  /workspace/backfill/posist_channel/channel_YYYY-MM.csv
      same columns, one calendar month (Alfred's April 2026 format;
      May–August will follow). Source names are kept as in the file
      (April uses DINEIN, TAKEOUT, SWIGGYONLINE, ZOMATOONLINE, ONDC).
      Copied to data/posist/daily_sales/ and data/posist/monthly/.

  /workspace/backfill/posist_channel/channel_store_month.csv
      columns: month, store, region, city, source, sales, orders, days_present,
               days_in_month, complete, first_day, last_day, note
      copied to data/history/extra/

  /workspace/backfill/procurement/purchases_item_month.csv
  /workspace/backfill/procurement/purchases_vendor_month.csv
  /workspace/backfill/procurement/prices_item_month.csv
      same columns as data/history/ (see data/history/README.md)
      copied to data/history/extra/

  /workspace/backfill/procurement/<YYYY-MM>/
  /workspace/backfill/procurement/<YYYY-MM-DDtoDD>/
      Entry Report .xlsx (Delhi and Kolkata warehouses) and Purchase
      Summary Item Wise .xls (HTML). Copied to data/procurement/backfill/
      and picked up by scripts/build_history.py. This is how April–8 Sep
      2026 was loaded.

  /workspace/backfill/procurement/wastage/wastage_{east,north}_YYYY-MM.csv
  /workspace/backfill/procurement/wastage/wastage_{east,north}_YYYY-MM-DDtoDD.csv
      17 columns (Deployment Name, Store Kitchen Name, Item Code, Item Name,
      Category, Super Category, Unit, Average Price, Stock Wastage Qty, Amt,
      Consumption Qty, Amt, Billing Wastage Qty, Amt, Total Wastage Qty, Amt,
      Percentage Wastage). Copied to data/procurement/backfill/wastage/ and
      folded by scripts/build_history.py. Consumption reports are not loaded.

  /workspace/backfill/menu_mix/menu_mix_YYYY-MM.csv
      columns: store, item, total_sales, total_orders, contribution_pct,
               period_start, period_end
      copied to data/menu/; also folded into data/history/extra/menu_item_month.csv
      if the drop already has a month column.

  /workspace/backfill/tally/daybook_vouchers.csv
      columns: company, date, type, no, dr, cr, amt, source
      merged (deduped by company, date, type, no) into the newest
      data/tally/YYYY-MM-DD/ folder. Existing rows are kept.

  /workspace/backfill/tally/<company>/<YYYY-MM>/
      Raw Tally Day Book packs from the Accountant (due 17 Nov).
      .txt Day Books are parsed with scripts/parse_tally_daybooks.py
      and merged the same way. Bank statements are not parsed as vouchers.

  /workspace/backfill/menu_mix/ and /workspace/backfill/posist_sales/
      still pending from Jarvis and Alfred; this loader already globs them
      so a later data PR can add the files without a code change.

After copying daily files, run scripts/build_history.py to refresh
data/history/*.csv and data/history/coverage.json. Pre-built monthly
CSVs in data/history/extra/ are read by the lookup on top of the
canonical files, so a data PR can add a month without changing code.

Usage:
    python scripts/load_backfill.py
    python scripts/load_backfill.py --rebuild
    python scripts/load_backfill.py --src /path/to/backfill
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
_DEFAULT_SRC = Path("/workspace/backfill")

_DAILY = {
    "posist_sales": ("sales_*.csv", _ROOT / "data" / "posist" / "daily_sales"),
    "posist_channel": ("channel_*.csv", _ROOT / "data" / "posist" / "daily_sales"),
}
_MONTHLY = {
    "posist_sales": ("sales_store_month.csv", "sales_city_month.csv"),
    "posist_channel": ("channel_store_month.csv",),
    "procurement": (
        "purchases_item_month.csv",
        "purchases_vendor_month.csv",
        "prices_item_month.csv",
    ),
    "menu_mix": ("menu_item_month.csv",),
}


def _copy(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    print(f"  {src} -> {dest.relative_to(_ROOT)}")


def load(src):
    src = Path(src)
    if not src.is_dir():
        print(f"No backfill folder at {src}. Nothing to copy.")
        return 0
    copied = 0
    for domain, (pattern, dest_dir) in _DAILY.items():
        folder = src / domain
        if not folder.is_dir():
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(folder.glob(pattern)):
            _copy(path, dest_dir / path.name)
            copied += 1
            # Calendar-month files (sales_YYYY-MM.csv / channel_YYYY-MM.csv)
            # are also kept under data/posist/monthly/.
            import re as _re
            if _re.search(r"(?i)_(20\d{2}-\d{2})\.csv$", path.name):
                monthly = _ROOT / "data" / "posist" / "monthly" / path.name
                _copy(path, monthly)
                copied += 1
        # monthly pre-aggregates living in the same domain folder
        for name in _MONTHLY.get(domain, ()):
            path = folder / name
            if path.is_file():
                _copy(path, _ROOT / "data" / "history" / "extra" / name)
                copied += 1
    for domain, names in _MONTHLY.items():
        if domain in _DAILY:
            continue
        folder = src / domain
        if not folder.is_dir():
            continue
        for name in names:
            path = folder / name
            if path.is_file():
                _copy(path, _ROOT / "data" / "history" / "extra" / name)
                copied += 1
        # menu calendar files
        if domain == "menu_mix":
            for path in sorted(folder.glob("menu_mix_*.csv")):
                _copy(path, _ROOT / "data" / "menu" / path.name)
                copied += 1
    # PurchaseEasy month folders (Entry Reports + HTML Purchase Summaries).
    proc = src / "procurement"
    if proc.is_dir():
        dest_root = _ROOT / "data" / "procurement" / "backfill"
        for folder in sorted(proc.iterdir()):
            if not folder.is_dir():
                continue
            if folder.name in {"purchases_item_month.csv", "purchases_vendor_month.csv", "prices_item_month.csv"}:
                continue
            has_reports = list(folder.glob("entry_report_*")) + list(folder.glob("purchase_summary_*"))
            if not has_reports:
                continue
            target = dest_root / folder.name
            target.mkdir(parents=True, exist_ok=True)
            for path in sorted(folder.iterdir()):
                if path.is_file():
                    _copy(path, target / path.name)
                    copied += 1

    # Wastage CSVs (consumption reports in procurement/consumption are left for later).
    wastage = src / "procurement" / "wastage"
    if wastage.is_dir():
        dest = _ROOT / "data" / "procurement" / "backfill" / "wastage"
        dest.mkdir(parents=True, exist_ok=True)
        for path in sorted(wastage.glob("wastage_*.csv")):
            _copy(path, dest / path.name)
            copied += 1

    tally = src / "tally"
    if tally.is_dir():
        if str(_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS))
        from parse_tally_daybooks import load_csv, merge_vouchers, write_csv

        incoming = []
        for path in sorted(tally.glob("*.csv")):
            incoming.extend(load_csv(path))
            print(f"  read {path} ({path.stat().st_size} bytes)")
        if incoming:
            base = _ROOT / "data" / "tally"
            dated = sorted(
                [p for p in base.iterdir() if p.is_dir() and len(p.name) == 10],
                key=lambda p: p.name,
            )
            dest = (dated[-1] if dated else base / "incoming") / "daybook_vouchers.csv"
            existing = load_csv(dest)
            merged, added = merge_vouchers(existing, incoming)
            write_csv(dest, merged)
            print(f"  tally merged into {dest.relative_to(_ROOT)}: {added} new, {len(merged)} total")
            copied += 1
        # Raw Day Book text under tally/<company>/<YYYY-MM>/ (Accountant drops).
        raw_dirs = [d for d in tally.iterdir() if d.is_dir()]
        if raw_dirs:
            from parse_tally_daybooks import collect_from, load_csv, merge_vouchers, write_csv
            incoming = collect_from(raw_dirs)
            if incoming:
                base = _ROOT / "data" / "tally"
                dated = sorted(
                    [p for p in base.iterdir() if p.is_dir() and len(p.name) == 10],
                    key=lambda p: p.name,
                )
                dest = (dated[-1] if dated else base / "incoming") / "daybook_vouchers.csv"
                existing = load_csv(dest)
                merged, added = merge_vouchers(existing, incoming)
                write_csv(dest, merged)
                print(f"  tally raw packs merged into {dest.relative_to(_ROOT)}: {added} new, {len(merged)} total")
                copied += 1
    print(f"copied {copied} file(s)")
    return copied


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", default=str(_DEFAULT_SRC), help="Backfill root (default /workspace/backfill)")
    parser.add_argument("--rebuild", action="store_true", help="Run scripts/build_history.py after copying")
    args = parser.parse_args(argv)
    load(args.src)
    if args.rebuild:
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        from build_history import main as rebuild
        rebuild()


if __name__ == "__main__":
    main()
