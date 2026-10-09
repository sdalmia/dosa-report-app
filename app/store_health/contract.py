"""CSV contract for the Posist box and the predicted-vs-actual calendar.

An empty cell stays None. Callers render that as a blank. Zero is kept when
the file actually contains 0. This module never fills a missing cell.

posist_daily.csv — one row per store per date
    store, date, net, gross, bills, apb,
    net_wow_pct, bills_wow_pct, apb_wow_pct,
    net_last_same_weekday, bills_last_same_weekday, apb_last_same_weekday,
    unsettled_bills, unsettled_amount, void_bills,
    source (live|historical|historical-total-revenue), provisional (bool), region

sales_pred_vs_actual.csv — network shape, plus store on a store calendar
    date, weekday, tier, pred_low, pred_high, pred_mid, actual_net,
    variance_vs_mid, variance_pct, status, drivers, notes
    status: pending | actual | actual_provisional_eod | share_of_network_band | not_on_deployment_report

Money is rupees unless the column name ends with _L (already in lakhs).
"""

import csv
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


POSIST_FILE = "posist_daily.csv"
CALENDAR_FILE = "sales_pred_vs_actual.csv"
KEKA_FILE = "keka.csv"
KEKA_ACTIVE_FILE = "keka_active.csv"
AUDIT_FILE = "mystery_audit.csv"
REELO_FILE = "reelo.csv"
FAMEPILOT_FILE = "famepilot.csv"
MENU_MIX_FILE = "menu_mix.csv"
ITEM_SALES_FILE = "item_sales.csv"

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
    "region",
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

KEKA_COLUMNS = (
    "posist_store",
    "keka_location",
    "headcount",
    "primary_lead",
    "other_leads",
    "match_status",
    "note",
)
KEKA_ACTIVE_COLUMNS = (
    "posist_store",
    "active_employees",
    "keka_location",
    "match_status",
    "definition",
)

AUDIT_COLUMNS = (
    "store",
    "period",
    "avg_score",
    "weekday_score",
    "weekend_score",
    "note",
    "status",
)

REELO_COLUMNS = (
    "posist_store",
    "reelo_store",
    "date_range",
    "match_status",
    "times_rewards_redeemed",
    "redemption_rate",
    "redemption_revenue_inr",
    "avg_revenue_per_redemption_inr",
    "points_issued",
    "sales_total_inr_last30d",
    "visits_last30d",
    "phones_valid_visits",
    "phones_blocked_visits",
    "phone_capture_pct",
    "customers_with_purchase",
    "active_customers",
    "inactive_customers",
    "note",
)

FAMEPILOT_COLUMNS = (
    "posist_store",
    "famepilot_location",
    "rating",
    "review_count",
    "main_threat",
    "private_rating",
    "private_review_count",
    "overall_reviews",
)

MENU_MIX_COLUMNS = (
    "store",
    "item",
    "total_sales",
    "total_orders",
    "contribution_pct",
    "period_start",
    "period_end",
)

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

ALLOWED_SOURCE = {"live", "historical", "historical-total-revenue"}
ALLOWED_STATUS = {
    "pending",
    "actual",
    "actual_provisional_eod",
    "share_of_network_band",
    "not_on_deployment_report",
}


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
                        _warn(
                            warnings,
                            f"{POSIST_FILE} row {index} source is {text!r}. "
                            "Expected live, historical, or historical-total-revenue.",
                        )
            elif field == "region":
                parsed[field] = None if _blank(cell) else str(cell).strip()
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
                                "Expected pending, actual, actual_provisional_eod, "
                                "share_of_network_band, or not_on_deployment_report.",
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


def _text_cell(value):
    if _blank(value):
        return None
    return str(value).strip()


def load_keka_active(directory=None):
    """Active employee counts. A blank stays blank. It is not zero."""
    directory = Path(directory) if directory else data_directory()
    return _load_store_rows(directory, KEKA_ACTIVE_FILE, KEKA_ACTIVE_COLUMNS, "posist_store")


def load_keka(directory=None):
    """Rows from keka.csv. The headcount column is not the staff number on the page."""
    directory = Path(directory) if directory else data_directory()
    warnings = []
    path = directory / KEKA_FILE
    table = _read_dicts(path, warnings)
    rows = []
    if not table:
        return rows, warnings
    if "posist_store" not in table[0]:
        _warn(warnings, f"{KEKA_FILE} is missing posist_store.")
        return [], warnings
    for index, raw in enumerate(table, start=2):
        store = _text_cell(raw.get("posist_store"))
        if not store:
            _warn(warnings, f"{KEKA_FILE} row {index} has no posist_store, so it was skipped.")
            continue
        parsed = {field: _text_cell(raw.get(field)) for field in KEKA_COLUMNS}
        parsed["posist_store"] = store
        rows.append(parsed)
    return rows, warnings


