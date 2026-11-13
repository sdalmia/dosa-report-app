"""Parse Procurement backfill drops for April–early September 2026.

Entry Report .xlsx files are a warehouse / vendor / invoice / item tree.
Item lines (numeric item code + name, qty, rate, totals) are taken as
purchases. Rows after "Charges Bifurcation" (Freight, Transport, TCS) are
invoice charges, not items, and are stored separately. Category, vendor-total
and store-total rows are skipped.

Purchase Summary Item Wise .xls files are HTML. They give the official
monthly quantity, unit price and subtotal by item, used for prices.

Nothing is estimated. A day with no GRN is left out, not treated as zero.
"""

from __future__ import annotations

import re
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from openpyxl import load_workbook

_SKIP = {
    "item code", "super category bifurcation", "charges bifurcation",
    "vendor total", "store total", "grand total", "food", "packaging",
    "cleaning", "beverage", "non food", "invoice date", "total",
    "nonfood", "non-food",
}
_CHARGE_LABELS = {"freight", "transport charges", "tcs charge", "transport"}
_DATE = re.compile(r"(\d{1,2})-(\d{1,2})-(20\d{2})")


def _num(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).replace(",", "").replace("₹", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _day(text):
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    match = _DATE.search(str(text or ""))
    if not match:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _city_from_name(name, warehouse=""):
    blob = f"{name} {warehouse}".casefold()
    if "kolkata" in blob or "kolkata" in blob.replace(" ", ""):
        return "Kolkata"
    if "delhi" in blob:
        return "Delhi"
    return ""


def parse_entry_report(path, city="", warehouse=""):
    """Return (item_lines, charge_lines, store_total, issues)."""
    path = Path(path)
    city = city or _city_from_name(path.name)
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    vendor = ""
    inv_date = None
    se = ""
    items = []
    charges = []
    store_total = None
    issues = []
    in_charges = False
    for index, raw in enumerate(ws.iter_rows(values_only=True), 1):
        cells = list(raw) + [None] * 12
        first, second, third = cells[0], cells[1], cells[2]
        if index == 1:
            continue
        if isinstance(first, (int, float)) and not isinstance(first, bool) and second:
            in_charges = False
            items.append({
                "city": city,
                "warehouse": warehouse,
                "vendor": vendor,
                "date": inv_date,
                "se_number": se,
                "item_code": first,
                "item": str(second).strip(),
                "qty": _num(cells[3]),
                "unit": (cells[4] or "").strip() if isinstance(cells[4], str) else (cells[4] or ""),
                "unit_price": _num(cells[5]),
                "sub_total": _num(cells[6]),
                "tax": _num(cells[7]),
                "total": _num(cells[8]),
                "source": path.name,
            })
            continue
        text = str(first or "").strip()
        if not text:
            continue
        folded = text.casefold()
        if "warehouse" in folded:
            warehouse = text
            city = city or _city_from_name(path.name, warehouse)
            in_charges = False
            continue
        if text.startswith("SE-") or "Invoice N" in text:
            se = text
            in_charges = False
            continue
        if folded == "invoice date":
            inv_date = _day(third)
            in_charges = False
            continue
        if folded == "charges bifurcation":
            in_charges = True
            continue
        if folded == "store total":
            store_total = _num(cells[8])
            continue
        if folded in _SKIP or "bifurcation" in folded:
            in_charges = False
            continue
        if in_charges:
            total = _num(cells[8])
            if total is not None:
                charges.append({
                    "city": city,
                    "warehouse": warehouse,
                    "vendor": vendor,
                    "date": inv_date,
                    "se_number": se,
                    "charge": text,
                    "total": total,
                    "source": path.name,
                })
            continue
        # Vendor heading: name only, no item in column B.
        vendor = text
        in_charges = False
    wb.close()
    for row in items:
        if row["date"] is None:
            issues.append(f"{path.name}: item {row['item']} has no invoice date")
        if not row["vendor"]:
            issues.append(f"{path.name}: item {row['item']} has no vendor")
    item_sum = sum(row["total"] or 0 for row in items)
    return items, charges, store_total, issues, item_sum


class _HtmlTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []
            self.in_cell = True

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.row is not None and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
            self.in_cell = False
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)


