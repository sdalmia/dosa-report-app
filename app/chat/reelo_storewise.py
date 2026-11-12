"""Logan's store-wise Reelo extract.

One file is the whole source. A Monday load replaces that file.
Rows are not appended to older weeks. Stores that are not in the file
are left out on purpose and are not treated as gaps.
"""

import csv
from pathlib import Path

PERIOD = "13 Oct to 12 Nov 2026"
FILENAME = "reelo_storewise_latest.csv"


def directory():
    return Path(__file__).resolve().parents[2] / "data" / "reelo"


def path():
    return directory() / FILENAME


def _number(value):
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_storewise(source=None):
    """Rows in the current file only. A missing file is an empty list."""
    file_path = Path(source) if source else path()
    if not file_path.is_file():
        return []
    rows = []
    with file_path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            store = (raw.get("Store") or "").strip()
            if not store:
                continue
            rows.append({
                "store": store,
                "orders": _number(raw.get("Total Orders")),
                "phone_capture": _number(raw.get("%")),
                "customers": _number(raw.get("Customers visited")),
                "new_customers": _number(raw.get("New Customers")),
                "repeat_customers": _number(raw.get("Repeat Customers")),
                "repeat_share": _number(raw.get("Derived repeat customer share (%)")),
                "rating": _number(raw.get("avg_rating")),
                "feedback": _number(raw.get("total_feedbacks_submitted")),
                "redemption": _number(raw.get("redemption_rate_in_percentage")),
            })
    return rows


def replace_storewise(text, source=None):
    """Write the Monday file in place. Previous rows are not kept."""
    file_path = Path(source) if source else path()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(text, encoding="utf-8")
    return load_storewise(file_path)
