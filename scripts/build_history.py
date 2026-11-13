"""Build data/history monthly aggregates from files already on disk.

Run from the repo root:  python scripts/build_history.py

Every figure is copied or summed from a source file. A missing month is
left out; it is never filled with zero or an estimate. Re-running replaces
the generated files. Copied source files (channel days, menu extracts,
Sanjoy's workbook) are left in place if they already exist.

This script is for a data PR. The Wizard at runtime reads the CSVs under
data/history and data/posist/daily_sales; it does not need /workspace.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from parse_tally_daybooks import (  # noqa: E402
    collect_from,
    load_csv,
    merge_vouchers,
    write_csv as write_vouchers,
)

WINDOW_START = date(2026, 4, 1)
WINDOW_END = date(2026, 11, 13)
FARIDABAD_OUT = date(2026, 10, 23)
_CLOSED = ("chattarpur", "gk1", "gk 1")
_HISTORY = _ROOT / "data" / "history"
_BOX_POSIST = Path("/workspace/dosa-coffee-mis/posist/daily_sales")
_BOX_MENU = Path("/workspace/dosa-coffee-mis/posist/command_centre/monthly_menu/2026-10")
_BOX_AGG = Path(
    "/workspace/wizard_data/sanjoy_2026-11-13"
    "/Dosa Coffee - Brand Aggregator Performance - Aug-Oct 2026.xlsx"
)
_TALLY_PACKS = [
    *[Path(f"/workspace/tally/daily/2026-10-{d:02d}") for d in range(16, 28)],
    Path("/workspace/tally/daily/2026-11-06_to_11"),
]

# Outlet key -> (store_master name, match_status, note)
# Mapped only when the store master or the same DC key on the other platform is clear.
# Faridabad (DC-09) is left out. Unmapped names stay as in the workbook.
_AGG_MAP = {
    "DC-01": ("Connaught Place", "mapped", "store_master name"),
    "DC-02": ("Gurgaon DLF", "mapped", "DLF Cyber Greens is Gurgaon DLF in store_master"),
    "DC-03": ("Pacific Mall Jasola", "mapped", "Jasola is Pacific Mall Jasola in store_master"),
    "DC-04": ("Kalkaji", "mapped", "store_master name"),
    "DC-05": ("Model Town", "mapped", "Model Town 2 is Model Town in store_master"),
    "DC-06": ("Paschim Vihar", "mapped", "store_master name"),
    "DC-07": ("Rohini Sec-7", "mapped", "Rohini is Rohini Sec-7 in store_master"),
    "DC-08": ("Gurgaon Sec 10", "mapped", "Sector 10A is Gurgaon Sec 10 in store_master"),
    "DC-09": ("Sec 15 Faridabad", "excluded", "Faridabad is left out of aggregator totals"),
    "DC-10": ("Gurgaon Sec-15", "mapped", "same outlet key as Swiggy Sector 15 (Gurgaon)"),
    "DC-11": ("Sec 18 Noida", "mapped", "Sector 18 / Noida Sector 18 is Sec 18 Noida in store_master"),
    "DC-12": ("Sec 31 Gurgaon", "mapped", "Sector 31 / Gurgaon Sector 31 is Sec 31 Gurgaon in store_master"),
    "DC-13": (
        "Sec 143 Noida",
        "mapped",
        "same outlet key DC-13 as Swiggy Noida Sector 143; Zomato label is Shahdara",
    ),
    "DC-14": ("Shalimar Bagh", "mapped", "store_master name"),
    "DC-15": ("James Long Sarani", "mapped", "store_master famepilot name is Jameslong Behala"),
    "DC-16": ("Belur", "unmapped", "no confident store_master match; original name kept"),
    "DC-17": ("Elgin", "unmapped", "no confident store_master match; original name kept"),
    "DC-18": ("Kalikapur", "mapped", "store_master name"),
    "DC-19": ("Kankurgachi", "unmapped", "no confident store_master match; original name kept"),
    "DC-20": ("Lake Market Area", "unmapped", "no confident store_master match; original name kept"),
    "DC-21": ("Lake Town", "mapped", "store_master name"),
    "DC-22": ("Rosedale Plaza", "mapped", "same outlet key as Swiggy New Town (Rosedale Plaza)"),
    "DC-23": ("New Town Cloud Kitchen", "mapped", "same outlet key as Swiggy New Town (Cloud Kitchen)"),
    "DC-24": ("Santoshpur", "mapped", "store_master name"),
    "DC-25": ("Salt Lake Sec-1", "mapped", "Sector 1, Salt Lake is Salt Lake Sec-1 in store_master"),
    "DC-26": ("Salt Lake Sec-3", "mapped", "Sector 3, Salt Lake is Salt Lake Sec-3 in store_master"),
}


def _num(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace("₹", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text[:11] if fmt.startswith("%d-%b") else text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _month_key(day):
    return f"{day.year:04d}-{day.month:02d}" if day else ""


def _closed(name):
    text = (name or "").casefold()
    return any(token in text for token in _CLOSED)


def _skip_day(store, day):
    if day is None or _closed(store):
        return True
    if "faridabad" in (store or "").casefold() and day >= FARIDABAD_OUT:
        return True
    return False


def _region(store, region=""):
    text = (region or "").strip()
    folded = text.casefold()
    if folded in {"east", "kolkata"}:
        return "East"
    if folded in {"north", "ncr", "delhi", "delhi ncr"}:
        return "North"
    name = (store or "").casefold()
    if "event" in name or "cater" in name:
        return "Events"
    if re.search(r"\(02/", store or "") or any(
        token in name for token in ("noida", "gurgaon", "faridabad", "connaught", "kalkaji", "rohini", "paschim", "shalimar", "model town", "jasola", "pacific")
    ):
        return "North"
    if re.search(r"\(01/", store or "") or re.search(r"\(\d{3,4}\)", store or ""):
        return "East"
    return text or ""


def _city_label(region):
    if region == "East":
        return "Kolkata"
    if region == "North":
        return "NCR"
    return region or ""


def _store_key(name):
    text = re.sub(r"\s*\([^)]*\)", "", name or "")
    text = re.sub(r"(?i)^dosa coffee\s*-\s*", "", text)
    return " ".join(text.split()).casefold()


def write_rows(path, fields, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: "" if row.get(name) is None else row.get(name) for name in fields})
    print(f"  wrote {path.relative_to(_ROOT)} ({len(rows)} rows)")


def copy_channel_files():
    dest = _ROOT / "data" / "posist" / "daily_sales"
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    if not _BOX_POSIST.is_dir():
        print("  box posist folder not present; skipping channel copy")
        return
    for path in sorted(_BOX_POSIST.glob("channel_*.csv")):
        target = dest / path.name
        if target.is_file() and target.stat().st_size == path.stat().st_size:
            continue
        shutil.copy2(path, target)
        copied += 1
    print(f"  channel files copied: {copied}")
    # Oct 2-8 daily extract (not in the dated channel_*.csv drop)
    early = Path("/workspace/dosa-coffee-mis/posist/command_centre/channel_sales_daily_2026-10-02_2026-10-08.csv")
    if early.is_file():
        by_day = {}
        with early.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                day = (raw.get("date") or "").strip()
                if not day:
                    continue
                by_day.setdefault(day, []).append(raw)
        written = 0
        for day, rows in sorted(by_day.items()):
            target = dest / f"channel_{day}.csv"
            if target.is_file():
                continue
            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["store", "store_code", "date", "source", "sales", "orders"])
                writer.writeheader()
                for raw in rows:
                    writer.writerow({
                        "store": raw.get("store") or "",
                        "store_code": raw.get("store_code") or "",
                        "date": raw.get("date") or "",
                        "source": raw.get("source") or "",
                        "sales": raw.get("gross") or raw.get("sales") or "",
                        "orders": raw.get("orders") or "",
                    })
            written += 1
        print(f"  early October channel days written: {written}")
    # 9 Sep-8 Oct is a 30-day window, not a calendar month. Copy for reference only.
    rng = Path("/workspace/dosa-coffee-mis/posist/command_centre/channel_sales_range_2026-09-09_2026-10-08.csv")
    if rng.is_file():
        target = _ROOT / "data" / "posist" / "channel_sales_range_2026-09-09_2026-10-08.csv"
        if not target.is_file():
            shutil.copy2(rng, target)
            print(f"  copied 9 Sep-8 Oct channel range (not used as a calendar month)")


def copy_oct_menu():
    dest = _ROOT / "data" / "menu" / "monthly" / "2026-10"
    dest.mkdir(parents=True, exist_ok=True)
    if not _BOX_MENU.is_dir():
        print("  box October menu folder not present; skipping")
        return dest
    copied = 0
    for path in sorted(_BOX_MENU.glob("*.xlsx")):
        target = dest / path.name
        if not target.is_file():
            shutil.copy2(path, target)
            copied += 1
    print(f"  October menu workbooks copied: {copied}")
    return dest


def _menu_stores():
    path = Path("/workspace/menu_mix/stores.csv")
    repo = _ROOT / "data" / "menu" / "stores.csv"
    src = path if path.is_file() else repo
    mapping = {}
    if src.is_file():
        with src.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                code = (raw.get("store_code") or "").strip()
                name = (raw.get("store") or "").strip()
                if code and name:
                    mapping[code] = name
    return mapping


def build_oct_menu_csv(folder):
    from openpyxl import load_workbook

    stores = _menu_stores()
    rows = []
    for path in sorted(Path(folder).glob("*.xlsx")):
        code = path.stem  # 01-0001 or events_catering
        if code.lower().startswith("events"):
            store = "Events & Catering"
        else:
            name = stores.get(code) or stores.get(code.replace("-", "/")) or code
            display_code = code.replace("-", "/")
            store = f"{name} ({display_code})"
        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb[wb.sheetnames[0]]
            for i, raw in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    continue
                item = (raw[0] if raw else None)
                if not item:
                    continue
                sales = _num(raw[1] if len(raw) > 1 else None)
                orders = _num(raw[2] if len(raw) > 2 else None)
                contrib = _num(raw[3] if len(raw) > 3 else None)
                rows.append({
                    "store": store,
                    "item": str(item).strip(),
                    "total_sales": "" if sales is None else f"{sales}",
                    "total_orders": "" if orders is None else f"{orders}",
                    "contribution_pct": "" if contrib is None else f"{contrib}",
                    "period_start": "2026-10-01",
                    "period_end": "2026-10-31",
                    "source": path.name,
                })
        finally:
            wb.close()
    dest = _ROOT / "data" / "menu" / "menu_mix_2026-10.csv"
    write_rows(
        dest,
        ["store", "item", "total_sales", "total_orders", "contribution_pct", "period_start", "period_end", "source"],
        rows,
    )
    meta = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "source": "Posist monthly menu extracts, data/menu/monthly/2026-10",
        "stores": len({r["store"] for r in rows}),
        "rows": len(rows),
        "note": "Calendar October. Faridabad (02-0007) is in the extract as received; the store closed 22 Oct. Figures are not adjusted.",
    }
    dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return rows


def parse_tally():
    dest_dir = _ROOT / "data" / "tally" / "2026-11-13"
    dest = dest_dir / "daybook_vouchers.csv"
    existing = load_csv(dest)
    incoming = collect_from(_TALLY_PACKS)
    merged, added = merge_vouchers(existing, incoming)
    write_vouchers(dest, merged)
    print(f"  tally vouchers: {len(existing)} existing, {added} added, {len(merged)} total")
    readme = dest_dir / "README.md"
    extra = (
        "\n\nUpdated in the April 2026 history PR: parsed the raw Day Book packs "
        "already on the box for 16–27 Oct (single-day extracts, including later "
        "pages the original 16 Oct load missed) and 6–11 Nov (voucher dates 6, 8, 9 "
        "and 11 Nov only; 7 and 10 Nov are not in the pack). Bank statements in "
        "those folders were not loaded as Tally vouchers. Missing days are left "
        "out, not filled with zero. Dedup is by company, date, type, and voucher no.\n"
    )
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        if "16–27 Oct" not in text and "16-27 Oct" not in text:
            readme.write_text(text.rstrip() + extra, encoding="utf-8")
    return merged


def _type_group(vtype):
    text = (vtype or "").strip()
    head = text.split("-", 1)[0].strip().title()
    if head.lower() == "journal":
        return "Journal"
    if head.lower() == "payment":
        return "Payment"
    if head.lower() == "receipt":
        return "Receipt"
    if head.lower() == "sales":
        return "Sales"
    if head.lower() == "purchase":
        return "Purchase"
    if head.lower() == "contra":
        return "Contra"
    if "credit" in head.lower():
        return "Credit Note"
    return head or "Other"


def build_tally_month(vouchers):
    buckets = defaultdict(lambda: {
        "voucher_count": 0, "total_amt": Decimal("0"), "days": set(),
    })
    for row in vouchers:
        day = _day(row.get("date"))
        if day is None or day < WINDOW_START:
            continue
        amount = _num(row.get("amt"))
        key = (_month_key(day), row.get("company") or "", _type_group(row.get("type")))
        bucket = buckets[key]
        bucket["voucher_count"] += 1
        if amount is not None:
            bucket["total_amt"] += Decimal(str(amount))
        bucket["days"].add(day)
    rows = []
    for (month, company, group), bucket in sorted(buckets.items()):
        year, mon = int(month[:4]), int(month[5:7])
        days_in = monthrange(year, mon)[1]
        rows.append({
            "month": month,
            "company": company,
            "type_group": group,
            "voucher_count": bucket["voucher_count"],
            "total_amt": f"{bucket['total_amt']}",
            "days_present": len(bucket["days"]),
            "days_in_month": days_in,
            "complete": "yes" if len(bucket["days"]) == days_in else "no",
            "first_day": min(bucket["days"]).isoformat() if bucket["days"] else "",
            "last_day": max(bucket["days"]).isoformat() if bucket["days"] else "",
            "note": "Missing days are left out, not treated as zero.",
        })
    write_rows(
        _HISTORY / "tally_company_month.csv",
        ["month", "company", "type_group", "voucher_count", "total_amt",
         "days_present", "days_in_month", "complete", "first_day", "last_day", "note"],
        rows,
    )


def build_sales():
    from app.chat.month_sales import _sales_by_store, is_mall_food_court
    # is_mall is in food_courts; import via month_sales context
    from app.food_courts import is_mall_food_court as mall

    grouped = _sales_by_store()
    store_rows = []
    city_acc = defaultdict(lambda: defaultdict(lambda: {
        "gross": 0.0, "bills_ex_mall": 0.0, "mall_gross": 0.0, "days": set(), "stores": 0,
    }))
    for rec in grouped.values():
        name = rec["name"]
        region = rec.get("region") or _region(name)
        by_month = defaultdict(lambda: {"gross": 0.0, "bills": 0.0, "net": 0.0, "net_n": 0, "days": set()})
        for day, vals in rec["days"].items():
            if day < WINDOW_START or day > WINDOW_END:
                continue
            gross = vals.get("gross")
            if gross is None:
                continue
            month = _month_key(day)
            bucket = by_month[month]
            bucket["gross"] += float(gross)
            if vals.get("bills") is not None:
                bucket["bills"] += float(vals["bills"])
            if vals.get("net") is not None:
                bucket["net"] += float(vals["net"])
                bucket["net_n"] += 1
            bucket["days"].add(day)
        for month, bucket in sorted(by_month.items()):
            year, mon = int(month[:4]), int(month[5:7])
            days_in = monthrange(year, mon)[1]
            is_mall = mall(name)
            store_rows.append({
                "month": month,
                "store": name,
                "region": region,
                "city": _city_label(region),
                "gross": f"{bucket['gross']:.2f}",
                "bills": "" if is_mall else f"{bucket['bills']:.2f}",
                "net": f"{bucket['net']:.2f}" if bucket["net_n"] else "",
                "days_present": len(bucket["days"]),
                "days_in_month": days_in,
                "complete": "yes" if len(bucket["days"]) == days_in else "no",
                "mall_bulk": "yes" if is_mall else "no",
                "first_day": min(bucket["days"]).isoformat(),
                "last_day": max(bucket["days"]).isoformat(),
            })
            city = city_acc[_city_label(region)][month]
            city["gross"] += bucket["gross"]
            if is_mall:
                city["mall_gross"] += bucket["gross"]
            else:
                city["bills_ex_mall"] += bucket["bills"]
            city["days"].update(bucket["days"])
            city["stores"] += 1
    write_rows(
        _HISTORY / "sales_store_month.csv",
        ["month", "store", "region", "city", "gross", "bills", "net",
         "days_present", "days_in_month", "complete", "mall_bulk", "first_day", "last_day"],
        sorted(store_rows, key=lambda r: (r["month"], r["city"], r["store"])),
    )
    city_rows = []
    for city, months in sorted(city_acc.items()):
        for month, bucket in sorted(months.items()):
            year, mon = int(month[:4]), int(month[5:7])
            days_in = monthrange(year, mon)[1]
            note = ""
            if month == "2026-09":
                note = "Daily file starts 4 Sep; 1–3 Sep are not on file."
            elif month == "2026-11":
                note = "Through 12 Nov; the month is not complete."
            city_rows.append({
                "month": month,
                "city": city,
                "gross": f"{bucket['gross']:.2f}",
                "bills_ex_mall": f"{bucket['bills_ex_mall']:.2f}",
                "mall_gross": f"{bucket['mall_gross']:.2f}",
                "days_present": len(bucket["days"]),
                "days_in_month": days_in,
                "complete": "yes" if len(bucket["days"]) == days_in else "no",
                "stores": bucket["stores"],
                "first_day": min(bucket["days"]).isoformat() if bucket["days"] else "",
                "last_day": max(bucket["days"]).isoformat() if bucket["days"] else "",
                "note": note,
            })
    write_rows(
        _HISTORY / "sales_city_month.csv",
        ["month", "city", "gross", "bills_ex_mall", "mall_gross", "days_present",
         "days_in_month", "complete", "stores", "first_day", "last_day", "note"],
        city_rows,
    )


def build_channel():
    folder = _ROOT / "data" / "posist" / "daily_sales"
    acc = defaultdict(lambda: {"sales": 0.0, "orders": 0.0, "days": set()})
    if folder.is_dir():
        for path in sorted(folder.glob("channel_*.csv")):
            stamp = _day(path.stem.replace("channel_", ""))
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for raw in csv.DictReader(handle):
                    day = _day(raw.get("date")) or stamp
                    store = (raw.get("store") or "").strip()
                    if _skip_day(store, day) or day is None or day < WINDOW_START:
                        continue
                    source = (raw.get("source") or "").strip()
                    sales = _num(raw.get("sales")) or 0.0
                    orders = _num(raw.get("orders")) or 0.0
                    key = (_month_key(day), store, _region(store, raw.get("region") or ""), source)
                    bucket = acc[key]
                    bucket["sales"] += sales
                    bucket["orders"] += orders
                    bucket["days"].add(day)
    rows = []
    for (month, store, region, source), bucket in sorted(acc.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][3])):
        year, mon = int(month[:4]), int(month[5:7])
        days_in = monthrange(year, mon)[1]
        note = ""
        if month == "2026-11":
            note = "9 Nov channel file is not on disk; that day is left out, not treated as zero. Through 12 Nov."
        elif month == "2026-10":
            note = "Store-level channel days are 2–15 Oct (2–8 from a daily extract; 9–15 from dated files). 16–31 Oct files are network totals only (ALL (network) / ALL DEPLOYMENTS). 1 Oct is not on file."
        rows.append({
            "month": month,
            "store": store,
            "region": region,
            "city": _city_label(region),
            "source": source,
            "sales": f"{bucket['sales']:.2f}",
            "orders": f"{bucket['orders']:.2f}",
            "days_present": len(bucket["days"]),
            "days_in_month": days_in,
            "complete": "yes" if len(bucket["days"]) == days_in else "no",
            "first_day": min(bucket["days"]).isoformat(),
            "last_day": max(bucket["days"]).isoformat(),
            "note": note,
        })
    write_rows(
        _HISTORY / "channel_store_month.csv",
        ["month", "store", "region", "city", "source", "sales", "orders",
         "days_present", "days_in_month", "complete", "first_day", "last_day", "note"],
        rows,
    )



def copy_procurement_backfill():
    """Copy April–early September PurchaseEasy drops into the repo."""
    dest_root = _ROOT / "data" / "procurement" / "backfill"
    srcs = [
        Path("/workspace/backfill/procurement"),
        dest_root,
    ]
    copied = 0
    src = Path("/workspace/backfill/procurement")
    if src.is_dir():
        for folder in sorted(src.iterdir()):
            if not folder.is_dir():
                continue
            # Only PurchaseEasy Entry Reports and Purchase Summaries. Other
            # drops in the same tree (consumption, wastage) are left for a
            # later data PR.
            reports = list(folder.glob("entry_report_*")) + list(folder.glob("purchase_summary_*"))
            if not reports:
                continue
            target = dest_root / folder.name
            target.mkdir(parents=True, exist_ok=True)
            for path in sorted(folder.iterdir()):
                if not path.is_file():
                    continue
                # Skip non-purchase files that may sit in the same month folder.
                name = path.name.casefold()
                if not (
                    name.startswith("entry_report_")
                    or name.startswith("purchase_summary_")
                    or name == "readme.md"
                ):
                    continue
                dest = target / path.name
                if dest.is_file() and dest.stat().st_size == path.stat().st_size:
                    continue
                shutil.copy2(path, dest)
                copied += 1
    print(f"  procurement backfill files copied: {copied}")
    return dest_root if dest_root.is_dir() else src


def build_procurement():
    """Purchases and prices from the April–8 Sep backfill, the 9 Sep–8 Oct GRN, and procurement_summary.json."""
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    from parse_procurement_backfill import parse_tree

    roots = [
        _ROOT / "data" / "procurement" / "backfill",
        Path("/workspace/backfill/procurement"),
    ]
    # Prefer the repo copy so a rebuild on a machine without /workspace still works.
    # parse_tree is additive; skip the workspace tree when the repo copy is present.
    parse_roots = []
    if (_ROOT / "data" / "procurement" / "backfill").is_dir() and any(
        (_ROOT / "data" / "procurement" / "backfill").iterdir()
    ):
        parse_roots = [_ROOT / "data" / "procurement" / "backfill"]
    else:
        parse_roots = [Path("/workspace/backfill/procurement")]
    bf_items, bf_charges, bf_prices, bf_issues, bf_checks = parse_tree(parse_roots)
    notes_path = _HISTORY / "procurement_parse_notes.json"
    notes_path.write_text(
        json.dumps({"issues": bf_issues, "checks": bf_checks}, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"  procurement backfill: {len(bf_items)} item lines, {len(bf_prices)} price rows, {len(bf_issues)} parse issues")

    item_acc = defaultdict(lambda: {"qty": 0.0, "total": 0.0, "sub_total": 0.0, "lines": 0, "days": set(), "unit": "", "sources": set()})
    vendor_acc = defaultdict(lambda: {"total": 0.0, "lines": 0, "days": set(), "items": set(), "sources": set()})
    charge_acc = defaultdict(lambda: {"total": 0.0, "lines": 0, "days": set()})

    def add_item(month, city, item, code, unit, qty, total, day, vendor, warehouse, source, sub_total=None):
        if not month or month < "2026-04":
            return
        ik = (month, city, item, str(code or ""), unit or "")
        item_acc[ik]["qty"] += qty or 0.0
        item_acc[ik]["total"] += total or 0.0
        item_acc[ik]["sub_total"] += (sub_total if sub_total is not None else (total or 0.0))
        item_acc[ik]["lines"] += 1
        if day:
            item_acc[ik]["days"].add(day)
        item_acc[ik]["unit"] = unit or item_acc[ik]["unit"]
        item_acc[ik]["sources"].add(source or "")
        vk = (month, city, vendor or "", warehouse or "")
        vendor_acc[vk]["total"] += total or 0.0
        vendor_acc[vk]["lines"] += 1
        if day:
            vendor_acc[vk]["days"].add(day)
        if item:
            vendor_acc[vk]["items"].add(item)
        vendor_acc[vk]["sources"].add(source or "")

    for row in bf_items:
        day = row.get("date")
        month = row.get("month") or (f"{day.year:04d}-{day.month:02d}" if day else "")
        add_item(
            month, row.get("city") or "", row.get("item") or "", row.get("item_code") or "",
            row.get("unit") or "", row.get("qty") or 0.0,
            row.get("total") if row.get("total") is not None else (row.get("sub_total") or 0.0),
            day, row.get("vendor") or "", row.get("warehouse") or "",
            row.get("source") or "entry_report",
            sub_total=row.get("sub_total"),
        )
    for row in bf_charges:
        day = row.get("date")
        month = row.get("month") or (f"{day.year:04d}-{day.month:02d}" if day else "")
        charge = row.get("charge") or ""
        folded = charge.casefold()
        if not any(tok in folded for tok in ("freight", "transport", "tcs")):
            continue
        key = (month, row.get("city") or "", row.get("vendor") or "", charge)
        charge_acc[key]["total"] += row.get("total") or 0.0
        charge_acc[key]["lines"] += 1
        if day:
            charge_acc[key]["days"].add(day)

    grn = _ROOT / "data" / "procurement" / "grn_lines_warehouses.csv"
    if grn.is_file():
        with grn.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                day = _day(raw.get("date"))
                if day is None or day < WINDOW_START:
                    continue
                month = _month_key(day)
                add_item(
                    month, (raw.get("city") or "").strip(), (raw.get("item_name") or "").strip(),
                    raw.get("item_code") or "", raw.get("unit") or "",
                    _num(raw.get("qty")) or 0.0,
                    _num(raw.get("total") or raw.get("sub_total")) or 0.0,
                    day, (raw.get("supplier") or "").strip(), raw.get("warehouse") or "",
                    "grn_lines_warehouses.csv",
                    sub_total=_num(raw.get("sub_total")),
                )

    def month_note(month, days):
        if not days:
            return "no", ""
        first, last = min(days), max(days)
        year, mon = int(month[:4]), int(month[5:7])
        days_in = monthrange(year, mon)[1]
        # April–August are calendar-month extracts. Completeness is for the
        # month file, not for one item or vendor.
        if "2026-04" <= month <= "2026-08":
            return "yes", (
                f"Calendar {month} from Procurement Entry Reports (item lines, tax inclusive). "
                "A day with no GRN is a day with no invoice, left out not treated as zero. "
                "Freight and other invoice charges are in purchases_charges_month.csv."
            )
        if month == "2026-09":
            return "no", (
                f"September combines the 1–8 Sep Entry Report backfill with GRN lines from 9–30 Sep "
                f"({first.isoformat()} to {last.isoformat()}, {len(days)} days with an entry). "
                "1 Oct onward is not in this row. The month is complete for purchases only through 30 Sep; "
                "Delhi has no 1 Sep or 6 Sep entry in the 1–8 Sep pack."
            )
        if month == "2026-10":
            return "no", (
                f"GRN lines {first.isoformat()} to {last.isoformat()} only; not a full calendar month."
            )
        return "no", f"{first.isoformat()} to {last.isoformat()} only."

    item_rows = []
    for (month, city, item, code, unit), bucket in sorted(item_acc.items()):
        first = min(bucket["days"]) if bucket["days"] else None
        last = max(bucket["days"]) if bucket["days"] else None
        complete, note = month_note(month, bucket["days"])
        item_rows.append({
            "month": month,
            "city": city,
            "item": item,
            "item_code": code,
            "unit": unit or bucket["unit"],
            "qty": f"{bucket['qty']}",
            "total": f"{bucket['total']:.2f}",
            "line_count": bucket["lines"],
            "first_day": first.isoformat() if first else "",
            "last_day": last.isoformat() if last else "",
            "complete": complete,
            "note": note,
        })
    write_rows(
        _HISTORY / "purchases_item_month.csv",
        ["month", "city", "item", "item_code", "unit", "qty", "total",
         "line_count", "first_day", "last_day", "complete", "note"],
        item_rows,
    )
    vendor_rows = []
    for (month, city, vendor, warehouse), bucket in sorted(vendor_acc.items()):
        first = min(bucket["days"]) if bucket["days"] else None
        last = max(bucket["days"]) if bucket["days"] else None
        complete, note = month_note(month, bucket["days"])
        vendor_rows.append({
            "month": month,
            "city": city,
            "vendor": vendor,
            "warehouse": warehouse,
            "total": f"{bucket['total']:.2f}",
            "line_count": bucket["lines"],
            "item_count": len(bucket["items"]),
            "first_day": first.isoformat() if first else "",
            "last_day": last.isoformat() if last else "",
            "complete": complete,
            "note": note,
        })
    write_rows(
        _HISTORY / "purchases_vendor_month.csv",
        ["month", "city", "vendor", "warehouse", "total", "line_count", "item_count",
         "first_day", "last_day", "complete", "note"],
        vendor_rows,
    )
    charge_rows = []
    for (month, city, vendor, charge), bucket in sorted(charge_acc.items()):
        first = min(bucket["days"]) if bucket["days"] else None
        last = max(bucket["days"]) if bucket["days"] else None
        charge_rows.append({
            "month": month,
            "city": city,
            "vendor": vendor,
            "charge": charge,
            "total": f"{bucket['total']:.2f}",
            "line_count": bucket["lines"],
            "first_day": first.isoformat() if first else "",
            "last_day": last.isoformat() if last else "",
            "note": "Invoice charges from Entry Report (Freight, Transport, TCS). Not included in item purchase totals.",
        })
    write_rows(
        _HISTORY / "purchases_charges_month.csv",
        ["month", "city", "vendor", "charge", "total", "line_count", "first_day", "last_day", "note"],
        charge_rows,
    )

    # Prices: official Purchase Summary for Apr–Aug (complete months) and the
    # 1–8 Sep slice. September full-month prices also use a qty-weighted average
    # of 1–8 Sep entry lines plus 9–30 Sep GRN lines. October and November stay
    # on procurement_summary.json.
    price_rows = []
    seen_summary = set()
    for raw in bf_prices:
        month = raw.get("month") or ""
        if month >= "2026-10":
            continue
        key = (month, raw.get("city"), raw.get("item_code"), raw.get("item"))
        seen_summary.add(key)
        price_rows.append({
            "month": month,
            "city": raw.get("city") or "",
            "item": raw.get("item") or "",
            "item_code": raw.get("item_code") or "",
            "unit": raw.get("unit") or "",
            "avg_unit_price": raw.get("unit_price") if raw.get("unit_price") is not None else "",
            "qty": raw.get("qty") if raw.get("qty") is not None else "",
            "complete": raw.get("complete") or "no",
            "note": raw.get("note") or "",
        })
    # September weighted prices from all Sep item lines (1–8 backfill + 9–30 GRN),
    # so the month is not left as a 1–8 slice only.
    sep_price = defaultdict(lambda: {"qty": 0.0, "sub": 0.0, "unit": "", "city": "", "item": "", "code": ""})
    for (month, city, item, code, unit), bucket in item_acc.items():
        if month != "2026-09":
            continue
        if not bucket["qty"]:
            continue
        key = (city, item, str(code or ""))
        sep_price[key]["qty"] += bucket["qty"]
        # Prefer sub_total / qty (ex-tax), falling back to total.
        sep_price[key]["sub"] += bucket["sub_total"] or bucket["total"]
        sep_price[key]["unit"] = unit or bucket["unit"]
        sep_price[key]["city"] = city
        sep_price[key]["item"] = item
        sep_price[key]["code"] = code
    # Replace the 1–8 Sep summary prices with the combined Sep weighted averages.
    price_rows = [row for row in price_rows if row["month"] != "2026-09"]
    for key, bucket in sorted(sep_price.items()):
        avg = bucket["sub"] / bucket["qty"] if bucket["qty"] else None
        days = set()
        for (month, city, item, code, unit), ib in item_acc.items():
            if month == "2026-09" and city == bucket["city"] and item == bucket["item"] and str(code or "") == str(bucket["code"] or ""):
                days |= ib["days"]
        first = min(days).isoformat() if days else "2026-09-01"
        last = max(days).isoformat() if days else "2026-09-30"
        price_rows.append({
            "month": "2026-09",
            "city": bucket["city"],
            "item": bucket["item"],
            "item_code": bucket["code"],
            "unit": bucket["unit"],
            "avg_unit_price": f"{avg:.4f}" if avg is not None else "",
            "qty": f"{bucket['qty']}",
            "complete": "yes" if first[:10] <= "2026-09-02" and last[:10] >= "2026-09-30" else "no",
            "note": (
                f"Qty-weighted average (subtotal/qty) from 1–8 Sep Entry Reports plus 9–30 Sep GRN lines "
                f"({first} to {last}). The 1–8 Sep Purchase Summary is a slice, not used as a full-month price."
            ),
        })

    summary_path = _ROOT / "data" / "procurement" / "procurement_summary.json"
    if summary_path.is_file():
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        monthly = (payload or {}).get("monthly_prices") or {}
        items = monthly.get("items") or []
        as_of = (payload.get("as_of") or payload.get("as_of_date") or "2026-11-12")
        for raw in items:
            city = raw.get("city") or ""
            item = raw.get("item") or ""
            code = raw.get("item_code") or ""
            unit = raw.get("unit") or ""
            last = raw.get("last_month") or {}
            this = raw.get("this_month") or {}
            if last:
                price_rows.append({
                    "month": "2026-10",
                    "city": city,
                    "item": item,
                    "item_code": code,
                    "unit": unit,
                    "avg_unit_price": last.get("avg_unit_price") if last.get("avg_unit_price") is not None else "",
                    "qty": last.get("qty") if last.get("qty") is not None else "",
                    "complete": "yes",
                    "note": "October 2026 complete, from procurement_summary.json last_month.",
                })
            if this:
                price_rows.append({
                    "month": "2026-11",
                    "city": city,
                    "item": item,
                    "item_code": code,
                    "unit": unit,
                    "avg_unit_price": this.get("avg_unit_price") if this.get("avg_unit_price") is not None else "",
                    "qty": this.get("qty") if this.get("qty") is not None else "",
                    "complete": "no",
                    "note": f"November 1–12 2026 (as_of {as_of}), from procurement_summary.json this_month.",
                })
    write_rows(
        _HISTORY / "prices_item_month.csv",
        ["month", "city", "item", "item_code", "unit", "avg_unit_price", "qty", "complete", "note"],
        price_rows,
    )


def build_menu_month():
    sources = [
        (_ROOT / "data" / "menu" / "menu_mix_2026-09_2de5.csv", "2026-09", "2026-09-01", "2026-09-30",
         "Calendar September from menu_mix_2026-09_2de5.csv."),
        (_ROOT / "data" / "menu" / "menu_mix_2026-10.csv", "2026-10", "2026-10-01", "2026-10-31",
         "Calendar October from the Posist monthly menu extracts."),
    ]
    rows = []
    for path, month, start, end, note in sources:
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                rows.append({
                    "month": month,
                    "store": (raw.get("store") or "").strip(),
                    "item": (raw.get("item") or "").strip(),
                    "total_sales": (raw.get("total_sales") or "").replace(",", ""),
                    "total_orders": (raw.get("total_orders") or "").replace(",", ""),
                    "contribution_pct": raw.get("contribution_pct") or "",
                    "period_start": raw.get("period_start") or start,
                    "period_end": raw.get("period_end") or end,
                    "source": path.name,
                    "note": note,
                })
    write_rows(
        _HISTORY / "menu_item_month.csv",
        ["month", "store", "item", "total_sales", "total_orders", "contribution_pct",
         "period_start", "period_end", "source", "note"],
        rows,
    )


def _reelo_month_from_period(text):
    text = (text or "").strip()
    months = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    folded = text.casefold()
    year = "2026"
    m = re.search(r"20\d{2}", text)
    if m:
        year = m.group(0)
    for name, num in months.items():
        if re.search(r"\b" + name + r"\b", folded):
            return f"{year}-{num}"
    return ""


def build_reelo():
    folder = _ROOT / "data" / "reelo" / "2026-11-13"
    rows_by_month = {}

    def take(path, field_map, month_field="period"):
        if not path.is_file():
            return
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                month = _reelo_month_from_period(raw.get(month_field) or raw.get("period") or raw.get("date") or "")
                if not month or month < "2026-04" or month > "2026-11":
                    continue
                bucket = rows_by_month.setdefault(month, {"month": month, "source": path.name})
                for dest, src in field_map.items():
                    val = raw.get(src)
                    if val not in (None, ""):
                        bucket[dest] = str(val).replace(",", "")
                bucket["period_label"] = raw.get("period") or raw.get("date") or bucket.get("period_label") or ""

    take(
        folder / "customers_monthly_all_stores_2026-01-01_to_2026-10-31.csv",
        {},
    )
    # Inspect and copy all numeric columns we can name safely
    for fname, default_prefix in (
        ("customers_monthly_all_stores_2026-01-01_to_2026-10-31.csv", "customers"),
        ("orders_monthly_all_stores_2026-01-01_to_2026-10-31.csv", "orders"),
        ("average_spend_monthly_all_stores_2026-01-01_to_2026-10-31.csv", "spend"),
    ):
        path = folder / fname
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames or []
            for raw in reader:
                period_val = raw.get("period") or raw.get("Period") or raw.get("date") or raw.get("Date") or ""
                month = _reelo_month_from_period(period_val)
                if not month or month < "2026-04" or month > "2026-11":
                    continue
                bucket = rows_by_month.setdefault(month, {"month": month})
                bucket["period_label"] = period_val or bucket.get("period_label") or ""
                sources = bucket.get("source") or ""
                if fname not in sources:
                    bucket["source"] = (sources + ";" + fname).strip(";")
                for field in fields:
                    if field.casefold() in {"period", "date"}:
                        continue
                    val = raw.get(field)
                    if val not in (None, ""):
                        bucket[field] = str(val).replace(",", "")
    # Nov 1-12 from daily files if monthly Nov is thin
    daily_cust = folder / "average_spend_daily_all_stores_2026-11-01_to_2026-11-12.csv"
    # Don't invent a Nov monthly total from daily unless we clearly have monthly already.
    # Reelo folder also has customers monthly Aug-Nov 13 - use that for Nov incomplete.
    late = folder / "customers_monthly_all_stores_2026-08-01_to_2026-11-13.csv"
    if late.is_file():
        with late.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames or []
            for raw in reader:
                month = _reelo_month_from_period(raw.get("period") or raw.get("date") or "")
                if month != "2026-11":
                    continue
                bucket = rows_by_month.setdefault(month, {"month": month})
                bucket["period_label"] = raw.get("period") or raw.get("date") or "1–12 Nov 2026"
                bucket["complete"] = "no"
                bucket["note"] = "November is 1–12 Nov (or through 13), not a full month."
                bucket["source"] = late.name
                for field in fields:
                    if field in {"period", "date"}:
                        continue
                    val = raw.get(field)
                    if val not in (None, ""):
                        bucket[field] = str(val).replace(",", "")
    # Collect union of keys
    keys = ["month", "period_label"]
    extra = []
    for bucket in rows_by_month.values():
        for key in bucket:
            if key not in keys and key not in extra:
                extra.append(key)
    for bucket in rows_by_month.values():
        bucket.setdefault("complete", "yes" if bucket["month"] <= "2026-10" else "no")
        bucket.setdefault("note", "" if bucket["month"] <= "2026-10" else "November is incomplete.")
    fields = keys + extra
    if "complete" not in fields:
        fields.append("complete")
    if "note" not in fields:
        fields.append("note")
    write_rows(_HISTORY / "reelo_month.csv", fields, [rows_by_month[m] for m in sorted(rows_by_month)])


def _month_from_cell(value):
    day = _day(value)
    if day:
        return _month_key(day)
    text = str(value or "")
    m = re.search(r"(20\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return ""


def build_aggregator():
    dest_dir = _ROOT / "data" / "aggregators"
    dest_dir.mkdir(parents=True, exist_ok=True)
    if _BOX_AGG.is_file():
        target = dest_dir / _BOX_AGG.name
        if not target.is_file():
            shutil.copy2(_BOX_AGG, target)
        src = target
    else:
        src = next(dest_dir.glob("*.xlsx"), None)
    if src is None:
        print("  Sanjoy aggregator workbook not found; skipping")
        return
    from openpyxl import load_workbook
    wb = load_workbook(src, data_only=True)
    z_headers = None
    s_headers = None
    z_rows = []
    s_rows = []
    ws = wb["Zomato Actuals"]
    for i, raw in enumerate(ws.iter_rows(values_only=True), 1):
        if i == 3:
            z_headers = [str(c).strip() if c else f"col_{j}" for j, c in enumerate(raw)]
            continue
        if i < 4 or not raw or not raw[0]:
            continue
        z_rows.append(dict(zip(z_headers, raw)))
    ws = wb["Swiggy Inputs"]
    for i, raw in enumerate(ws.iter_rows(values_only=True), 1):
        if i == 3:
            s_headers = [str(c).strip() if c else f"col_{j}" for j, c in enumerate(raw)]
            continue
        if i < 4 or not raw or not raw[0]:
            continue
        s_rows.append(dict(zip(s_headers, raw)))
    wb.close()

    def flatten(platform, raw):
        key = str(raw.get("Outlet key") or "").strip()
        mapped, status, note = _AGG_MAP.get(key, ((raw.get("Outlet") or "").strip(), "unmapped", "not in the mapping table"))
        month = _month_from_cell(raw.get("Month"))
        if status == "excluded" or month < "2026-04":
            return None
        def cell(*names):
            for name in names:
                if name in raw and raw[name] not in (None, ""):
                    return raw[name]
            return ""
        return {
            "month": month,
            "platform": platform,
            "outlet_key": key,
            "region": raw.get("Region") or "",
            "workbook_name": raw.get("Outlet") or "",
            "store": mapped,
            "match_status": status,
            "match_note": note,
            "res_id": cell("Zomato Res ID", "Swiggy Res ID"),
            "net_sales": _num(cell("Net sales")) if cell("Net sales") != "" else "",
            "bill_subtotal": _num(cell("Bill subtotal")) if cell("Bill subtotal") != "" else "",
            "orders": _num(cell("Orders")) if cell("Orders") != "" else "",
            "impressions": _num(cell("Impressions")) if cell("Impressions") != "" else "",
            "menu_opens": _num(cell("Menu opens")) if cell("Menu opens") != "" else "",
            "cart_builds": _num(cell("Cart builds")) if cell("Cart builds") != "" else "",
            "orders_placed": _num(cell("Orders placed")) if cell("Orders placed") != "" else "",
            "online_time_pct": _num(cell("Online time %")) if cell("Online time %") != "" else "",
            "offline_hours": _num(cell("Offline hours")) if cell("Offline hours") != "" else "",
            "ad_spend": _num(cell("Ad spend")) if cell("Ad spend") != "" else "",
            "ad_sales": _num(cell("Ad sales")) if cell("Ad sales") != "" else "",
            "merchant_refunds": _num(cell("Merchant refunds")) if cell("Merchant refunds") != "" else "",
            "swiggy_gmv": _num(cell("Swiggy GMV")) if cell("Swiggy GMV") != "" else "",
            "note": (
                "Zomato actuals are complete for these columns. "
                if platform == "Zomato"
                else "Swiggy impressions, ads and refunds are blank in the workbook (still pending). "
            ) + ("" if status == "mapped" else note),
        }

    out = []
    for raw in z_rows:
        row = flatten("Zomato", raw)
        if row:
            out.append(row)
    for raw in s_rows:
        row = flatten("Swiggy", raw)
        if row:
            out.append(row)
    # blank cells should stay blank, not 0
    for row in out:
        for key, val in list(row.items()):
            if val == "":
                row[key] = ""
            elif isinstance(val, float):
                row[key] = f"{val}"
    fields = [
        "month", "platform", "outlet_key", "region", "workbook_name", "store",
        "match_status", "match_note", "res_id", "net_sales", "bill_subtotal",
        "orders", "impressions", "menu_opens", "cart_builds", "orders_placed",
        "online_time_pct", "offline_hours", "ad_spend", "ad_sales",
        "merchant_refunds", "swiggy_gmv", "note",
    ]
    write_rows(_HISTORY / "aggregator_store_month.csv", fields, out)
    # mapping file for transparency
    map_rows = []
    for key, (store, status, note) in _AGG_MAP.items():
        z = next((r for r in z_rows if str(r.get("Outlet key")) == key), {})
        s = next((r for r in s_rows if str(s.get("Outlet key")) == key), {}) if False else next((r for r in s_rows if str(r.get("Outlet key")) == key), {})
        map_rows.append({
            "outlet_key": key,
            "region": z.get("Region") or s.get("Region") or "",
            "zomato_name": z.get("Outlet") or "",
            "swiggy_name": s.get("Outlet") or "",
            "store": store,
            "match_status": status,
            "match_note": note,
        })
    write_rows(
        _HISTORY / "aggregator_outlet_map.csv",
        ["outlet_key", "region", "zomato_name", "swiggy_name", "store", "match_status", "match_note"],
        map_rows,
    )


def build_finance():
    src = _ROOT / "data" / "finance" / "grand_economics" / "grand_economics_tidy.csv"
    rows = []
    if not src.is_file():
        print("  finance tidy not found")
        return
    with src.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            month = raw.get("month") or ""
            if month < "2026-04" or month > "2026-09":
                continue
            if (raw.get("level") or "") != "city":
                continue
            if (raw.get("store") or "").strip():
                continue
            rows.append({
                "month": month,
                "city": raw.get("city") or "",
                "line": raw.get("line") or "",
                "value": raw.get("value") or "",
                "fy": raw.get("fy") or "",
                "level": "city",
                "note": "From grand_economics_tidy.csv, city level. October 2026 is not in the file.",
            })
    write_rows(
        _HISTORY / "finance_city_month.csv",
        ["month", "city", "line", "value", "fy", "level", "note"],
        rows,
    )


def build_hr():
    src = _ROOT / "data" / "hr" / "2026-11-12" / "monthly_joiners_exits_by_location.csv"
    rows = []
    if src.is_file():
        with src.open(newline="", encoding="utf-8-sig") as handle:
            fields = None
            for raw in csv.DictReader(handle):
                if fields is None:
                    fields = list(raw.keys())
                month = raw.get("month") or ""
                if month < "2026-04":
                    continue
                # Drop any column that looks like a person name (none expected).
                clean = {k: v for k, v in raw.items() if k and "name" not in k.casefold() and "email" not in k.casefold()}
                clean["complete"] = "no" if month == "2026-11" else "yes"
                clean["note"] = (
                    "November covers 1–12 Nov only. Counts of 0 are real counts. No names."
                    if month == "2026-11"
                    else "Counts only. No names."
                )
                rows.append(clean)
    fields = ["month", "location", "joiners", "exits", "exits_absconded", "exits_resigned",
              "exits_company_action", "complete", "note"]
    # include any extra count columns except name-like
    extra = []
    for row in rows:
        for key in row:
            if key not in fields and key not in extra:
                extra.append(key)
    write_rows(_HISTORY / "hr_month.csv", fields + extra, rows)


def build_famepilot():
    src = _ROOT / "data" / "famepilot" / "tickets.csv"
    # also try other locations
    if not src.is_file():
        for cand in (_ROOT / "data").rglob("tickets.csv"):
            if "famepilot" in str(cand).casefold():
                src = cand
                break
    acc = defaultdict(lambda: {"tickets": 0, "stale": 0})
    if not src.is_file():
        print("  famepilot tickets not found")
        write_rows(_HISTORY / "famepilot_tickets_month.csv",
                   ["month", "store", "platform", "tickets", "stale", "complete", "note"], [])
        return
    with src.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            # Do not copy customer or any name column.
            day = _day(raw.get("date_time") or raw.get("date") or raw.get("created_at"))
            if day is None or day < WINDOW_START:
                continue
            store = (raw.get("store") or "").strip()
            platform = (raw.get("platform") or "").strip()
            key = (_month_key(day), store, platform)
            acc[key]["tickets"] += 1
            keyword = (raw.get("keyword") or "").strip().casefold()
            if keyword == "stale":
                acc[key]["stale"] += 1
    rows = []
    for (month, store, platform), bucket in sorted(acc.items()):
        rows.append({
            "month": month,
            "store": store,
            "platform": platform,
            "tickets": bucket["tickets"],
            "stale": bucket["stale"],
            "complete": "no" if month == "2026-10" else ("yes" if month == "2026-09" else "no"),
            "note": (
                "Counts only; customer names are not stored. "
                + ("October tickets run through 9 Oct only." if month == "2026-10"
                   else ("Tickets on file start 1 Sep." if month == "2026-09" else ""))
            ),
        })
    write_rows(
        _HISTORY / "famepilot_tickets_month.csv",
        ["month", "store", "platform", "tickets", "stale", "complete", "note"],
        rows,
    )


def _months_between(start, end):
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return months


def _loaded_months(path, column="month"):
    if not Path(path).is_file():
        return []
    found = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            month = raw.get(column) or ""
            if month and month not in found:
                found.append(month)
    return sorted(found)


def build_coverage():
    window = _months_between(WINDOW_START, WINDOW_END)
    domains = []

    def add(domain_id, label, owner, how, loaded, notes, roles, start="", end="", extra_missing=None):
        loaded = [m for m in loaded if m >= "2026-04"]
        missing = [m for m in window if m not in loaded]
        if extra_missing:
            for m in extra_missing:
                if m not in missing and m in window:
                    missing.append(m)
                if m in loaded:
                    # still "loaded" but incomplete; leave in loaded
                    pass
        domains.append({
            "id": domain_id,
            "label": label,
            "owner": owner,
            "owner_how": how,
            "from": start or (loaded[0] if loaded else ""),
            "to": end or (loaded[-1] if loaded else ""),
            "months_loaded": loaded,
            "months_missing": sorted(missing),
            "notes": notes,
            "roles": roles,
        })

    all_roles = ["owner", "ops", "finance", "hr"]
    sales_loaded = _loaded_months(_HISTORY / "sales_city_month.csv")
    add("sales", "Sales by city and store", "Alfred",
        "who pulls Posist Insights daily sales",
        sales_loaded,
        "Daily store sales start 4 Sep 2026. October is a full calendar month. November is through 12 Nov. Chattarpur and GK1 Cloud Kitchen are out of the sales base; Faridabad is out from 23 Oct. Manisquare and Forum sales are counted; bills and APB stay out of comparisons.",
        all_roles, start="2026-09-04", end="2026-11-12")
    ch_loaded = _loaded_months(_HISTORY / "channel_store_month.csv")
    add("channel", "Sales by channel (Swiggy, Zomato, and others)", "Alfred",
        "who pulls Posist Insights channel sales",
        ch_loaded,
        "Store-level channel files cover 2–15 Oct and 1–12 Nov 2026, except 1 Oct and 9 Nov, which are not on disk and are left out (not treated as zero). 16–31 Oct are network-wide totals only (ALL (network) / ALL DEPLOYMENTS), not store-level. A 9 Sep–8 Oct 30-day range file is in data/posist; it is not a calendar month. Calendar September is not loaded.",
        all_roles, start="2026-10-02", end="2026-11-12")
    add("procurement", "Procurement purchases and ingredient prices", "Logan",
        "who pulls the procurement (PurchaseEasy) reports",
        sorted(set(_loaded_months(_HISTORY / "purchases_item_month.csv") + _loaded_months(_HISTORY / "prices_item_month.csv"))),
        "Purchases and item prices run from 1 Apr 2026. April–August are calendar-month Entry Reports and Purchase Summaries (days with no GRN are days with no invoice, left out not treated as zero). September purchases combine the 1–8 Sep backfill with GRN lines for 9–30 Sep; Delhi has no 1 Sep or 6 Sep entry in the 1–8 pack. October purchases are GRN 1–8 Oct only. Item prices: Apr–Aug from the official Purchase Summary; Sep is a qty-weighted average of 1–8 Sep entries plus 9–30 Sep GRN; October is complete and November is 1–12, from procurement_summary.json. Freight and other invoice charges are kept separate from item totals. The Purchase Summary .xls files are HTML.",
        all_roles,
        start="2026-04-01", end="2026-11-12")
    # prices add Nov
    # already noted
    add("menu_mix", "Menu mix by month", "Jarvis",
        "who pulls the Posist menu-mix extracts",
        _loaded_months(_HISTORY / "menu_item_month.csv"),
        "Calendar September and October are loaded. A 14 Oct–12 Nov Friday file is also in data/menu; it is a 30-day window, not a calendar month. November calendar month is not complete. April–August are not loaded.",
        all_roles, start="2026-09-01", end="2026-10-31")
    add("reelo", "Reelo monthly customers, orders and spend", "Jarvis",
        "who pulls the Reelo dashboard exports",
        _loaded_months(_HISTORY / "reelo_month.csv"),
        "Monthly customers, orders and average spend for April–October 2026. November is 1–12 only. Campaign metrics are mostly blank.",
        all_roles)
    add("aggregator", "Swiggy and Zomato aggregator performance", "Sanjoy",
        "who maintains the brand aggregator workbook",
        _loaded_months(_HISTORY / "aggregator_store_month.csv"),
        "August–October 2026 from Sanjoy's 13 Nov workbook, 26 outlets. Faridabad Sector 15 (DC-09) is left out. Outlet names are mapped only where the store master or the same DC key is clear; unmapped names stay as in the workbook. Zomato actuals are complete. Swiggy impressions, ads and refunds are blank (still pending).",
        all_roles, start="2026-08-01", end="2026-10-31")
    add("finance", "Grand Economics (P&L)", "Shilajit",
        "who sends the Grand Economics workbook",
        _loaded_months(_HISTORY / "finance_city_month.csv"),
        "April–September 2026, both cities, city-level lines from grand_economics_tidy.csv. October and November 2026 are not in the file. Owner and finance only.",
        ["owner", "finance"], start="2026-04-01", end="2026-09-30")
    add("tally", "Tally day book", "the Accountant",
        "who sends the daily Tally Day Book packs (via Shilajit)",
        _loaded_months(_HISTORY / "tally_company_month.csv"),
        "Vouchers from 30 Sep through 11 Nov 2026, with gaps. 16–27 Oct and 6, 8, 9, 11 Nov were parsed from raw packs on the box for this PR. 7 and 10 Nov are not in the pack. April–29 Sep are not loaded. Missing days are left out, not filled with zero. Owner and finance only.",
        ["owner", "finance"], start="2026-09-30", end="2026-11-11")
    add("hr", "HR monthly joiners and exits (counts only)", "the HR Bot",
        "who pulls the Keka aggregates",
        _loaded_months(_HISTORY / "hr_month.csv"),
        "April–November 2026 location-level joiner and exit counts. November is 1–12 only. No employee names. Owner only.",
        ["owner"], start="2026-04-01", end="2026-11-12")
    add("famepilot", "Famepilot ticket counts", "Albus",
        "who pulls the Famepilot ticket export",
        _loaded_months(_HISTORY / "famepilot_tickets_month.csv"),
        "Ticket counts by store and platform, 1 Sep–9 Oct 2026. Customer names are not stored. April–August and 10 Oct onward are not loaded.",
        all_roles, start="2026-09-01", end="2026-10-09")

    payload = {
        "window_start": WINDOW_START.isoformat(),
        "window_end": WINDOW_END.isoformat(),
        "as_of": "2026-11-13",
        "domains": domains,
        "rule": "When a month is not loaded, say the data is not loaded yet and name who it would come from. Never estimate.",
    }
    path = _HISTORY / "coverage.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {path.relative_to(_ROOT)}")
    return payload


def main():
    # App imports (month_sales) need the repo on sys.path
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    _HISTORY.mkdir(parents=True, exist_ok=True)
    (_HISTORY / "extra").mkdir(parents=True, exist_ok=True)
    print("Copying source files")
    copy_channel_files()
    copy_procurement_backfill()
    menu_folder = copy_oct_menu()
    print("Building October menu CSV")
    build_oct_menu_csv(menu_folder)
    print("Parsing Tally packs")
    vouchers = parse_tally()
    print("Building monthly aggregates")
    build_tally_month(vouchers)
    build_sales()
    build_channel()
    build_procurement()
    build_menu_month()
    build_reelo()
    build_aggregator()
    build_finance()
    build_hr()
    build_famepilot()
    print("Writing coverage")
    build_coverage()
    print("done")


if __name__ == "__main__":
    main()
