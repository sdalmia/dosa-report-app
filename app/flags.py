"""Red flags dropped as CSV files under data/flags/.

Every *.csv is read. A bad row is logged and skipped. The page never crashes
on a short or odd file. Accounts and people rows are removed here, before
HTML or JSON is built, unless the signed-in email is an owner.
"""

import csv
import io
import logging
import os
from datetime import datetime
from pathlib import Path

from app.access import can_see_area
from app.store_health.contract import parse_date
from app.store_health.present import business_today, format_date

log = logging.getLogger(__name__)

COLUMNS = ("area", "severity", "title", "detail", "owner", "as_of", "source")
FLAG_MAX_AGE_DAYS = 7

# Known areas first. Any other area, including training, still gets a group.
AREAS_ORDER = (
    "sales",
    "reputation",
    "procurement",
    "people",
    "accounts",
    "tech",
    "marketing",
    "training",
)

AREA_ICONS = {
    "sales": "bi-graph-up-arrow",
    "reputation": "bi-star",
    "procurement": "bi-box-seam",
    "people": "bi-people",
    "accounts": "bi-bank",
    "tech": "bi-cpu",
    "marketing": "bi-megaphone",
    "training": "bi-mortarboard",
}


def flags_directory():
    override = os.getenv("FLAGS_DATA_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "data" / "flags"


def _parse_as_of(value):
    day = parse_date(value)
    if day is not None:
        return day
    text = str(value or "").strip()
    for fmt in ("%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _header_map(fieldnames):
    mapping = {}
    for name in fieldnames or []:
        if name is None:
            continue
        mapping[str(name).strip().lower()] = name
    return mapping


def _cell(raw, headers, column):
    source = headers.get(column)
    if source is None:
        return ""
    value = raw.get(source)
    if value is None:
        return ""
    return str(value).strip()


def _parse_row(raw, headers, filename, index, today):
    area = _cell(raw, headers, "area").casefold()
    severity = _cell(raw, headers, "severity").casefold()
    title = _cell(raw, headers, "title")
    detail = _cell(raw, headers, "detail")
    owner = _cell(raw, headers, "owner")
    source = _cell(raw, headers, "source")
    as_of_raw = _cell(raw, headers, "as_of")
    if not area or not title:
        log.warning(
            "flags file %s row %s has no area or title, so it was skipped.",
            filename,
            index,
        )
        return None
    if severity not in {"red", "amber"}:
        log.warning(
            "flags file %s row %s severity %r is not red or amber, so it was skipped.",
            filename,
            index,
            severity,
        )
        return None
    as_of = _parse_as_of(as_of_raw)
    if as_of is None:
        log.warning(
            "flags file %s row %s as_of %r is not a date, so it was skipped.",
            filename,
            index,
            as_of_raw,
        )
        return None
    age = (today - as_of).days
    if age > FLAG_MAX_AGE_DAYS:
        return None
    return {
        "area": area,
        "label": area[:1].upper() + area[1:],
        "severity": severity,
        "title": title,
        "detail": detail,
        "owner": owner,
        "as_of": as_of,
        "as_of_label": format_date(as_of),
        "source": source,
        "file": filename,
        "icon": AREA_ICONS.get(area, "bi-flag"),
    }


def load_flag_rows(directory=None, today=None):
    """Every CSV in the flags folder, newest red first. Bad rows are dropped."""
    directory = Path(directory) if directory else flags_directory()
    today = today or business_today()
    rows = []
    if not directory.is_dir():
        return rows
    for path in sorted(item for item in directory.glob("*.csv") if item.is_file()):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            log.warning("flags file %s could not be read: %s", path.name, exc)
            continue
        if not text.strip():
            continue
        try:
            reader = csv.DictReader(io.StringIO(text))
            fieldnames = reader.fieldnames
            table = list(reader)
        except csv.Error as exc:
            log.warning("flags file %s is not valid CSV: %s", path.name, exc)
            continue
        headers = _header_map(fieldnames)
        missing = [column for column in COLUMNS if column not in headers]
        if missing:
            log.warning(
                "flags file %s is missing %s, so it was skipped.",
                path.name,
                ", ".join(missing),
            )
            continue
        for index, raw in enumerate(table, start=2):
            if raw is None:
                log.warning("flags file %s row %s was empty, so it was skipped.", path.name, index)
                continue
            try:
                item = _parse_row(raw, headers, path.name, index, today)
            except Exception as exc:  # a stray cell should not take the page down
                log.warning("flags file %s row %s skipped: %s", path.name, index, exc)
                continue
            if item is not None:
                rows.append(item)
    rows.sort(
        key=lambda item: (
            0 if item["severity"] == "red" else 1,
            -item["as_of"].toordinal(),
            item["title"].casefold(),
        )
    )
    return rows


def flag_files_present(directory=None):
    directory = Path(directory) if directory else flags_directory()
    if not directory.is_dir():
        return False
    return any(directory.glob("*.csv"))


def visible_flags(rows, email):
    """Drop accounts and people unless this email is an owner."""
    return [row for row in rows if can_see_area(row["area"], email)]


def flag_public_dict(row):
    return {
        "area": row["area"],
        "severity": row["severity"],
        "title": row["title"],
        "detail": row["detail"],
        "owner": row["owner"],
        "as_of": row["as_of"].isoformat(),
        "source": row["source"],
    }


def group_flags(rows):
    buckets = {}
    for row in rows:
        buckets.setdefault(row["area"], []).append(row)
    groups = []
    seen = set()
    for name in AREAS_ORDER:
        if name in buckets:
            groups.append((name, buckets[name]))
            seen.add(name)
    for name in sorted(set(buckets) - seen):
        groups.append((name, buckets[name]))
    return groups
