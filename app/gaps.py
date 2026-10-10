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
            record = _record(
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
            record["store_ids"] = [store_id] if row.get("store_id") else []
            records.append(record)
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


def recipe_stub_gaps():
    """Recipe looks incomplete, owned by Sailesh. One card per city and dish."""
    from app.menu_costing.catalog import stub_gap_rows
    from app.store_master import get_index

    by_label = {}
    for row in get_index().rows:
        store_id = row.get("store_id") or ""
        for label in (row.get("display_name"), row.get("posist_name")):
            if label and store_id:
                by_label.setdefault(label.casefold(), store_id)
    records = []
    for stub in stub_gap_rows():
        city = stub.get("city") or ""
        item = stub.get("item") or ""
        ids = []
        for name in stub.get("outlet_names") or []:
            store_id = by_label.get((name or "").casefold())
            if store_id and store_id not in ids:
                ids.append(store_id)
        record = _record(
            gap_id=f"recipe-stub:{city}:{item.casefold()}",
            area="procurement",
            store=city,
            title=f"Recipe looks incomplete: {item}",
            why=f"{city}. Stock under-deduction risk for Sailesh. {stub.get('reason') or ''}.",
            fix="Set the full base recipe",
            owner="Sailesh",
            status="open",
            due=None,
            as_of=None,
            source="",
            threat=True,
        )
        record["store_ids"] = ids
        records.append(record)
    return records


def batch_recipe_gaps():
    """Batch items with no recipe, owned by Sailesh. One row per city and item."""
    from app.menu_costing.batches import missing_recipe_rows
    from app.store_master import get_index
    from app.view_filters import CITY_REGION

    records = []
    master = list(get_index().rows)
    for row in missing_recipe_rows():
        city = row.get("city") or ""
        item = row.get("item") or ""
        region = CITY_REGION.get(city, "")
        ids = []
        for store in master:
            if region and (store.get("region") or "") != region:
                continue
            store_id = store.get("store_id") or ""
            if store_id and store_id not in ids:
                ids.append(store_id)
        record = _record(
            gap_id=f"batch-recipe:{city}:{item.casefold()}",
            area="procurement",
            store=city,
            title=f"No batch recipe: {item}",
            why=f"{city}. Recipe coming from Sailesh.",
            fix="Add the batch recipe",
            owner="Sailesh",
            status="open",
            due=None,
            as_of=None,
            source="",
            threat=True,
        )
        record["store_ids"] = ids
        records.append(record)
    return records


def load_gap_board(master_rows, directory=None, email=None):
    rows = system_gap_records(master_rows) + load_gap_files(directory)
    if directory is None:
        rows.extend(recipe_stub_gaps())
        rows.extend(batch_recipe_gaps())
    rows = visible_gaps(rows, email)
    return {
        "counts": gap_counts(rows),
        "groups": group_gaps_by_owner(rows),
        "gaps": rows,
    }


_PLACE_SPLIT = re.compile(r"\s*(?:,|\||\band\b)\s*", re.IGNORECASE)
_REGION_WORDS = {"kolkata": "East", "east": "East", "delhi": "North", "ncr": "North", "north": "North"}


def _is_subsequence(needle, haystack):
    if not needle or len(needle) > len(haystack):
        return False
    index = 0
    for word in haystack:
        if word == needle[index]:
            index += 1
            if index == len(needle):
                return True
    return False


def _row_labels(row):
    labels = [row.get("display_name"), row.get("posist_name"), row.get("store_id")]
    from app.store_master import known_names

    labels.extend(known_names(row.get("notes")))
    return [label for label in labels if label]


def _prefix_of_another(words, rows, own):
    """True when these words are the start of a different outlet's name."""
    if not words:
        return False
    from app.store_master import name_words

    for other in rows:
        if other is own:
            continue
        for label in (other.get("display_name"), other.get("posist_name")):
            other_words = name_words(label)
            if len(other_words) > len(words) and other_words[: len(words)] == tuple(words):
                return True
    return False


def _shared_region(rows):
    regions = {(row.get("region") or "") for row in rows}
    regions.discard("")
    if len(regions) == 1:
        return next(iter(regions))
    return ""


def _match_place(part, index):
    """One outlet, or none when the words fit two outlets.

    A city word such as Delhi is a region, not a list of every store there.
    A short name that starts another outlet, such as Salt Lake, stays unmatched.
    """
    from app.store_master import name_words, normalise_key

    text = (part or "").strip()
    if not text:
        return [], ""
    hit = index.find(text)
    if hit is not None:
        return [hit], ""
    token = normalise_key(text)
    exact = [row for row in index.rows if any(normalise_key(label) == token for label in _row_labels(row))]
    words = name_words(text)
    if len(exact) == 1 and not _prefix_of_another(words, index.rows, exact[0]):
        return exact, ""
    if words and set(words) <= set(_REGION_WORDS):
        region = ""
        for word in words:
            region = _REGION_WORDS.get(word, region)
        return [], region
    if len(words) == 1 and (len(words[0]) < 4 or words[0].isdigit()):
        return [], ""
    hits = []
    for row in index.rows:
        if any(_is_subsequence(words, name_words(label)) for label in _row_labels(row)):
            hits.append(row)
    if len(hits) == 1:
        return hits, ""
    if len(hits) > 1:
        return [], _shared_region(hits)
    if len(exact) > 1:
        return [], _shared_region(exact)
    return [], ""


def gap_places(row, index):
    """Outlets named on a gap, and a region when the text only names a city."""
    pinned = [item for item in (row.get("store_ids") or []) if item]
    if pinned:
        wanted = set(pinned)
        return [item for item in index.rows if item.get("store_id") in wanted], set()
    text = row.get("store") or ""
    parts = [part.strip() for part in _PLACE_SPLIT.split(text) if part and part.strip()]
    outlets = []
    seen = set()
    regions = set()
    for part in parts:
        matched, region = _match_place(part, index)
        for outlet in matched:
            store_id = outlet.get("store_id")
            if store_id in seen:
                continue
            seen.add(store_id)
            outlets.append(outlet)
        if not matched and region:
            regions.add(region)
    if not outlets:
        blob = " ".join(str(row.get(key) or "") for key in ("store", "title", "why_it_matters"))
        from app.store_master import normalise_key

        for word in normalise_key(blob).split():
            region = _REGION_WORDS.get(word)
            if region:
                regions.add(region)
    return outlets, regions


def filter_gaps(rows, filters, index):
    """Keep gaps for the chosen store and city. A date range is left alone.

    A gap with no store is company-wide, so a store or city choice hides it.
    A city named in the title, such as Kolkata, keeps the gap for that city.
    """
    from app.view_filters import city_region

    filters = filters or {}
    store_id = (filters.get("cc_store") or "").strip()
    region = city_region(filters)
    if not store_id and not region:
        return list(rows)
    kept = []
    for row in rows:
        outlets, word_regions = gap_places(row, index)
        if store_id and region:
            if any(item.get("store_id") == store_id and (item.get("region") or "") == region for item in outlets):
                kept.append(row)
            continue
        if store_id:
            if any(item.get("store_id") == store_id for item in outlets):
                kept.append(row)
            continue
        if outlets:
            if any((item.get("region") or "") == region for item in outlets):
                kept.append(row)
        elif region in word_regions:
            kept.append(row)
    return kept
