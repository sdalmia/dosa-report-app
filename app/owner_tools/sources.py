"""Owner-only files. Store-health CSVs stay on the shared loader.

A missing file is reported. It is never filled with a zero.
"""

import csv
import os
import re
from pathlib import Path

from app.store_health.contract import parse_number

FOOD_SAFETY_TERMS = (
    "food safety",
    "food-safety",
    "hygiene",
    "contaminat",
    "pest",
    "foreign body",
    "foreign object",
    "food poisoning",
    "unsafe food",
)
EMERGENCY_TERMS = ("emergency", "fire", "injury", "injured", "accident", "ambulance", "evacuation")
_SKIP_VALUES = {"no", "none", "n/a", "na", "not shown", "not available", "-"}
_FLAG_COLUMNS = {"flag", "flags", "alert", "alerts", "status", "issue", "issues"}
# Bill reconciliation uses status for match / amount_mismatch. That is not an owner flag.
# Batch movement files use status for how a row was booked, not as a brief flag.
_STATUS_NOT_A_FLAG = {
    "match",
    "amount_mismatch",
    "issued_from_ck",
    "consumed_no_issue_record (made in store or untracked)",
    "wastage_or_return_only",
}
_ID_COLUMNS = {
    "posist_store",
    "famepilot_location",
    "store",
    "rating",
    "review_count",
    "private_rating",
    "private_review_count",
    "overall_reviews",
}


def repo_root():
    return Path(__file__).resolve().parents[2]


def goals_path():
    override = os.getenv("OWNER_GOALS_FILE")
    if override:
        return Path(override)
    return repo_root() / "data" / "goals.csv"


def procurement_dir():
    override = os.getenv("OWNER_PROCUREMENT_DIR")
    if override:
        return Path(override)
    return repo_root() / "data" / "procurement"


def wastage_path(directory):
    override = os.getenv("OWNER_WASTAGE_FILE")
    if override:
        return Path(override)
    return Path(directory) / "wastage.csv"


def _blank(value):
    return value is None or str(value).strip() == ""


def read_csv(path):
    """Return (rows, fieldnames). None rows means the file is missing."""
    path = Path(path)
    if not path.exists():
        return None, []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = []
        for raw in reader:
            if raw is None or all(_blank(cell) for cell in raw.values()):
                continue
            rows.append({(key or "").strip(): (value if value is not None else "") for key, value in raw.items()})
        return rows, fieldnames


def load_goals():
    path = goals_path()
    rows, fieldnames = read_csv(path)
    header = [name.strip() for name in fieldnames]
    if rows is None:
        return {
            "state": "missing",
            "rows": [],
            "message": "No targets yet. Add a monthly gross target to see progress.",
        }
    if header[:3] != ["store", "month", "target_gross"]:
        return {
            "state": "unreadable",
            "rows": [],
            "message": "Targets could not be read. They need a store, a month, and a gross target.",
        }
    if not rows:
        return {
            "state": "empty",
            "rows": [],
            "message": "No targets yet. Add a monthly gross target to see progress.",
        }
    return {"state": "ready", "rows": rows, "message": ""}


def _contains_term(text, term):
    if " " in term or "-" in term:
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _kinds_for_cell(column, value):
    text = str(value).strip()
    if not text or text.casefold() in _SKIP_VALUES:
        return []
    low = text.casefold()
    col = column.strip().casefold().replace(" ", "_")
    kinds = []
    column_is_safety = "food_safety" in col or "food-safety" in col or col == "hygiene"
    column_is_emergency = "emergency" in col
    if column_is_safety or any(_contains_term(low, term) for term in FOOD_SAFETY_TERMS):
        kinds.append("food_safety")
    if column_is_emergency or any(_contains_term(low, term) for term in EMERGENCY_TERMS):
        kinds.append("emergency")
    return kinds


