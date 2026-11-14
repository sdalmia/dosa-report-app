"""Load Alfred's daily store-by-channel (tab) workbooks into daily channel files.

Input: secondpass_daily_tabs_<tab>_<day1>_and_<day2>.xlsx (Posist Insights,
Deployment-wise, Day mode). Each workbook holds two individual days. Tabs vary
by day (ONDC and OWNLYONLINE are not listed every day); a tab or store that is
not in a workbook is absent, not zero. A day that sits in two workbooks
(11 Nov is in both 10–11 and 11–12 Nov) is counted once, after checking that
both copies agree.

Output:
  data/posist/daily_sales/channel_YYYY-MM-DD.csv  (store, store_code, date, source, sales, orders)
  data/posist/channel_tabwise_manifest.json       (days, tabs, stores, duplicate check)
  data/history/channel_tabwise_reconciliation.csv (channel total vs loaded store gross)

Store rules: Chattarpur and GK1 Cloud Kitchen are left out; Faridabad is left out
from 23 Oct 2026; Events & Catering is kept as its own row; zero cells
from the two-day export (0 sales and 0 orders) are not written as rows, so an
absent day stays absent (Rosedale's zero store-gross days are not touched).

Usage:
    python scripts/parse_tabwise_channels.py [/workspace/posist_insights/2026-11-13]
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

DEFAULT_SRC = Path("/workspace/posist_insights/2026-11-13")
DEST = _ROOT / "data" / "posist" / "daily_sales"
MANIFEST = _ROOT / "data" / "posist" / "channel_tabwise_manifest.json"
RECON = _ROOT / "data" / "history" / "channel_tabwise_reconciliation.csv"
FARIDABAD_CLOSED_FROM = date(2026, 10, 23)
_NAME = re.compile(r"secondpass_daily_tabs_([a-z]+)_(\d{4}-\d{2}-\d{2})_and_(\d{4}-\d{2}-\d{2})\.xlsx$")


def _day(text):
    head = str(text).split()[0]
    dd, mm, yy = head.split("-")
    return date(int(yy), int(mm), int(dd))


def _dec(value):
    if value is None or str(value).strip() == "":
        return None
    return Decimal(str(value))


def _code(store):
    match = re.search(r"\(([^()]*)\)\s*$", store) or re.search(r"(\d{2}/\d{4})\s*$", store)
    return match.group(1).strip() if match else ""


def _excluded(store, day):
    folded = store.casefold()
    if "chattarpur" in folded or "gk1" in folded or "gk 1" in folded or "gk-1" in folded:
        return True
    if "faridabad" in folded and day >= FARIDABAD_CLOSED_FROM:
        return True
    return False


def read_workbooks(src):
    import openpyxl

    records = {}
    copies = defaultdict(list)
    files = sorted(src.glob("secondpass_daily_tabs_*.xlsx"))
    for path in files:
        match = _NAME.search(path.name)
        if not match:
            continue
        tab = match.group(1).upper()
        sheet = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = list(sheet.iter_rows(values_only=True))
        header = rows[0]
        if header[0] != "Deployment Name" or len(header) < 6:
            raise SystemExit(f"unexpected header in {path.name}: {header}")
        days = [_day(header[1]), _day(header[2])]
        if [d.isoformat() for d in days] != [match.group(2), match.group(3)] or days != [_day(header[4]), _day(header[5])]:
            raise SystemExit(f"day columns do not match the file name in {path.name}: {header}")
        for row in rows[1:]:
            if not row or not row[0]:
                continue
            store = str(row[0]).strip()
            for i, day in enumerate(days):
                sales, orders = _dec(row[1 + i]), _dec(row[4 + i])
                if sales is None and orders is None:
                    continue
                key = (day, tab, store)
                copies[key].append((sales, orders, path.name))
                records.setdefault(key, (sales, orders))
    duplicates = {k: v for k, v in copies.items() if len({f for _, _, f in v}) > 1}
    disagree = {k: v for k, v in duplicates.items() if len({(s, o) for s, o, _ in v}) > 1}
    if disagree:
        raise SystemExit(f"overlapping workbooks disagree: {list(disagree.items())[:5]}")
    return files, records, duplicates


def main(argv):
    src = Path(argv[1]) if len(argv) > 1 else DEFAULT_SRC
    if not src.is_dir():
        print(f"  tabwise folder {src} not present; skipping")
        return
    if not (src / "_DONE_TABWISE").exists():
        print("  _DONE_TABWISE marker missing; the export may be incomplete")
    files, records, duplicates = read_workbooks(src)
    by_day = defaultdict(list)
    left_out = defaultdict(Decimal)
    zero_cells = 0
    for (day, tab, store), (sales, orders) in records.items():
        if not sales and not orders:
            # A two-day comparison export prints 0 for the day a store had no sales in that tab.
            # That is the same as no row, so it is not written as a zero.
            zero_cells += 1
            continue
        if _excluded(store, day):
            left_out[(day.isoformat(), store)] += sales or 0
            continue
        by_day[day].append({
            "store": store,
            "store_code": _code(store),
            "date": day.isoformat(),
            "source": tab,
            "sales": f"{sales:.2f}" if sales is not None else "",
            "orders": f"{orders:.0f}" if orders is not None else "",
        })
    DEST.mkdir(parents=True, exist_ok=True)
    fields = ["store", "store_code", "date", "source", "sales", "orders"]
    for day, rows in sorted(by_day.items()):
        rows.sort(key=lambda r: (r["store"], r["source"]))
        with (DEST / f"channel_{day.isoformat()}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    manifest = {
        "source_folder": str(src),
        "source": "Posist Insights, Deployment-wise sales by tab, Day mode (secondpass_daily_tabs_*.xlsx)",
        "workbooks": len(files),
        "days": [d.isoformat() for d in sorted(by_day)],
        "tabs_by_day": {d.isoformat(): sorted({r["source"] for r in rows}) for d, rows in sorted(by_day.items())},
        "stores_by_day": {d.isoformat(): len({r["store"] for r in rows}) for d, rows in sorted(by_day.items())},
        "duplicate_days": sorted({k[0].isoformat() for k in duplicates}),
        "duplicate_keys_checked": len(duplicates),
        "duplicate_keys_disagreeing": 0,
        "zero_cells_not_written": zero_cells,
        "left_out": [{"date": d, "store": s, "sales": f"{v:.2f}"} for (d, s), v in sorted(left_out.items())],
        "rules": "Absent tab or store = not in the file, not zero. Chattarpur and GK1 out; Faridabad out from 23 Oct 2026; Events & Catering kept as its own row.",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  tabwise channel days written: {len(by_day)} ({manifest['days'][0]} to {manifest['days'][-1]})")
    reconcile(by_day)


def reconcile(by_day):
    from app.chat.month_sales import _sales_by_store, _store_key

    gross = _sales_by_store()
    out = []
    for day, rows in sorted(by_day.items()):
        totals = defaultdict(lambda: [Decimal(0), ""])
        for row in rows:
            bucket = totals[_store_key(row["store"])]
            bucket[0] += Decimal(row["sales"] or 0)
            bucket[1] = row["store"]
        for key, (channel_total, store) in sorted(totals.items()):
            loaded = (gross.get(key) or {}).get("days", {}).get(day, {}).get("gross")
            if loaded is None:
                status = "no store gross loaded"
                diff = ""
            else:
                delta = channel_total - Decimal(str(loaded)).quantize(Decimal("0.01"))
                status = "match" if abs(delta) <= Decimal("1") else "mismatch"
                diff = f"{delta:.2f}"
            out.append({
                "date": day.isoformat(), "store": store, "channel_total": f"{channel_total:.2f}",
                "store_gross": "" if loaded is None else f"{loaded:.2f}", "difference": diff, "status": status,
            })
        for key, bucket in gross.items():
            loaded = bucket["days"].get(day, {}).get("gross")
            if loaded and key not in totals:
                out.append({"date": day.isoformat(), "store": bucket["name"], "channel_total": "",
                            "store_gross": f"{loaded:.2f}", "difference": "", "status": "no channel rows"})
    RECON.parent.mkdir(parents=True, exist_ok=True)
    with RECON.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "store", "channel_total", "store_gross", "difference", "status"])
        writer.writeheader()
        writer.writerows(out)
    counts = defaultdict(int)
    for row in out:
        counts[row["status"]] += 1
    print(f"  tabwise reconciliation: {dict(counts)}")


if __name__ == "__main__":
    main(sys.argv)