def is_brand_audit(row):
    status = (row.get("status") or "").strip().casefold()
    store = (row.get("store") or "").strip().casefold()
    return status == "brand aggregate" or store == "brand"


def load_audit(directory=None):
    """Mystery-audit rows. Scores stay as written, including notes that are not numbers."""
    directory = Path(directory) if directory else data_directory()
    warnings = []
    path = directory / AUDIT_FILE
    table = _read_dicts(path, warnings)
    rows = []
    if not table:
        return rows, warnings
    if "store" not in table[0]:
        _warn(warnings, f"{AUDIT_FILE} is missing store.")
        return [], warnings
    for index, raw in enumerate(table, start=2):
        store = _text_cell(raw.get("store"))
        if not store:
            _warn(warnings, f"{AUDIT_FILE} row {index} has no store, so it was skipped.")
            continue
        parsed = {field: _text_cell(raw.get(field)) for field in AUDIT_COLUMNS}
        parsed["store"] = store
        rows.append(parsed)
    return rows, warnings


def _load_store_rows(directory, filename, columns, label_key):
    warnings = []
    path = Path(directory) / filename
    table = _read_dicts(path, warnings)
    rows = []
    if not table:
        return rows, warnings
    if label_key not in table[0]:
        _warn(warnings, f"{filename} is missing {label_key}.")
        return [], warnings
    for index, raw in enumerate(table, start=2):
        store = _text_cell(raw.get(label_key))
        if not store:
            _warn(warnings, f"{filename} row {index} has no {label_key}, so it was skipped.")
            continue
        parsed = {field: _text_cell(raw.get(field)) for field in columns}
        parsed[label_key] = store
        rows.append(parsed)
    return rows, warnings


def load_reelo(directory=None):
    directory = Path(directory) if directory else data_directory()
    return _load_store_rows(directory, REELO_FILE, REELO_COLUMNS, "posist_store")


def load_famepilot(directory=None):
    directory = Path(directory) if directory else data_directory()
    return _load_store_rows(directory, FAMEPILOT_FILE, FAMEPILOT_COLUMNS, "posist_store")


def load_menu_mix(directory=None, filename=None):
    """Item rows from Posist Insights Menu Analysis. Every row is kept.

    A blank sales, order, or contribution cell stays blank. This does not
    invent an item or turn a blank into zero.
    """
    directory = Path(directory) if directory else data_directory()
    filename = filename or MENU_MIX_FILE
    warnings = []
    path = directory / filename
    table = _read_dicts(path, warnings)
    rows = []
    if not table:
        return rows, warnings
    required = ("store", "item", "period_start", "period_end")
    missing = [name for name in required if name not in table[0]]
    if missing:
        _warn(warnings, f"{filename} is missing {', '.join(missing)}.")
        return [], warnings
    for index, raw in enumerate(table, start=2):
        store = _text_cell(raw.get("store"))
        item = _text_cell(raw.get("item"))
        start = parse_date(raw.get("period_start"))
        end = parse_date(raw.get("period_end"))
        if not store or not item or start is None or end is None or end < start:
            _warn(warnings, f"{filename} row {index} has no store, item, or period, so it was skipped.")
            continue
        parsed = {
            "store": store,
            "item": item,
            "total_sales": parse_number(raw.get("total_sales")),
            "total_orders": parse_number(raw.get("total_orders")),
            "contribution_pct": parse_number(raw.get("contribution_pct")),
            "period_start": start,
            "period_end": end,
        }
        for field in ("total_sales", "total_orders", "contribution_pct"):
            cell = raw.get(field)
            if parsed[field] is None and not _blank(cell):
                _warn(warnings, f"{filename} row {index} {field} is not a number, so it was left blank.")
        rows.append(parsed)
    return rows, warnings


