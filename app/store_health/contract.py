"""CSV contract for the Posist box and the predicted-vs-actual calendar.

An empty cell stays None. Callers render that as a blank. Zero is kept when
the file actually contains 0. This module never fills a missing cell.

posist_daily.csv — one row per store per date
    store, date, net, gross, bills, apb,
    net_wow_pct, bills_wow_pct, apb_wow_pct,
    net_last_same_weekday, bills_last_same_weekday, apb_last_same_weekday,
    unsettled_bills, unsettled_amount, void_bills,
    source (live|historical), provisional (bool)

sales_pred_vs_actual.csv — network shape, plus store on a store calendar
    date, weekday, tier, pred_low, pred_high, pred_mid, actual_net,
    variance_vs_mid, variance_pct, status, drivers, notes
    status: pending | actual | actual_provisional_eod

Money is rupees unless the column name ends with _L (already in lakhs).
"""

import csv
import os
from datetime import date
from pathlib import Path


POSIST_FILE = "posist_daily.csv"
CALENDAR_FILE = "sales_pred_vs_actual.csv"

POSIST_COLUMNS = (
    "store",
    "date",
    "net",
    "gross",
    "bills",
    "apb",
    "net_wow_pct",
    "bills_wow_pct",
    "apb_wow_pct",
    "net_last_same_weekday",
    "bills_last_same_weekday",
    "apb_last_same_weekday",
    "unsettled_bills",
    "unsettled_amount",
    "void_bills",
    "source",
    "provisional",
)

# Network file shape. Store calendars use these columns plus store.
CALENDAR_VALUE_COLUMNS = (
    "date",
    "weekday",
    "tier",
    "pred_low",
    "pred_high",
    "pred_mid",
    "actual_net",
    "variance_vs_mid",
    "variance_pct",
    "status",
    "drivers",
    "notes",
)
CALENDAR_COLUMNS = ("store",) + CALENDAR_VALUE_COLUMNS

POSIST_MONEY = {
    "net",
    "gross",
    "apb",
    "net_last_same_weekday",
    "apb_last_same_weekday",
    "unsettled_amount",
}
POSIST_COUNTS = {
    "bills",
    "bills_last_same_weekday",
    "unsettled_bills",
    "void_bills",
}
POSIST_PERCENTS = {"net_wow_pct", "bills_wow_pct", "apb_wow_pct"}

CALENDAR_MONEY = {
    "pred_low",
    "pred_high",
    "pred_mid",
    "actual_net",
    "variance_vs_mid",
}
CALENDAR_PERCENTS = {"variance_pct"}
CALENDAR_TEXT = {"weekday", "tier", "status", "drivers", "notes"}

ALLOWED_SOURCE = {"live", "historical"}
ALLOWED_STATUS = {"pending", "actual", "actual_provisional_eod"}


