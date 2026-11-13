"""Tally day book. Owner only. The newest dated folder is the source.

Missing days are left out. They are not filled with zero. Nothing after the
last date in the file is invented.
"""

import csv
import re
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_COMPANIES = ("kolkata", "delhi", "haryana", "up")
_TYPES = ("payment", "receipt", "journal", "purchase", "sales", "contra")


def newest_dir():
    base = _ROOT / "data" / "tally"
    if not base.is_dir():
        return None
    dated = [path for path in base.iterdir() if path.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)]
    return max(dated, key=lambda path: path.name) if dated else None


def _parse_day(value):
    text = str(value or "").strip()
    for fmt in ("%d-%b-%y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _num(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _inr(value):
    if value is None:
        return ""
    sign = "-" if value < 0 else ""
    return f"{sign}₹{abs(value):,.2f}"


def load_vouchers():
    folder = newest_dir()
    if folder is None:
        return []
    path = folder / "daybook_vouchers.csv"
    if not path.is_file():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            day = _parse_day(raw.get("date"))
            amount = _num(raw.get("amt"))
            rows.append({
                "company": (raw.get("company") or "").strip(),
                "date": day,
                "date_text": (raw.get("date") or "").strip(),
                "type": (raw.get("type") or "").strip(),
                "no": (raw.get("no") or "").strip(),
                "dr": (raw.get("dr") or "").strip(),
                "cr": (raw.get("cr") or "").strip(),
                "amt": amount,
                "source": (raw.get("source") or "").strip(),
            })
    return rows


def load_ledger_map():
    folder = newest_dir()
    if folder is None:
        return []
    path = folder / "pnl_sep2026_ledger_map.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def coverage(rows):
    """Days present per company. The last date in the file is the end of coverage."""
    by_company = {}
    last = None
    for row in rows:
        if row["date"] is None:
            continue
        by_company.setdefault(row["company"], set()).add(row["date"])
        if last is None or row["date"] > last:
            last = row["date"]
    return by_company, last


def coverage_line(rows):
    by_company, last = coverage(rows)
    if not by_company or last is None:
        return "Tally day book is not loaded."
    bits = [f"{name} {len(days)} days" for name, days in sorted(by_company.items())]
    return (
        "Coverage: "
        + ", ".join(bits)
        + f". Last date in the file is {last.strftime('%-d %b %Y')}. Nothing after that date. "
        "A day with no rows is missing, not zero."
    )


def _company(question):
    folded = (question or "").casefold()
    for name in _COMPANIES:
        if name in folded:
            return name
    return ""


def _asked_day(question):
    match = re.search(
        r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:\s+(\d{4}))?",
        (question or "").casefold(),
    )
    if not match:
        return None
    month = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}[match.group(2)[:3] if match.group(2) != "sept" else "sep"]
    if match.group(2).startswith("sept"):
        month = 9
    year = int(match.group(3) or 2026)
    try:
        return datetime(year, month, int(match.group(1))).date()
    except ValueError:
        return None


def _month(question):
    folded = (question or "").casefold()
    months = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
    for name, number in months.items():
        if name in folded:
            return number
    return None


def _kind(question):
    folded = (question or "").casefold()
    for name in _TYPES:
        if name in folded:
            return name
    if "paid" in folded or "pay " in folded or folded.startswith("pay") or "payments" in folded:
        return "payment"
    return ""


def relevant(question):
    folded = (question or "").casefold()
    return any(token in folded for token in (
        "tally", "day book", "daybook", "voucher", "what did we pay", "payments in", "paid to",
    ))


def _rows_for(question, rows):
    company = _company(question)
    day = _asked_day(question)
    month = _month(question)
    kind = _kind(question)
    picked = []
    for row in rows:
        if company and row["company"].casefold() != company:
            continue
        if day is not None and row["date"] != day:
            continue
        if month is not None and (row["date"] is None or row["date"].month != month):
            continue
        if kind and not row["type"].casefold().startswith(kind):
            continue
        picked.append(row)
    return picked


def _party(row):
    return row["dr"] or row["cr"] or ""