def load_item_sales(directory=None):
    """Per-store item sales. Absent until the file is dropped in.

    A period file uses the menu-mix columns. A daily file uses
    store, item, date, sales, orders. Blank cells stay blank.
    """
    directory = Path(directory) if directory else data_directory()
    path = directory / ITEM_SALES_FILE
    if not path.is_file():
        return [], []
    warnings = []
    table = _read_dicts(path, warnings)
    if not table:
        return [], warnings
    headers = set(table[0])
    if "period_start" in headers and "period_end" in headers:
        return load_menu_mix(directory, ITEM_SALES_FILE)
    if "date" not in headers:
        _warn(warnings, f"{ITEM_SALES_FILE} needs a date or a period, so it was left unused.")
        return [], warnings
    rows = []
    for index, raw in enumerate(table, start=2):
        store = _text_cell(raw.get("store"))
        item = _text_cell(raw.get("item"))
        day = parse_date(raw.get("date"))
        if not store or not item or day is None:
            _warn(warnings, f"{ITEM_SALES_FILE} row {index} has no store, item, or date, so it was skipped.")
            continue
        sales_cell = raw.get("total_sales")
        if sales_cell is None or _blank(sales_cell):
            sales_cell = raw.get("sales")
        orders_cell = raw.get("total_orders")
        if orders_cell is None or _blank(orders_cell):
            orders_cell = raw.get("orders")
        rows.append({
            "store": store,
            "item": item,
            "total_sales": parse_number(sales_cell),
            "total_orders": parse_number(orders_cell),
            "contribution_pct": parse_number(raw.get("contribution_pct")),
            "period_start": day,
            "period_end": day,
        })
    return rows, warnings


def load_feeds(directory=None):
    from app.store_health.stores import assign_rows, extra_store_labels, match_menu_store

    directory = Path(directory) if directory else data_directory()
    posist, posist_warnings = load_posist(directory)
    calendar, calendar_warnings = load_calendar(directory)
    keka, keka_warnings = load_keka(directory)
    keka_active, keka_active_warnings = load_keka_active(directory)
    audit, audit_warnings = load_audit(directory)
    reelo, reelo_warnings = load_reelo(directory)
    famepilot, famepilot_warnings = load_famepilot(directory)
    menu_mix, menu_mix_warnings = load_menu_mix(directory)
    item_sales, item_sales_warnings = load_item_sales(directory)
    labels = sorted({store for store, _day in posist})
    # Stores that never appear on the deployment report still have Keka, Reelo,
    # and Famepilot rows. Join those to the same labels the picker shows.
    outside = keka + keka_active + reelo + famepilot
    join_labels = list(labels) + extra_store_labels(outside, labels)
    keka_by_store, keka_unmatched = assign_rows(keka, "posist_store", join_labels)
    keka_active_by_store, keka_active_unmatched = assign_rows(keka_active, "posist_store", join_labels)
    audit_stores = [row for row in audit if not is_brand_audit(row)]
    brand_rows = [row for row in audit if is_brand_audit(row)]
    audit_by_store, audit_unmatched = assign_rows(audit_stores, "store", labels)
    reelo_by_store, reelo_unmatched = assign_rows(reelo, "posist_store", join_labels)
    famepilot_by_store, famepilot_unmatched = assign_rows(famepilot, "posist_store", join_labels)
    menu_mix_by_store = {}
    unmatched_menu_stores = []
    if join_labels or labels:
        seen_menu = set()
        targets = join_labels or labels
        for row in menu_mix:
            label = match_menu_store(row.get("store"), targets)
            if label is None:
                if row.get("store") not in seen_menu:
                    seen_menu.add(row.get("store"))
                    unmatched_menu_stores.append(row)
                continue
            menu_mix_by_store.setdefault(label, []).append(row)
    item_sales_by_store = {}
    if join_labels or labels:
        seen_items = set()
        targets = join_labels or labels
        for row in item_sales:
            label = match_menu_store(row.get("store"), targets)
            if label is None:
                if row.get("store") not in seen_items:
                    seen_items.add(row.get("store"))
                    _warn(
                        item_sales_warnings,
                        f"{ITEM_SALES_FILE} store {row.get('store')!r} does not match one store, so it was not applied.",
                    )
                continue
            item_sales_by_store.setdefault(label, []).append(row)
    if labels or join_labels:
        for row in unmatched_menu_stores:
            _warn(
                menu_mix_warnings,
                f"{MENU_MIX_FILE} store {row.get('store')!r} does not match one store, so it was not applied.",
            )
    if labels:
        for row in keka_unmatched:
            _warn(
                keka_warnings,
                f"{KEKA_FILE} row {row.get('posist_store')!r} does not match one Posist store, so it was not applied.",
            )
        for row in keka_active_unmatched:
            _warn(
                keka_active_warnings,
                f"{KEKA_ACTIVE_FILE} row {row.get('posist_store')!r} does not match one Posist store, so it was not applied.",
            )
        for row in audit_unmatched:
            _warn(
                audit_warnings,
                f"{AUDIT_FILE} row {row.get('store')!r} does not match one Posist store, so it was not applied.",
            )
        for row in reelo_unmatched:
            _warn(
                reelo_warnings,
                f"{REELO_FILE} row {row.get('posist_store')!r} does not match one Posist store, so it was not applied.",
            )
        for row in famepilot_unmatched:
            _warn(
                famepilot_warnings,
                f"{FAMEPILOT_FILE} row {row.get('posist_store')!r} does not match one Posist store, so it was not applied.",
            )
    return {
        "posist": posist,
        "calendar": calendar,
        "keka": keka,
        "keka_by_store": keka_by_store,
        "keka_active": keka_active,
        "keka_active_by_store": keka_active_by_store,
        "audit": audit,
        "audit_by_store": audit_by_store,
        "audit_brand": brand_rows[-1] if brand_rows else None,
        "reelo": reelo,
        "reelo_by_store": reelo_by_store,
        "famepilot": famepilot,
        "famepilot_by_store": famepilot_by_store,
        "menu_mix": menu_mix,
        "menu_mix_by_store": menu_mix_by_store,
        "item_sales": item_sales,
        "item_sales_by_store": item_sales_by_store,
        "warnings": posist_warnings + calendar_warnings + keka_warnings + keka_active_warnings + audit_warnings + reelo_warnings + famepilot_warnings + menu_mix_warnings + item_sales_warnings,
        "directory": directory,
    }


