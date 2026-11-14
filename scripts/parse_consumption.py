"""Parse PurchaseEasy Consumption Report HTML .xls files into monthly aggregates.

Source files live under /workspace/backfill/procurement/consumption/ and are
not copied into the repo (they are ~5 MB each). Store and item aggregates
are written to data/history/. Chattarpur and GK1 Cloud Kitchen are excluded.
"""

from __future__ import annotations

import csv
import json
import re
from calendar import monthrange
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from html.parser import HTMLParser
from pathlib import Path

_CLOSED = ("chattarpur", "gk1", "gk 1")
_BACKFILL = Path("/workspace/backfill/procurement/consumption")

# Column index in a 38-cell item row.
_COL = {
    "deployment": 0,
    "item_code": 1,
    "item": 2,
    "category": 3,
    "unit": 4,
    "super_category": 5,
    "avg_price": 6,
    "opening_date": 7,
    "opening_qty": 8,
    "opening_amt": 9,
    "purchase_qty": 10,
    "purchase_amt": 11,
    "stock_in_qty": 12,
    "stock_in_amt": 13,
    "consumption_qty": 14,
    "consumption_amt": 15,
    "stock_out_qty": 16,
    "stock_out_amt": 17,
    "wastage_qty": 20,
    "wastage_amt": 21,
    "wastage_pct": 22,
    "closing_date": 27,
    "closing_qty": 28,
    "closing_amt": 29,
}


class _HtmlTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._table = []
            self.tables.append(self._table)
        elif tag == "tr" and self._table is not None:
            self._row = []
            self._table.append(self._row)
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            self._in_cell = True
            self._row.append(self._cell)

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._in_cell = False
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._table = None

    def handle_data(self, data):
        if self._in_cell:
            self._cell.append(data)


def _closed(name):
    text = (name or "").casefold()
    return any(token in text for token in _CLOSED)


def _money(text):
    raw = (text or "").replace("\xa0", " ").replace(",", "").replace("₹", "").strip()
    raw = re.sub(r"\{\{.*?\}\}", "", raw).strip()
    if raw in ("", "N.A.", "NA", "N.A", "-", "0 -->"):
        return None
    try:
        return Decimal(raw)
    except Exception:
        return None


def _bucket(super_category):
    """raw = Food + Beverage; semi = Semi Process; packaging; other = the rest."""
    text = (super_category or "").casefold().strip()
    if text in {"food", "beverage"}:
        return "raw"
    if text in {"semi process", "semi-process", "semiprocess"}:
        return "semi"
    if text == "packaging":
        return "packaging"
    return "other"


def _month_from_name(name):
    """2026-04 or 2026-09-01to08 from the consumption filename."""
    match = re.search(r"(20\d{2}-\d{2})(?:-(\d{2})to(\d{2}))?", name)
    if not match:
        return "", "", ""
    month = match.group(1)
    if match.group(2) and match.group(3):
        return month, f"{month}-{match.group(2)}", f"{month}-{match.group(3)}"
    last = monthrange(int(month[:4]), int(month[5:7]))[1]
    return month, f"{month}-01", f"{month}-{last:02d}"


def _city_from_file(filename, deployment):
    if "east" in filename.casefold():
        return "East", "Kolkata"
    if "north" in filename.casefold():
        return "North", "NCR"
    return "", ""


def _fmt_amt(value):
    if value is None:
        return ""
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def _fmt_qty(value):
    if value is None:
        return ""
    text = f"{value.normalize()}" if value == value.to_integral() else f"{value}"
    return text