def parse_purchase_summary(path, city=""):
    """Official monthly item-wise qty, unit price and subtotal from the HTML .xls."""
    path = Path(path)
    city = city or _city_from_name(path.name)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    if "<table" not in text.casefold() and "PURCHASE SUMMARY" not in text:
        return [], [f"{path.name}: not an HTML purchase summary"], None
    parser = _HtmlTable()
    parser.feed(text)
    items = []
    issues = []
    footer_grand = None
    footer_charge = None
    for raw in parser.rows:
        if not raw:
            continue
        first = (raw[0] or "").strip()
        if first.startswith("Total Charge") or (len(raw) <= 10 and "Total" in first):
            # Footer: last cell is grand total including charges.
            charge_match = re.search(r"Total Charge\s*:\s*([\d,]+(?:\.\d+)?)", first)
            if charge_match:
                footer_charge = _num(charge_match.group(1))
            if raw[-1]:
                footer_grand = _num(raw[-1])
            continue
        if not first or not first[0].isdigit():
            continue
        if len(raw) < 11:
            issues.append(f"{path.name}: short item row {raw[:4]}")
            continue
        # Data rows have 18 cells: Item Code .. Sub Total, Discount, CGST, SGST, IGST, Non GST, Total, Grand.
        items.append({
            "city": city,
            "item_code": first,
            "item": raw[1],
            "qty": _num(raw[7]),
            "unit": raw[8],
            "unit_price": _num(raw[9]),
            "sub_total": _num(raw[10]),
            "discount": _num(raw[11]) if len(raw) > 11 else None,
            "total": _num(raw[-2]) if len(raw) >= 18 else (_num(raw[-1]) if raw else None),
            "source": path.name,
        })
    return items, issues, {"grand_total": footer_grand, "total_charge": footer_charge}


def discover(root):
    """Yield (folder_name, month_key, entry_paths, summary_paths)."""
    root = Path(root)
    if not root.is_dir():
        return
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        name = folder.name
        # 2026-04 or 2026-09-01to08
        match = re.match(r"(20\d{2})-(\d{2})", name)
        if not match:
            continue
        month = f"{match.group(1)}-{match.group(2)}"
        entries = sorted(folder.glob("entry_report_*.xlsx"))
        summaries = sorted(list(folder.glob("purchase_summary_*.xls")) + list(folder.glob("purchase_summary_*.xlsx")))
        yield folder, month, entries, summaries


def parse_tree(roots):
    """Parse every backfill folder. Returns items, charges, prices, issues."""
    all_items = []
    all_charges = []
    all_prices = []
    issues = []
    checks = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for folder, month, entries, summaries in discover(root):
            month_items = []
            for path in entries:
                city = _city_from_name(path.name)
                items, charges, store_total, local_issues, item_sum = parse_entry_report(path, city=city)
                for row in items:
                    row["month"] = month
                    row["folder"] = folder.name
                for row in charges:
                    row["month"] = month
                all_items.extend(items)
                all_charges.extend(charges)
                issues.extend(local_issues)
                month_items.extend(items)
                charge_sum = sum(
                    row["total"] for row in charges
                    if (row.get("charge") or "").casefold() in _CHARGE_LABELS or "freight" in (row.get("charge") or "").casefold() or "transport" in (row.get("charge") or "").casefold() or "tcs" in (row.get("charge") or "").casefold()
                )
                checks.append({
                    "file": path.name,
                    "month": month,
                    "city": city,
                    "item_lines": len(items),
                    "item_sum": round(item_sum, 2),
                    "store_total": store_total,
                    "charge_sum": round(charge_sum, 2),
                    "note": "Store Total includes charges; item_sum is item lines only and is the purchase figure used.",
                })
            for path in summaries:
                city = _city_from_name(path.name)
                prices, local_issues, footer = parse_purchase_summary(path, city=city)
                issues.extend(local_issues)
                for row in prices:
                    row["month"] = month
                    row["folder"] = folder.name
                    if folder.name.endswith("01to08") or "to" in folder.name:
                        row["complete"] = "no"
                        row["note"] = f"Purchase summary for {folder.name}, not a full calendar month."
                    else:
                        row["complete"] = "yes"
                        row["note"] = f"Official Purchase Summary Item Wise for {month}."
                all_prices.extend(prices)
                summary_sub = sum(row["sub_total"] or 0 for row in prices)
                entry_sub = sum(
                    (row.get("sub_total") or row.get("total") or 0)
                    for row in month_items
                    if row.get("city") == city
                )
                gap = abs(summary_sub - entry_sub)
                checks.append({
                    "file": path.name,
                    "month": month,
                    "city": city,
                    "summary_items": len(prices),
                    "summary_subtotal": round(summary_sub, 2),
                    "entry_subtotal": round(entry_sub, 2),
                    "gap": round(gap, 2),
                    "footer": footer,
                    "note": (
                        "Summary item subtotal matches the entry-report item subtotal (within rounding)."
                        if gap < 1
                        else f"Summary item subtotal and entry-report item subtotal differ by ₹{gap:,.2f}."
                    ),
                })
    return all_items, all_charges, all_prices, issues, checks


if __name__ == "__main__":
    import json
    import sys

    roots = [Path(arg) for arg in sys.argv[1:]] or [
        Path("/workspace/backfill/procurement"),
        Path(__file__).resolve().parents[1] / "data" / "procurement" / "backfill",
    ]
    items, charges, prices, issues, checks = parse_tree(roots)
    print("items", len(items), "charges", len(charges), "prices", len(prices), "issues", len(issues))
    for row in checks:
        print(row)
    for issue in issues[:20]:
        print("ISSUE", issue)