def scan_famepilot(directory):
    path = Path(directory) / "famepilot.csv"
    rows, _fieldnames = read_csv(path)
    result = {
        "food_safety": [],
        "emergency": [],
        "food_safety_empty": "No food-safety notes from Famepilot.",
        "emergency_empty": "No emergency notes from Famepilot.",
    }
    if rows is None:
        missing = "No notes from Famepilot."
        result["food_safety_empty"] = missing
        result["emergency_empty"] = missing
        return result
    for row in rows:
        store = (row.get("posist_store") or row.get("store") or "").strip()
        for column, value in row.items():
            if column.strip().casefold() in _ID_COLUMNS:
                continue
            for kind in _kinds_for_cell(column, value):
                result[kind].append(
                    {
                        "store": store,
                        "column": column,
                        "text": str(value).strip(),
                    }
                )
    if result["food_safety"]:
        result["food_safety_empty"] = ""
    if result["emergency"]:
        result["emergency_empty"] = ""
    return result


def _is_flag_column(name):
    key = (name or "").strip().casefold()
    return key in _FLAG_COLUMNS or key.endswith("_flag")


_PROCUREMENT_SCAN = {}


def clear_procurement_scan_cache():
    _PROCUREMENT_SCAN.clear()


def _csv_fieldnames(path):
    """Header only. The cost-line files are tens of thousands of rows."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return []
    # Keep the header text DictReader uses as the key, including spacing.
    return ["" if name is None else name for name in header]


def _directory_signature(directory):
    parts = []
    for path in sorted(directory.glob("*.csv")):
        if not path.is_file():
            continue
        st = path.stat()
        parts.append((path.name, st.st_mtime_ns, st.st_size))
    return tuple(parts)


def scan_procurement():
    """Flag columns from procurement CSVs.

    A file is opened in full only when its header has a flag column.
    menu_item_cost_lines*.csv has no such column, so those rows stay on disk.
    """
    directory = procurement_dir()
    if not directory.exists():
        return {
            "items": [],
            "empty": "No procurement flags yet.",
        }
    signature = _directory_signature(directory)
    cached = _PROCUREMENT_SCAN.get((str(directory), signature))
    if cached is not None:
        return cached
    files = [path for path in sorted(directory.glob("*.csv")) if path.is_file()]
    if not files:
        result = {
            "items": [],
            "empty": "No procurement flags yet.",
        }
        _PROCUREMENT_SCAN[(str(directory), signature)] = result
        return result
    items = []
    saw_column = False
    for path in files:
        fieldnames = _csv_fieldnames(path)
        columns = [name for name in fieldnames if _is_flag_column(name)]
        if not columns:
            continue
        rows, fieldnames = read_csv(path)
        saw_column = True
        for row in rows or []:
            parts = []
            for column in columns:
                text = str(row.get(column) or "").strip()
                if column.strip().casefold() == "status" and text.casefold() in _STATUS_NOT_A_FLAG:
                    continue
                if text and text.casefold() not in _SKIP_VALUES:
                    parts.append(f"{column}: {text}")
            if not parts:
                continue
            store = (row.get("store") or row.get("posist_store") or "").strip()
            items.append({"file": path.name, "store": store, "text": "; ".join(parts)})
    if not saw_column:
        empty = "No procurement flags yet."
    elif not items:
        empty = "No procurement flags yet."
    else:
        empty = ""
    result = {"items": items, "empty": empty}
    _PROCUREMENT_SCAN[(str(directory), signature)] = result
    return result


def load_wastage(directory):
    """Raw wastage rows. Matching to a Posist store happens per month."""
    path = wastage_path(directory)
    rows, fieldnames = read_csv(path)
    empty = "No wastage figure yet, so that part of the score is left out."
    if rows is None:
        return {"present": False, "rows": [], "empty": empty}
    header = {name.strip().casefold() for name in fieldnames}
    if "store" not in header:
        return {
            "present": True,
            "rows": [],
            "empty": "Wastage could not be matched to a store, so that part of the score is left out.",
        }
    normalised = []
    for row in rows:
        mapped = {(key or "").strip().casefold(): value for key, value in row.items()}
        store = str(mapped.get("store") or "").strip()
        if not store:
            continue
        normalised.append(
            {
                "store": store,
                "month": str(mapped.get("month") or "").strip(),
                "wastage_pct": parse_number(mapped.get("wastage_pct")),
                "wastage_amount": parse_number(mapped.get("wastage_amount")),
            }
        )
    if not normalised:
        return {
            "present": True,
            "rows": [],
            "empty": "No wastage figure yet, so that part of the score is left out.",
        }
    return {"present": True, "rows": normalised, "empty": ""}
