"""Famepilot emergency-keyword cases from alert emails.

tickets.csv holds one row per alert. tickets_source_detail.csv adds the
type (review or complaint), the customer's post time, and whether the row
was read from the email body. status, owner, and resolved_at are blank
because the emails do not include them. Every such case is listed as Open.
Age uses the post time when it is present, otherwise the alert time.
The over-24-hours flag is that age. It is not a console resolution status.
"""

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.menu_ops.formatutil import format_hours, format_stamp
from app.menu_ops.loader import _blank, famepilot_directory, file_stamp, filename_date, normalise_header

IST = ZoneInfo("Asia/Kolkata")
TICKET_COLUMNS = (
    "date_time",
    "store",
    "platform",
    "rating",
    "keyword",
    "customer",
    "status",
    "owner",
    "resolved_at",
)
DETAIL_COLUMNS = (
    "date_time",
    "store",
    "type",
    "review_time_ist",
    "message_id",
    "detail_source",
    "dup_message_ids",
)
RESOLVED_STATUSES = {"resolved", "closed", "close", "done", "completed"}
OPEN_NOTE = (
    "Every case is listed as Open. The alert emails do not include a status, an owner, or a resolved time. "
    "Over 24 hours is the age of the case. A resolved or open status from the review console is not in yet."
)


def ticket_directory():
    return famepilot_directory()


def build_tickets(directory=None, now=None, store="", keyword=""):
    directory = directory or ticket_directory()
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    loaded = load_cases(directory, now)
    cases = loaded["cases"]
    if store:
        cases = [case for case in cases if case["store"] == store]
    if keyword:
        wanted = keyword.casefold()
        cases = [case for case in cases if case["keyword"].casefold() == wanted]
    return {
        "present": loaded["present"],
        "file": loaded["file"],
        "detail_file": loaded["detail_file"],
        "columns": loaded["columns"],
        "detail_columns": loaded["detail_columns"],
        "warnings": loaded["warnings"],
        "open_note": OPEN_NOTE,
        "expected_columns": TICKET_COLUMNS,
        "expected_detail_columns": DETAIL_COLUMNS,
        "cases": [_present_case(case) for case in cases],
        "hotspots": _hotspots(cases),
        "keywords": _keyword_groups(cases),
        "stores": _store_groups(cases),
        "store_names": sorted({case["store"] for case in loaded["cases"]}),
        "keyword_names": _keyword_names(loaded["cases"]),
        "store": store,
        "keyword": keyword,
        "counts": _counts(cases),
        "rating_note": _rating_note(cases),
    }


def load_cases(directory, now):
    directory = Path(directory)
    result = {
        "present": False,
        "file": "",
        "detail_file": "",
        "columns": [],
        "detail_columns": [],
        "cases": [],
        "warnings": [],
    }
    if not directory.exists():
        result["warnings"].append(_missing_tickets())
        return result
    paths = [
        path
        for path in sorted(directory.glob("tickets*.csv"))
        if not path.name.lower().startswith("tickets_source_detail")
    ]
    if not paths:
        result["warnings"].append(_missing_tickets())
        return result
    dated = [path for path in paths if filename_date(path.name)]
    path = max(dated, key=file_stamp) if dated else paths[-1]
    if len(paths) > 1 and not dated:
        result["warnings"].append(
            "More than one undated tickets file is on file. Loaded " + path.name + " and left the others unused."
        )
    detail_paths = sorted(directory.glob("tickets_source_detail*.csv"), key=file_stamp)
    detail_path = detail_paths[-1] if detail_paths else None
    ticket_rows, ticket_columns = _read_dicts(path)
    result["file"] = path.name
    result["columns"] = ticket_columns
    missing = [name for name in ("date_time", "store", "keyword") if name not in ticket_columns]
    if missing:
        result["warnings"].append(f"{path.name} is missing {', '.join(missing)}, so tickets were not loaded.")
        return result
    details = []
    if detail_path:
        details, detail_columns = _read_dicts(detail_path)
        result["detail_file"] = detail_path.name
        result["detail_columns"] = detail_columns
    paired = _pair(ticket_rows, details)
    cases = []
    for ticket, detail in paired:
        cases.append(_case(ticket, detail, now))
    result["cases"] = cases
    result["present"] = True
    return result


def _missing_tickets():
    return (
        "Famepilot tickets are not on file. Expected data/famepilot/tickets.csv with columns "
        + ", ".join(TICKET_COLUMNS)
        + ", and data/famepilot/tickets_source_detail.csv with columns "
        + ", ".join(DETAIL_COLUMNS)
        + "."
    )


_HEADER_FIELDS = {
    "date time": "date_time",
    "store": "store",
    "platform": "platform",
    "rating": "rating",
    "keyword": "keyword",
    "customer": "customer",
    "status": "status",
    "owner": "owner",
    "resolved at": "resolved_at",
    "type": "type",
    "review time ist": "review_time_ist",
    "message id": "message_id",
    "detail source": "detail_source",
    "dup message ids": "dup_message_ids",
}


def _read_dicts(path):
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        index = {}
        for name in reader.fieldnames or []:
            field = _HEADER_FIELDS.get(normalise_header(name))
            if field and field not in index:
                index[field] = name
        rows = []
        for raw in reader:
            if raw is None or all(_blank(value) for value in raw.values()):
                continue
            rows.append({field: raw.get(source) for field, source in index.items()})
        return rows, list(index)


def _pair_key(row):
    return ((row.get("date_time") or "").strip(), (row.get("store") or "").strip())