def data_directory():
    override = os.getenv("STORE_HEALTH_DATA_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data" / "store_health"


def _blank(value):
    if value is None:
        return True
    return str(value).strip() == ""


def parse_number(value):
    """Return a float, or None when the cell is blank or not a number."""
    if _blank(value):
        return None
    text = str(value).strip().replace("₹", "").replace(",", "").replace("%", "")
    text = text.replace(" ", "")
    if text[:1] in {"+", "−"}:
        text = text[1:] if text[0] == "+" else "-" + text[1:]
    if text in {"", "-", ".", "-."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_bool(value):
    if _blank(value):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def parse_date(value):
    if _blank(value):
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _normalise_header(name):
    return (name or "").strip().lower()


def _read_dicts(path, warnings):
    if not path.exists():
        return None
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                warnings.append(f"{path.name} has no header row.")
                return []
            rows = []
            for raw in reader:
                if raw is None:
                    continue
                if all(_blank(cell) for cell in raw.values()):
                    continue
                rows.append({_normalise_header(key): value for key, value in raw.items()})
            return rows
    except UnicodeError:
        warnings.append(f"{path.name} is not UTF-8, so it was not loaded.")
        return []
    except OSError as exc:
        warnings.append(f"{path.name} could not be read ({exc}).")
        return []
    except csv.Error as exc:
        warnings.append(f"{path.name} is not valid CSV ({exc}).")
        return []


def _warn(warnings, message):
    if len(warnings) < 8:
        warnings.append(message)
    elif len(warnings) == 8:
        warnings.append("Further file warnings were omitted.")


def load_posist(directory=None):
    """Map (store name, date) to a daily row. Last row in the file wins."""
    directory = Path(directory) if directory else data_directory()
    warnings = []
    path = directory / POSIST_FILE
    table = _read_dicts(path, warnings)
    rows = {}
    if not table:
        return rows, warnings
    header_checked = False
    for index, raw in enumerate(table, start=2):
        if not header_checked:
            header_checked = True
            missing = [name for name in ("store", "date") if name not in raw]
            if missing:
                _warn(warnings, f"{POSIST_FILE} is missing {', '.join(missing)}.")
                return {}, warnings
        store = (raw.get("store") or "").strip()
        day = parse_date(raw.get("date"))
        if not store or day is None:
            _warn(warnings, f"{POSIST_FILE} row {index} has no store or date, so it was skipped.")
            continue
        parsed = {"store": store, "date": day}
        for field in POSIST_COLUMNS:
            if field in {"store", "date"}:
                continue
            if field not in raw:
                parsed[field] = None
                continue
            cell = raw.get(field)
            if field == "provisional":
                value = parse_bool(cell)
                if value is None and not _blank(cell):
                    _warn(warnings, f"{POSIST_FILE} row {index} provisional is not true or false, so it was left blank.")
                parsed[field] = value
            elif field == "source":
                if _blank(cell):
                    parsed[field] = None
                else:
                    text = str(cell).strip().lower()
                    parsed[field] = text
                    if text not in ALLOWED_SOURCE:
                        _warn(warnings, f"{POSIST_FILE} row {index} source is {text!r}. Expected live or historical.")
            else:
                value = parse_number(cell)
                if value is None and not _blank(cell):
                    _warn(warnings, f"{POSIST_FILE} row {index} {field} is not a number, so it was left blank.")
                parsed[field] = value
        key = (store, day)
        if key in rows:
            _warn(warnings, f"{POSIST_FILE} has more than one row for {store} on {day.isoformat()}; the last row is shown.")
        rows[key] = parsed
    return rows, warnings


def load_calendar(directory=None):
    """Map (store name, date) to a calendar row.

    Rows with a blank store are network rows and are not attached to a store.
    """
    directory = Path(directory) if directory else data_directory()
    warnings = []
    path = directory / CALENDAR_FILE
    table = _read_dicts(path, warnings)
    rows = {}
    if not table:
        return rows, warnings
    has_store = "store" in table[0]
    if not has_store:
        _warn(
            warnings,
            f"{CALENDAR_FILE} has no store column, so those rows were not applied to a store.",
        )
        return rows, warnings
    saw_blank_store = False
    for index, raw in enumerate(table, start=2):
        store = (raw.get("store") or "").strip()
        day = parse_date(raw.get("date"))
        if not store:
            saw_blank_store = True
            continue
        if day is None:
            _warn(warnings, f"{CALENDAR_FILE} row {index} has no date, so it was skipped.")
            continue
        parsed = {"store": store, "date": day}
        for field in CALENDAR_VALUE_COLUMNS:
            if field == "date":
                continue
            cell = raw.get(field) if field in raw else None
            if field in CALENDAR_TEXT:
                if _blank(cell):
                    parsed[field] = None
                else:
                    text = str(cell).strip()
                    if field == "status":
                        lowered = text.lower()
                        parsed[field] = lowered
                        if lowered not in ALLOWED_STATUS:
                            _warn(
                                warnings,
                                f"{CALENDAR_FILE} row {index} status is {text!r}. "
                                "Expected pending, actual, or actual_provisional_eod.",
                            )
                    else:
                        parsed[field] = text
            else:
                value = parse_number(cell)
                if value is None and not _blank(cell):
                    _warn(warnings, f"{CALENDAR_FILE} row {index} {field} is not a number, so it was left blank.")
                parsed[field] = value
        key = (store, day)
        if key in rows:
            _warn(warnings, f"{CALENDAR_FILE} has more than one row for {store} on {day.isoformat()}; the last row is shown.")
        rows[key] = parsed
    if saw_blank_store and not rows:
        _warn(warnings, f"{CALENDAR_FILE} rows have no store, so they were not applied to a store.")
    return rows, warnings


def load_feeds(directory=None):
    directory = Path(directory) if directory else data_directory()
    posist, posist_warnings = load_posist(directory)
    calendar, calendar_warnings = load_calendar(directory)
    return {
        "posist": posist,
        "calendar": calendar,
        "warnings": posist_warnings + calendar_warnings,
        "directory": directory,
    }


def store_names_in_feeds(feeds):
    names = set()
    for store, _day in feeds["posist"]:
        names.add(store)
    for store, _day in feeds["calendar"]:
        names.add(store)
    return names