def parse_file(path):
    """Return (item dicts, footer consumption amt or None, issues)."""
    parser = _HtmlTable()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    issues = []
    items = []
    footer = None
    for table in parser.tables:
        for raw in table:
            row = ["".join(cell).replace("\xa0", " ").strip() for cell in raw]
            if not row:
                continue
            head = row[0]
            if head.startswith("Amount"):
                footer = row
                continue
            if head in {"Item", "Deployment Name"}:
                continue
            if len(row) < 16:
                continue
            if len(row) != 38:
                issues.append(f"{path.name}: item row has {len(row)} columns (expected 38), store={head[:60]}")
            def cell(index):
                return row[index] if index < len(row) else ""
            items.append({
                "deployment": cell(0),
                "item_code": cell(1),
                "item": cell(2),
                "category": cell(3),
                "unit": cell(4),
                "super_category": cell(5),
                "avg_price": _money(cell(6)),
                "opening_date": cell(7),
                "opening_qty": _money(cell(8)),
                "opening_amt": _money(cell(9)),
                "purchase_qty": _money(cell(10)),
                "purchase_amt": _money(cell(11)),
                "stock_in_qty": _money(cell(12)),
                "stock_in_amt": _money(cell(13)),
                "consumption_qty": _money(cell(14)),
                "consumption_amt": _money(cell(15)),
                "stock_out_qty": _money(cell(16)),
                "stock_out_amt": _money(cell(17)),
                "wastage_qty": _money(cell(20)),
                "wastage_amt": _money(cell(21)),
                "wastage_pct": _money(cell(22)),
                "closing_date": cell(27),
                "closing_qty": _money(cell(28)),
                "closing_amt": _money(cell(29)),
            })
    footer_cons = None
    if footer and len(footer) >= 9:
        footer_cons = _money(footer[8])
    return items, footer_cons, issues


def _has_movement(item):
    """True when the item moved this period (not a zero catalogue row)."""
    for key in (
        "opening_qty", "opening_amt", "purchase_qty", "purchase_amt",
        "stock_in_qty", "stock_in_amt", "consumption_qty", "consumption_amt",
        "stock_out_qty", "stock_out_amt", "wastage_qty", "wastage_amt",
    ):
        value = item.get(key)
        if value is not None and value != 0:
            return True
    return False


