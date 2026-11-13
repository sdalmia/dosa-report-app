"""Logan's deeper Reelo drop. The Monday storewise file is unchanged.

The newest dated folder under data/reelo wins. Blank cells stay blank.
Closed stores are dropped again here even if a future file includes them.
NPS is not in these files.
"""

import csv
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CLOSED = ("faridabad", "chattarpur", "gk1", "gk 1")


def history_dir():
    base = _ROOT / "data" / "reelo"
    if not base.is_dir():
        return None
    dated = [path for path in base.iterdir() if path.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)]
    return max(dated, key=lambda path: path.name) if dated else None


def _read(name):
    folder = history_dir()
    if folder is None:
        return []
    path = folder / name
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    kept = []
    for row in rows:
        blob = " ".join(str(value or "") for value in row.values()).casefold()
        if any(token in blob for token in _CLOSED):
            continue
        kept.append({key: (value if value is not None else "") for key, value in row.items()})
    return kept


def lapsed():
    return _read("lapsed_all_stores_as_of_2026-11-13.csv")


def segments():
    return _read("segments_all_stores_last_year_as_of_2026-11-13.csv")


def monthly_customers():
    return _read("customers_monthly_all_stores_2026-01-01_to_2026-10-31.csv")


def summary_text():
    folder = history_dir()
    if folder is None:
        return "Deep Reelo folder is not loaded. The Monday storewise file is still the weekly source."
    lines = [
        f"Deep Reelo pull {folder.name}. Range 1 Jan–12 Nov 2026 unless a filename says otherwise.",
        "Aggregates only. Blank cells stay blank. NPS is not in Reelo, so no NPS is stated.",
        "Lapsed counts are all-store only. Spend on the all-store segments is blank, so no rupee win-back is stated.",
    ]
    for row in lapsed():
        lines.append(
            f"Lapsed {row.get('has_not_visited_in_last_days')} days: {row.get('customers') or 'blank'} customers. {row.get('basis') or ''}"
        )
    months = monthly_customers()
    if len(months) >= 2:
        last, prior = months[-1], months[-2]
        lines.append(
            f"All-store customers {last.get('period')}: {last.get('customers')} "
            f"(repeat share {last.get('repeat_customers_percentage')}%). "
            f"Prior month {prior.get('period')}: {prior.get('customers')} "
            f"(repeat share {prior.get('repeat_customers_percentage')}%)."
        )
    lines.append("Stores not on Reelo are still not shown as zero: Manisquare, Forum, New Town Cloud Kitchen, Calcutta Swimming Club, Food Truck, Events & Catering, GK1, Chattarpur.")
    return "\n".join(lines)


def winback_line():
    rows = {row.get("has_not_visited_in_last_days"): row.get("customers") for row in lapsed()}
    thirty = rows.get("30") or ""
    if not thirty:
        return "Reelo win-back size is not loaded."
    return (
        f"Reelo win-back size: {thirty} customers have not visited in 30 days, all stores together. "
        "Spend for that list is blank, so no rupee value is stated."
    )