def _pair(tickets, details):
    if details and len(tickets) == len(details) and all(_pair_key(left) == _pair_key(right) for left, right in zip(tickets, details)):
        return list(zip(tickets, details))
    buckets = defaultdict(list)
    for detail in details:
        buckets[_pair_key(detail)].append(detail)
    used = defaultdict(int)
    paired = []
    for ticket in tickets:
        key = _pair_key(ticket)
        index = used[key]
        group = buckets.get(key) or []
        detail = group[index] if index < len(group) else None
        used[key] += 1
        paired.append((ticket, detail))
    return paired


def _parse_ist(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _text(row, field):
    if row is None or field not in row or _blank(row.get(field)):
        return ""
    return str(row.get(field)).strip()


def _case(ticket, detail, now):
    status = _text(ticket, "status")
    post = _parse_ist(detail.get("review_time_ist")) if detail else None
    alert = _parse_ist(ticket.get("date_time"))
    resolved_at = _parse_ist(ticket.get("resolved_at"))
    if post is not None:
        start = post
        basis = "since post"
    elif alert is not None:
        start = alert
        basis = "since alert"
    else:
        start = None
        basis = ""
    end = resolved_at or now
    age = None
    if start is not None and end is not None and end >= start:
        age = (end - start).total_seconds() / 3600.0
    resolved = status.casefold() in RESOLVED_STATUSES
    if not status:
        tracker = "Open"
    else:
        tracker = status
    if age is None:
        flag = None
    elif resolved:
        flag = False
    else:
        flag = age > 24
    rating_text = _text(ticket, "rating")
    return {
        "date_time": alert,
        "date_time_text": _text(ticket, "date_time"),
        "post_time": post,
        "store": _text(ticket, "store"),
        "platform": _text(ticket, "platform"),
        "rating": rating_text,
        "keyword": _text(ticket, "keyword"),
        "customer": _text(ticket, "customer"),
        "status": status,
        "owner": _text(ticket, "owner"),
        "resolved_at": _text(ticket, "resolved_at"),
        "tracker": tracker,
        "type": _text(detail, "type") if detail else "",
        "detail_source": _text(detail, "detail_source") if detail else "",
        "message_id": _text(detail, "message_id") if detail else "",
        "dup_message_ids": _text(detail, "dup_message_ids") if detail else "",
        "age_hours": age,
        "age_basis": basis,
        "over_24": flag,
        "start": start,
    }


def _present_case(case):
    return {
        "when": format_stamp(case["post_time"] or case["date_time"]) or case["date_time_text"],
        "alert": format_stamp(case["date_time"]) or case["date_time_text"],
        "post": format_stamp(case["post_time"]),
        "store": case["store"],
        "platform": case["platform"],
        "rating": case["rating"],
        "keyword": case["keyword"],
        "customer": case["customer"],
        "status": case["status"],
        "owner": case["owner"],
        "resolved_at": case["resolved_at"],
        "tracker": case["tracker"],
        "type": case["type"],
        "detail_source": case["detail_source"],
        "message_id": case["message_id"],
        "age": format_hours(case["age_hours"]),
        "age_basis": case["age_basis"],
        "over_24": case["over_24"],
        "over_24_label": {True: "Yes", False: "No"}.get(case["over_24"], ""),
    }


def _hotspots(cases):
    grouped = defaultdict(list)
    for case in cases:
        grouped[case["store"]].append(case)
    rows = []
    for store, group in grouped.items():
        if len(group) < 2:
            continue
        keywords = sorted({case["keyword"] for case in group if case["keyword"]})
        rows.append(
            {
                "store": store,
                "count": len(group),
                "keywords": keywords,
                "over_24": sum(1 for case in group if case["over_24"] is True),
            }
        )
    rows.sort(key=lambda row: (-row["count"], row["store"].casefold()))
    return rows


def _keyword_groups(cases):
    grouped = defaultdict(list)
    for case in cases:
        grouped[case["keyword"] or ""].append(case)
    rows = []
    for keyword, group in grouped.items():
        rows.append(
            {
                "keyword": keyword,
                "count": len(group),
                "stores": len({case["store"] for case in group}),
                "over_24": sum(1 for case in group if case["over_24"] is True),
            }
        )
    rows.sort(key=lambda row: (-row["count"], row["keyword"].casefold()))
    return rows


def _store_groups(cases):
    grouped = defaultdict(list)
    for case in cases:
        grouped[case["store"]].append(case)
    rows = []
    for store, group in grouped.items():
        ordered = sorted(group, key=lambda case: case["start"] or datetime.min.replace(tzinfo=IST), reverse=True)
        keywords = _keyword_groups(group)
        rows.append(
            {
                "store": store,
                "count": len(group),
                "keywords": keywords,
                "cases": [_present_case(case) for case in ordered],
            }
        )
    rows.sort(key=lambda row: (-row["count"], row["store"].casefold()))
    return rows


def _keyword_names(cases):
    return sorted({case["keyword"] for case in cases if case["keyword"]}, key=str.casefold)


def _counts(cases):
    return {
        "cases": len(cases),
        "stores": len({case["store"] for case in cases}),
        "over_24": sum(1 for case in cases if case["over_24"] is True),
        "within_24": sum(1 for case in cases if case["over_24"] is False),
        "age_blank": sum(1 for case in cases if case["over_24"] is None),
        "open": sum(1 for case in cases if case["tracker"] == "Open" and not case["status"]),
    }


def _rating_note(cases):
    typed = [case for case in cases if case["type"]]
    if not typed:
        return ""
    complaints = [case for case in typed if case["type"].casefold() == "complaint"]
    reviews = [case for case in typed if case["type"].casefold() == "review"]
    if complaints and reviews and all(not case["rating"] for case in complaints) and all(case["rating"] for case in reviews):
        return "Rating is on reviews. Complaints have no rating."
    return ""
