"""Parse Tally Day Book text extracts into the daybook_vouchers.csv shape.

A voucher is one dated header line plus the first opposing ledger (cr).
Amounts are taken from the file; nothing is estimated. Leading spaces on
later pages (the 16-27 Oct and 6-11 Nov packs) are accepted. Page headers
and comment lines are skipped.

Dedup key: company, date, type, no. Existing rows in the destination CSV
are kept as-is when the same voucher is parsed again.

Bank-statement extracts are not parsed as day books.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

_DATE = re.compile(
    r"^\s*(\d{1,2}-[A-Za-z]{3}-\d{2})\s+(.+?)\s{2,}(\S.*?)\s{2,}(\d+)\s+([\d,]+\.\d{2})\s*$"
)
_CONT = re.compile(r"^\s+(.+?)\s{2,}([\d,]+\.\d{2})\s*$")
_SKIP = re.compile(
    r"(?i)(day book|particulars|inwards qty|page\s+\d|debit amount|"
    r"dosa coffee|dalgreen|extracted from|^#|continued)"
)
_SINGLE_DAY = re.compile(
    r"(?i)daybook\s+(\d{1,2})[.\-](\d{1,2})[.\-](20\d{2}|\d{2})"
)
_COMPANY = (
    ("kolkata", "Kolkata"),
    ("delhi", "Delhi"),
    ("haryana", "Haryana"),
)


def _num(text):
    return float(str(text).replace(",", ""))


def company_from_name(name):
    folded = (name or "").casefold()
    for token, label in _COMPANY:
        if token in folded:
            return label
    if re.search(r"(^|[\s_\-])kol($|[\s_\-.])", folded):
        return "Kolkata"
    if re.search(r"(^|[\s_\-])up($|[\s_\-.])", folded) or "uttar" in folded:
        return "UP"
    return None


def parse_text(text, source="", company=""):
    """Parse the body of one Day Book text extract."""
    rows = []
    current = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if _SKIP.search(line) and not _DATE.match(line):
            current = None
            continue
        match = _DATE.match(line)
        if match:
            current = {
                "company": company,
                "date": match.group(1),
                "type": match.group(3).strip(),
                "no": match.group(4),
                "dr": match.group(2).strip(),
                "cr": "",
                "amt": f"{_num(match.group(5))}",
                "source": source,
            }
            rows.append(current)
            continue
        if current is not None and not current["cr"]:
            cont = _CONT.match(line)
            if cont:
                current["cr"] = cont.group(1).strip()
    return rows


def parse_file(path, company=None):
    path = Path(path)
    label = company or company_from_name(path.name)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    return parse_text(text, source=path.name, company=label or "")


def voucher_key(row):
    return (
        (row.get("company") or "").strip(),
        (row.get("date") or "").strip(),
        (row.get("type") or "").strip(),
        (row.get("no") or "").strip(),
    )


def load_csv(path):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def merge_vouchers(existing, incoming):
    """Keep existing rows when a key collides. Append only new vouchers."""
    seen = {voucher_key(row) for row in existing}
    out = list(existing)
    added = 0
    for row in incoming:
        key = voucher_key(row)
        if not key[0] or not key[1] or not key[3] or key in seen:
            continue
        seen.add(key)
        out.append({
            "company": row.get("company") or "",
            "date": row.get("date") or "",
            "type": row.get("type") or "",
            "no": row.get("no") or "",
            "dr": row.get("dr") or "",
            "cr": row.get("cr") or "",
            "amt": row.get("amt") or "",
            "source": row.get("source") or "",
        })
        added += 1
    return out, added


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["company", "date", "type", "no", "dr", "cr", "amt", "source"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name) or "" for name in fields})


def _is_bank_statement(path):
    name = path.name.casefold()
    if name.startswith("accountstmt") or "bankstatement" in name:
        return True
    if "bank" in name and "daybook" not in name and "day book" not in name:
        return True
    return False


def _is_daybook(path):
    name = path.name.casefold().replace(" ", "")
    return "daybook" in name and path.suffix.lower() == ".txt" and not _is_bank_statement(path)


def _is_range_name(name):
    return bool(re.search(r"\d{1,2}\s*[-to]+\s*\d{1,2}", name, re.I))


def preferred_daybook_files(folders):
    """One Day Book text per company, preferring single-day slices.

    Range packs (16-27 Oct, 6-11 Nov) are used only when a date has no
    single-day extract. Bank statements are never selected.
    """
    singles = []
    ranges = []
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.txt")):
            if not _is_daybook(path):
                continue
            if not company_from_name(path.name) and not company_from_name(path.parent.name):
                continue
            if _SINGLE_DAY.search(path.name) and not _is_range_name(path.name):
                singles.append(path)
            else:
                ranges.append(path)
    if singles:
        # Drop a range pack when we already have daily slices from the same tree.
        return singles + [path for path in ranges if "11" in path.name and "06" in path.name]
    return ranges + singles


def collect_from(folders):
    rows = []
    for path in preferred_daybook_files(folders):
        company = company_from_name(path.name) or company_from_name(path.parent.name)
        rows.extend(parse_file(path, company=company))
    return rows


if __name__ == "__main__":
    import sys
    from collections import Counter

    for arg in sys.argv[1:]:
        path = Path(arg)
        found = collect_from([path]) if path.is_dir() else parse_file(path)
        print(path, "vouchers", len(found), Counter(r["date"] for r in found))