def answer(question, role):
    if role not in {"owner", "finance"}:
        return {"text": "Tally is not included for this role.", "table": None, "as_of": ""}
    rows = load_vouchers()
    if not rows:
        return {"text": "Tally day book is not loaded.", "table": None, "as_of": ""}
    cover = coverage_line(rows)
    folded = (question or "").casefold()
    day = _asked_day(question)
    by_company, last = coverage(rows)
    company = _company(question)
    if day is not None and company:
        present = by_company.get(company.title()) or by_company.get(company.capitalize()) or set()
        # company key is as stored
        present = next((days for name, days in by_company.items() if name.casefold() == company), set())
        if day not in present:
            text = f"{company.title()} has no day book rows on {day.strftime('%-d %b %Y')}. {cover}"
            return {"text": text, "table": None, "as_of": last.isoformat() if last else ""}
    if "p&l" in folded or "p and l" in folded or "ledger map" in folded or "by line" in folded:
        return _by_line(question, rows, cover, last)
    if any(token in folded for token in ("paid to", "pay to", "vendor")):
        return _named_party(question, rows, cover, last)
    picked = _rows_for(question, rows)
    if "top" in folded or "largest" in folded:
        picked = [row for row in picked if row["amt"] is not None]
        picked.sort(key=lambda row: row["amt"], reverse=True)
        limit = 10
        match = re.search(r"top\s+(\d+)", folded)
        if match:
            limit = min(int(match.group(1)), 10)
        picked = picked[:limit]
    else:
        picked = sorted(picked, key=lambda row: (row["date"] or datetime.min.date(), -(row["amt"] or 0)))
        if len(picked) > 12:
            picked = picked[:12]
    total = sum(row["amt"] or 0 for row in picked if row["amt"] is not None)
    lines = [cover, f"{len(picked)} vouchers shown. Total of these rows {_inr(total)}."]
    table_rows = []
    amounts = []
    for row in picked:
        when = row["date"].strftime("%-d %b %Y") if row["date"] else row["date_text"]
        lines.append(f"{row['company']} {when} {row['type']} {_party(row)} {_inr(row['amt'])}")
        table_rows.append([row["company"], when, row["type"], _party(row), _inr(row["amt"]) if row["amt"] is not None else ""])
        if row["amt"] is not None:
            amounts.append(row["amt"])
    from app.chat.visuals import table_block

    table = table_block(["Company", "Date", "Type", "Party", "Amount"], table_rows, "Tally day book")
    return {
        "text": "\n".join(lines),
        "table": table,
        "as_of": last.isoformat() if last else "",
        "amounts": amounts,
    }


def _named_party(question, rows, cover, last):
    folded = (question or "").casefold()
    words = [word for word in re.findall(r"[a-z]{4,}", folded) if word not in {
        "what", "paid", "pay", "payment", "vendor", "tally", "from", "with", "this", "that", "were", "have",
    }]
    picked = []
    for row in rows:
        blob = f"{row['dr']} {row['cr']}".casefold()
        if words and all(word in blob for word in words[:3]):
            if _kind(question) and not row["type"].casefold().startswith(_kind(question)):
                continue
            picked.append(row)
    picked.sort(key=lambda row: row["amt"] or 0, reverse=True)
    total = sum(row["amt"] or 0 for row in picked)
    if picked:
        lines = [cover, f"Matched {len(picked)} vouchers. Total {_inr(total)}."]
    else:
        lines = [cover, "No voucher matches that name."]
    table_rows = []
    amounts = []
    for row in picked[:10]:
        when = row["date"].strftime("%-d %b %Y") if row["date"] else ""
        lines.append(f"{row['company']} {when} {row['type']} {row['dr']} {_inr(row['amt'])}")
        table_rows.append([row["company"], when, row["dr"], _inr(row["amt"]) if row["amt"] is not None else ""])
        if row["amt"] is not None:
            amounts.append(row["amt"])
    from app.chat.visuals import table_block

    return {
        "text": "\n".join(lines) if isinstance(lines, list) else lines,
        "table": table_block(["Company", "Date", "Ledger", "Amount"], table_rows, "Tally party") if table_rows else None,
        "as_of": last.isoformat() if last else "",
        "amounts": amounts,
    }


def _by_line(question, rows, cover, last):
    mapping = {}
    for row in load_ledger_map():
        key = ((row.get("company") or "").casefold(), (row.get("ledger") or "").casefold())
        line = (row.get("pnl_line") or "").strip()
        if key[1] and line:
            mapping[key] = line
    month = _month(question) or (11 if "month-to-date" in (question or "").casefold() or "mtd" in (question or "").casefold() else None)
    company = _company(question)
    totals = {}
    used_days = set()
    unmatched = 0
    for row in rows:
        if row["date"] is None or row["amt"] is None:
            continue
        if company and row["company"].casefold() != company:
            continue
        if month and row["date"].month != month:
            continue
        if not row["type"].casefold().startswith(("payment", "purchase")):
            continue
        line = mapping.get((row["company"].casefold(), row["dr"].casefold()))
        if not line:
            unmatched += 1
            continue
        totals[line] = totals.get(line, 0) + row["amt"]
        used_days.add((row["company"], row["date"]))
    lines = [
        cover,
        "Spend is payment and purchase vouchers whose debit ledger is on the September ledger map. Unmapped ledgers are counted but not given a line.",
        f"Unmapped vouchers: {unmatched}. Days used: {len(used_days)}.",
    ]
    table_rows = []
    amounts = []
    for line, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"{line} {_inr(amount)}")
        table_rows.append([line, _inr(amount)])
        amounts.append(amount)
    if not totals:
        lines.append("No mapped payment or purchase fell in that slice.")
    from app.chat.visuals import table_block

    return {
        "text": "\n".join(lines),
        "table": table_block(["P&L line", "Amount"], table_rows, "Tally spend by line") if table_rows else None,
        "as_of": last.isoformat() if last else "",
        "amounts": amounts,
    }