def describe_feed_file(path):
    """Say whether a feed file is missing, empty, or has a real last-updated time.

    A missing or empty file does not get a timestamp. When rows exist, the
    result includes the file's mtime and the newest date column. Callers label
    those two facts separately.
    """
    path = Path(path)
    name = path.name
    if not path.exists():
        return {"state": "missing", "detail": f"{name} is missing.", "saved_at": None, "newest_date": None}
    try:
        saved_at = datetime.fromtimestamp(path.stat().st_mtime, IST)
    except OSError:
        return {"state": "unreadable", "detail": f"{name} could not be read.", "saved_at": None, "newest_date": None}
    warnings = []
    table = _read_dicts(path, warnings)
    if any("not UTF-8" in warning or "could not be read" in warning or "not valid CSV" in warning or "no header" in warning for warning in warnings):
        return {"state": "unreadable", "detail": warnings[0], "saved_at": None, "newest_date": None}
    dates = []
    data_rows = 0
    for raw in table or []:
        data_rows += 1
        day = parse_date(raw.get("date"))
        if day is not None:
            dates.append(day)
    if data_rows == 0:
        return {"state": "empty", "detail": f"{name} is empty.", "saved_at": None, "newest_date": None}
    if not dates:
        return {"state": "undated", "detail": f"{name} has no dated rows.", "saved_at": None, "newest_date": None}
    return {"state": "ready", "detail": "", "saved_at": saved_at, "newest_date": max(dates)}


def describe_saved_file(path):
    """File save time when the feed has rows but no date column.

    Do not invent a newest date. A missing or empty file still has no timestamp.
    """
    path = Path(path)
    name = path.name
    if not path.exists():
        return {"state": "missing", "detail": f"{name} is missing.", "saved_at": None, "newest_date": None}
    try:
        saved_at = datetime.fromtimestamp(path.stat().st_mtime, IST)
    except OSError:
        return {"state": "unreadable", "detail": f"{name} could not be read.", "saved_at": None, "newest_date": None}
    warnings = []
    table = _read_dicts(path, warnings)
    if any("not UTF-8" in warning or "could not be read" in warning or "not valid CSV" in warning or "no header" in warning for warning in warnings):
        return {"state": "unreadable", "detail": warnings[0], "saved_at": None, "newest_date": None}
    if not table:
        return {"state": "empty", "detail": f"{name} is empty.", "saved_at": None, "newest_date": None}
    return {"state": "saved", "detail": "", "saved_at": saved_at, "newest_date": None}


def describe_feeds(directory=None):
    directory = Path(directory) if directory else data_directory()
    return {
        "posist": describe_feed_file(directory / POSIST_FILE),
        "calendar": describe_feed_file(directory / CALENDAR_FILE),
        "reelo": describe_saved_file(directory / REELO_FILE),
        "famepilot": describe_saved_file(directory / FAMEPILOT_FILE),
    }


def store_names_in_feeds(feeds):
    names = set()
    for store, _day in feeds["posist"]:
        names.add(store)
    for store, _day in feeds["calendar"]:
        names.add(store)
    return names