def build(history_dir, src=None, root=None):
    """Write consumption_store_month.csv, consumption_item_month.csv and notes."""
    src = Path(src) if src else _BACKFILL
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    if not src.is_dir():
        print("  no consumption backfill folder")
        return {"stores": 0, "items": 0, "excluded": 0, "issues": []}

    files = sorted(src.glob("consumption_*.xls"))
    issues = []
    footer_gaps = []
    excluded = []
    store_rows = []
    item_rows = []
    seen = {}

    for path in files:
        month, first, last = _month_from_name(path.name)
        if not month:
            issues.append(f"{path.name}: could not read a month from the filename")
            continue
        items, footer_cons, file_issues = parse_file(path)
        issues.extend(file_issues)
        if not items:
            issues.append(f"{path.name}: no item rows")
            continue
        deployments = {item["deployment"] for item in items}
        if len(deployments) != 1:
            issues.append(f"{path.name}: more than one deployment {sorted(deployments)}")
        store = items[0]["deployment"]
        region, city = _city_from_file(path.name, store)
        year, mon = int(month[:4]), int(month[5:7])
        days_in = monthrange(year, mon)[1]
        complete = "yes" if first == f"{month}-01" and last == f"{month}-{days_in:02d}" else "no"
        note = "Calendar month from the PurchaseEasy Consumption Report."
        if complete == "no":
            note = (
                f"{first} to {last} from the PurchaseEasy Consumption Report, "
                "not a full calendar month."
            )

        totals = defaultdict(lambda: Decimal(0))
        for item in items:
            amt = item["consumption_amt"] or Decimal(0)
            bucket = _bucket(item["super_category"])
            totals["consumption_amt_all"] += amt
            if bucket == "raw":
                totals["consumption_amt_raw"] += amt
            elif bucket == "semi":
                totals["consumption_amt_semi"] += amt
            elif bucket == "packaging":
                totals["consumption_amt_packaging"] += amt
                totals["consumption_amt_other"] += amt
            else:
                totals["consumption_amt_other"] += amt
            totals["purchase_amt_all"] += item["purchase_amt"] or Decimal(0)
            totals["wastage_amt_all"] += item["wastage_amt"] or Decimal(0)
            totals["opening_amt_all"] += item["opening_amt"] or Decimal(0)
            totals["closing_amt_all"] += item["closing_amt"] or Decimal(0)

        if footer_cons is not None:
            gap = totals["consumption_amt_all"] - footer_cons
            if abs(gap) > Decimal("0.02"):
                footer_gaps.append({
                    "file": path.name,
                    "item_sum": str(totals["consumption_amt_all"]),
                    "footer": str(footer_cons),
                    "gap": str(gap),
                })

        if _closed(store):
            excluded.append({
                "file": path.name,
                "store": store,
                "month": month,
                "consumption_amt_all": str(totals["consumption_amt_all"]),
                "item_rows": len(items),
                "nonzero_movement_rows": sum(1 for item in items if _has_movement(item)),
                "reason": (
                    "Closed store, excluded. Chattarpur files are a zero-value item catalogue. "
                    "GK1 Cloud Kitchen files have leftover opening quantities with zero amounts "
                    "and zero consumption, identical across the six months."
                ),
            })
            continue

        key = (month, store)
        if key in seen:
            issues.append(f"duplicate store-month {key}: {seen[key]} and {path.name}")
        seen[key] = path.name

        food = totals["consumption_amt_raw"] + totals["consumption_amt_semi"]
        store_rows.append({
            "month": month,
            "store": store,
            "region": region,
            "city": city,
            "first_day": first,
            "last_day": last,
            "days_in_month": days_in,
            "complete": complete,
            "item_rows": len(items),
            "item_rows_nonzero": sum(1 for item in items if _has_movement(item)),
            "consumption_amt_raw": _fmt_amt(totals["consumption_amt_raw"]),
            "consumption_amt_semi": _fmt_amt(totals["consumption_amt_semi"]),
            "consumption_amt_food": _fmt_amt(food),
            "consumption_amt_packaging": _fmt_amt(totals["consumption_amt_packaging"]),
            "consumption_amt_other": _fmt_amt(totals["consumption_amt_other"]),
            "consumption_amt_all": _fmt_amt(totals["consumption_amt_all"]),
            "purchase_amt_all": _fmt_amt(totals["purchase_amt_all"]),
            "wastage_amt_all": _fmt_amt(totals["wastage_amt_all"]),
            "opening_amt_all": _fmt_amt(totals["opening_amt_all"]),
            "closing_amt_all": _fmt_amt(totals["closing_amt_all"]),
            "source": path.name,
            "note": note,
        })

        for item in items:
            if not _has_movement(item):
                continue
            item_rows.append({
                "month": month,
                "store": store,
                "region": region,
                "city": city,
                "item_code": item["item_code"],
                "item": item["item"],
                "category": item["category"],
                "super_category": item["super_category"],
                "bucket": _bucket(item["super_category"]),
                "unit": item["unit"],
                "avg_price": _fmt_amt(item["avg_price"]),
                "opening_qty": _fmt_qty(item["opening_qty"]),
                "opening_amt": _fmt_amt(item["opening_amt"]),
                "purchase_qty": _fmt_qty(item["purchase_qty"]),
                "purchase_amt": _fmt_amt(item["purchase_amt"]),
                "stock_in_qty": _fmt_qty(item["stock_in_qty"]),
                "stock_in_amt": _fmt_amt(item["stock_in_amt"]),
                "consumption_qty": _fmt_qty(item["consumption_qty"]),
                "consumption_amt": _fmt_amt(item["consumption_amt"]),
                "stock_out_qty": _fmt_qty(item["stock_out_qty"]),
                "stock_out_amt": _fmt_amt(item["stock_out_amt"]),
                "wastage_qty": _fmt_qty(item["wastage_qty"]),
                "wastage_amt": _fmt_amt(item["wastage_amt"]),
                "wastage_pct": _fmt_qty(item["wastage_pct"]),
                "closing_qty": _fmt_qty(item["closing_qty"]),
                "closing_amt": _fmt_amt(item["closing_amt"]),
                "first_day": first,
                "last_day": last,
                "complete": complete,
                "source": path.name,
            })

    def write(path, fields, rows):
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    store_fields = [
        "month", "store", "region", "city", "first_day", "last_day",
        "days_in_month", "complete", "item_rows", "item_rows_nonzero",
        "consumption_amt_raw", "consumption_amt_semi", "consumption_amt_food",
        "consumption_amt_packaging", "consumption_amt_other", "consumption_amt_all",
        "purchase_amt_all", "wastage_amt_all", "opening_amt_all", "closing_amt_all",
        "source", "note",
    ]
    item_fields = [
        "month", "store", "region", "city", "item_code", "item", "category",
        "super_category", "bucket", "unit", "avg_price",
        "opening_qty", "opening_amt", "purchase_qty", "purchase_amt",
        "stock_in_qty", "stock_in_amt", "consumption_qty", "consumption_amt",
        "stock_out_qty", "stock_out_amt", "wastage_qty", "wastage_amt", "wastage_pct",
        "closing_qty", "closing_amt", "first_day", "last_day", "complete", "source",
    ]
    write(
        history_dir / "consumption_store_month.csv",
        store_fields,
        sorted(store_rows, key=lambda r: (r["month"], r["city"], r["store"])),
    )
    write(
        history_dir / "consumption_item_month.csv",
        item_fields,
        sorted(item_rows, key=lambda r: (r["month"], r["city"], r["store"], r["item"])),
    )

    notes = {
        "files_seen": len(files),
        "store_months_loaded": len(store_rows),
        "item_rows_nonzero": len(item_rows),
        "excluded": excluded,
        "footer_gaps": footer_gaps,
        "issues": issues,
        "known_gaps": [
            "North FRA (02/0017) has no file for any period in this drop.",
            "Sec 31 Gurgaon (02/0016) has no April file (May–8 Sep are present).",
            "Events & Catering has no consumption file.",
            "consumption_north_ConnaughtPlace_MainKitchen_2026-04.xls is Connaught place (02/0012); later months use Connaughtplace020012. The Deployment Name inside the file is used.",
            "consumption_east_SaltLake002_*.xls is Salt Lake (002); the Deployment Name inside the file is used.",
            "Chattarpur and GK1 Cloud Kitchen files are all the same size within each store and were excluded (closed stores). Chattarpur is a zero-value catalogue; GK1 has leftover opening quantities, zero amounts and zero consumption, identical across months.",
        ],
        "classification": (
            "Raw is the Food and Beverage super-categories. Semi is Semi Process. "
            "Packaging is tracked on its own and also included in other. "
            "Cleaning, Uniform, Non Food, Fruit and Bakery sit in other. "
            "Food cost is (raw + semi) / Posist gross. Packaging is shown separately."
        ),
        "item_sums_used": (
            "Store totals are the sum of item rows. Footer 'Amount -' consumption "
            "amounts can differ by a few paisa of rounding; those gaps are listed "
            "and the item sum is kept."
        ),
    }
    (history_dir / "consumption_parse_notes.json").write_text(
        json.dumps(notes, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"  consumption store-months: {len(store_rows)}, "
        f"item rows: {len(item_rows)}, excluded: {len(excluded)}, "
        f"footer gaps: {len(footer_gaps)}, issues: {len(issues)}"
    )
    return {
        "stores": len(store_rows),
        "items": len(item_rows),
        "excluded": len(excluded),
        "issues": issues,
        "footer_gaps": footer_gaps,
    }


if __name__ == "__main__":
    import sys
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/dra/data/history")
    build(dest)
