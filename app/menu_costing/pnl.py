"""Company P&L placeholder. Numbers appear only when an Accountant file is on disk.

A blank cell stays blank. Nothing here is estimated.
"""

import csv
import re
from datetime import date
from pathlib import Path

from app.menu_costing.catalog import owner_rupee
from app.procurement.numbers import num_attr, parse_number

COMPANIES = ("Kolkata", "Delhi", "UP", "Haryana")
LINES = (
    ("book_food_cost", "Book food cost"),
    ("recipe_cost", "Recipe cost"),
    ("rent", "Rent"),
    ("salaries", "Salaries"),
    ("aggregator_commissions", "Aggregator commissions"),
)
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def tally_dir():
    return Path(__file__).resolve().parents[2] / "data" / "tally"


def load_pnl(directory=None):
    root = Path(directory) if directory else tally_dir()
    found = _read(root)
    companies = []
    for name in COMPANIES:
        values = found["values"].get(name.casefold(), {})
        lines = []
        for key, label in LINES:
            number = values.get(key)
            lines.append(
                {
                    "key": key,
                    "label": label,
                    "text": "Data coming" if number is None else owner_rupee(number),
                    "attr": "" if number is None else num_attr(number),
                    "coming": number is None,
                }
            )
        companies.append({"name": name, "lines": lines})
    return {
        "companies": companies,
        "month_label": found["label"],
        "coming": found["label"] == "",
    }


def _read(root):
    latest = None
    values = {}
    if not root.is_dir():
        return {"label": "", "values": values}
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        match = _MONTH.match(child.name)
        if match is None:
            continue
        year, month = int(match.group(1)), int(match.group(2))
        if month < 1 or month > 12:
            continue
        month_values = _read_month(child)
        if not month_values and not any(child.glob("*.csv")):
            continue
        latest = (year, month)
        values = month_values
    label = ""
    if latest is not None:
        label = date(latest[0], latest[1], 1).strftime("%B %Y")
    return {"label": label, "values": values}


def _read_month(folder):
    values = {}
    known = {key for key, _label in LINES}
    allowed = {name.casefold(): name for name in COMPANIES}
    for path in sorted(folder.glob("*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                company = allowed.get((raw.get("company") or "").strip().casefold())
                if company is None:
                    continue
                bucket = values.setdefault(company.casefold(), {})
                for key in known:
                    if key not in raw:
                        continue
                    number = parse_number(raw.get(key))
                    if number is None and not str(raw.get(key) or "").strip():
                        continue
                    bucket[key] = number
    return values
