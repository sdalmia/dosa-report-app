"""Gap rows dropped as CSV files under data/gaps/, one file per bot.

Every *.csv is read. A bad row is logged and skipped. The page never crashes
on a short or odd file. Accounts and people rows are removed here, before
HTML is built, unless the signed-in email is an owner.

A store left off Reelo on purpose is not a gap. That decision lives on the
store master, not in these files.
"""

import csv
import io
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from app.access import can_see_area
from app.store_health.contract import parse_date
from app.store_health.present import format_date
from app.store_master import store_gaps

log = logging.getLogger(__name__)

COLUMNS = (
    "gap_id",
    "area",
    "store",
    "title",
    "why_it_matters",
    "fix",
    "owner",
    "status",
    "due",
    "as_of",
    "source",
)

STATUSES = ("open", "waiting", "fixed")
STATUS_LABELS = {"open": "Open", "waiting": "Waiting", "fixed": "Fixed"}
STATUS_ORDER = {"open": 0, "waiting": 1, "fixed": 2}
THREAT_AREAS = {"threat", "threats", "reputation"}
THREAT_KINDS = {"google", "unverified", "duplicate", "name"}
_THREAT_WORD = re.compile(r"\bthreats?\b", re.IGNORECASE)
_FILE_NAME = re.compile(r"\.(csv|xlsx|xls|json|txt)\b|[/\\]", re.IGNORECASE)


def gaps_directory():
    override = os.getenv("GAPS_DATA_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "data" / "gaps"


def _parse_day(value):
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


def _public_source(source):
    text = str(source or "").strip()
    if not text or _FILE_NAME.search(text):
        return ""
    return text


def _is_threat(area, title, why):
    if str(area or "").strip().casefold() in THREAT_AREAS:
        return True
    return bool(_THREAT_WORD.search(f"{title or ''} {why or ''}"))


def _record(
    gap_id,
    area,
    store,
    title,
    why,
    fix,
    owner,
    status,
    due,
    as_of,
    source,
    threat,
    kind="",
):
    return {
        "gap_id": gap_id,
        "area": area,
        "store": store,
        "title": title,
        "why_it_matters": why,
        "fix": fix,
        "owner": owner or "No owner yet",
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "due": due,
        "due_label": format_date(due) if due else "",
        "as_of": as_of,
        "as_of_label": format_date(as_of) if as_of else "",
        "source": _public_source(source),
        "threat": bool(threat),
        "kind": kind,
    }


def system_gap_records(rows):
    """Listing and delivery gaps from the store master. Reelo is not one of them."""
    records = []
    for row in rows:
        store = row.get("display_name") or row.get("posist_name") or ""
        store_id = row.get("store_id") or store
        for gap in store_gaps(row):
            kind = gap["kind"]
            threat = kind in THREAT_KINDS
            records.append(
                _record(
                    gap_id=f"{store_id}:{kind}",
                    area="reputation" if threat else kind,
                    store=store,
                    title=gap["label"],
                    why=gap["detail"],
                    fix=gap["status"],
                    owner=gap["owner"],
                    status="open",
                    due=None,
                    as_of=None,
                    source="",
                    threat=threat,
                    kind=kind,
                )
            )
    return records


def _parse_file_row(raw, headers, filename, index):
    title = _cell(raw, headers, "title")
    if not title:
        log.warning("gaps file %s row %s has no title, so it was skipped.", filename, index)
        return None
    status = _cell(raw, headers, "status").casefold() or "open"
    if status not in STATUSES:
        log.warning(
            "gaps file %s row %s status %r is not open, waiting, or fixed, so it was skipped.",
            filename,
            index,
            status,
        )
        return None
    area = _cell(raw, headers, "area").casefold() or "general"
    why = _cell(raw, headers, "why_it_matters")
    due_raw = _cell(raw, headers, "due")
    as_of_raw = _cell(raw, headers, "as_of")
    due = _parse_day(due_raw) if due_raw else None
    as_of = _parse_day(as_of_raw) if as_of_raw else None
    if due_raw and due is None:
        log.warning("gaps file %s row %s due %r is not a date, so the date was left blank.", filename, index, due_raw)
    if as_of_raw and as_of is None:
        log.warning("gaps file %s row %s as_of %r is not a date, so the date was left blank.", filename, index, as_of_raw)
    gap_id = _cell(raw, headers, "gap_id") or f"{filename}:{index}"
    return _record(
        gap_id=gap_id,
        area=area,
        store=_cell(raw, headers, "store"),
        title=title,
        why=why,
        fix=_cell(raw, headers, "fix"),
        owner=_cell(raw, headers, "owner"),
        status=status,
        due=due,
        as_of=as_of,
        source=_cell(raw, headers, "source"),
        threat=_is_threat(area, title, why),
        kind=area,
    )


def load_gap_files(directory=None):
    """Every CSV in the gaps folder. A header-only file adds no rows."""
    directory = Path(directory) if directory else gaps_directory()
    rows = []
    if not directory.is_dir():
        return rows
    for path in sorted(item for item in directory.glob("*.csv") if item.is_file()):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            log.warning("gaps file %s could not be read: %s", path.name, exc)
            continue
        if not text.strip():
            continue
        try:
            reader = csv.DictReader(io.StringIO(text))
            fieldnames = reader.fieldnames
            table = list(reader)
        except csv.Error as exc:
            log.warning("gaps file %s is not valid CSV: %s", path.name, exc)
            continue
        headers = _header_map(fieldnames)
        missing = [column for column in COLUMNS if column not in headers]
        if missing:
            log.warning("gaps file %s is missing %s, so it was skipped.", path.name, ", ".join(missing))
            continue
        for index, raw in enumerate(table, start=2):
            if raw is None or not any(str(value or "").strip() for value in raw.values()):
                continue
            try:
                item = _parse_file_row(raw, headers, path.name, index)
            except Exception as exc:
                log.warning("gaps file %s row %s skipped: %s", path.name, index, exc)
                continue
            if item is not None:
                rows.append(item)
    return rows


def visible_gaps(rows, email=None):
    """Drop accounts and people unless this email is an owner."""
    return [row for row in rows if can_see_area(row.get("area"), email)]


def _gap_sort(row):
    return (
        0 if row.get("threat") else 1,
        STATUS_ORDER.get(row.get("status"), 3),
        (row.get("title") or "").casefold(),
        (row.get("store") or "").casefold(),
    )


def group_gaps_by_owner(rows):
    """Owners with a threat come first. Inside a group, threats come first."""
    buckets = {}
    for row in rows:
        buckets.setdefault(row.get("owner") or "No owner yet", []).append(row)
    groups = []
    for owner, items in buckets.items():
        items.sort(key=_gap_sort)
        groups.append(
            {
                "owner": owner,
                "gaps": items,
                "threats": any(item.get("threat") for item in items),
            }
        )
    groups.sort(key=lambda group: (0 if group["threats"] else 1, group["owner"].casefold()))
    return groups


def gap_counts(rows):
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        status = row.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def load_gap_board(master_rows, directory=None, email=None):
    rows = visible_gaps(system_gap_records(master_rows) + load_gap_files(directory), email)
    return {
        "counts": gap_counts(rows),
        "groups": group_gaps_by_owner(rows),
        "gaps": rows,
    }
