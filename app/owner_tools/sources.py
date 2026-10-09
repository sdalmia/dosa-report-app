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
            "message": "Targets need data/goals.csv with columns store, month, target_gross. That file is missing.",
        }
    if header[:3] != ["store", "month", "target_gross"]:
        return {
            "state": "unreadable",
            "rows": [],
            "message": "data/goals.csv must start with the columns store, month, target_gross.",
        }
    if not rows:
        return {
            "state": "empty",
            "rows": [],
            "message": "data/goals.csv has the headers store, month, target_gross and no targets yet. Add a target_gross for a store and month (YYYY-MM) to draw a progress bar.",
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
        "food_safety_empty": (
            "No food-safety item is named in data/store_health/famepilot.csv. "
            "main_threat is an operational theme (such as Missing Item or Quality Issue) and does not say food safety. "
            "Add that wording, or a food_safety column, to show items here."
        ),
        "emergency_empty": (
            "No emergency item is named in data/store_health/famepilot.csv. "
            "None of the threat text says emergency. Add that wording, or an emergency column, to show items here."
        ),
    }
    if rows is None:
        missing = "data/store_health/famepilot.csv is missing, so there are no food-safety or emergency items to show."
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


def scan_procurement():
    directory = procurement_dir()
    if not directory.exists():
        return {
            "items": [],
            "empty": "Procurement flags need a folder at data/procurement. It is not in the repo.",
        }
    files = sorted(path for path in directory.glob("*.csv") if path.is_file())
    if not files:
        return {
            "items": [],
            "empty": "data/procurement has no CSV. Add a CSV with a flag, alert, or status column.",
        }
    items = []
    saw_column = False
    for path in files:
        rows, fieldnames = read_csv(path)
        columns = [name for name in fieldnames if _is_flag_column(name)]
        if not columns:
            continue
        saw_column = True
        for row in rows or []:
            parts = []
            for column in columns:
                text = str(row.get(column) or "").strip()
                if text and text.casefold() not in _SKIP_VALUES:
                    parts.append(f"{column}: {text}")
            if not parts:
                continue
            store = (row.get("store") or row.get("posist_store") or "").strip()
            items.append({"file": path.name, "store": store, "text": "; ".join(parts)})
    if not saw_column:
        empty = "data/procurement has CSV files, but none has a flag, alert, or status column."
    elif not items:
        empty = "data/procurement has a flag column, and every flag cell is blank."
    else:
        empty = ""
    return {"items": items, "empty": empty}


def load_wastage(directory):
    """Raw wastage rows. Matching to a Posist store happens per month."""
    path = wastage_path(directory)
    rows, fieldnames = read_csv(path)
    empty = (
        "Wastage needs data/store_health/wastage.csv with columns store and wastage_pct "
        "(or wastage_amount). That file is not in the repo, so this part of the score is left blank."
    )
    if rows is None:
        return {"present": False, "rows": [], "empty": empty}
    header = {name.strip().casefold() for name in fieldnames}
    if "store" not in header:
        return {
            "present": True,
            "rows": [],
            "empty": "data/store_health/wastage.csv has no store column, so wastage was not applied.",
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
            "empty": "data/store_health/wastage.csv has headers only, so wastage is blank.",
        }
    return {"present": True, "rows": normalised, "empty": ""}
