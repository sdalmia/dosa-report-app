"""Turn contract rows into display strings. Missing values stay empty strings."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.store_health.contract import (
    CALENDAR_COLUMNS,
    CALENDAR_MONEY,
    CALENDAR_PERCENTS,
    CALENDAR_VALUE_COLUMNS,
    POSIST_COLUMNS,
    POSIST_COUNTS,
    POSIST_MONEY,
    POSIST_PERCENTS,
)
from app.store_health.stores import CATALOGUE, Store, store_from_feed


IST = ZoneInfo("Asia/Kolkata")
MAX_RANGE_DAYS = 93

STATUS_LABELS = {
    "pending": "Pending",
    "actual": "Actual",
    "actual_provisional_eod": "Actual, provisional end of day",
}


def business_today():
    return datetime.now(IST).date()


def group_indian(digits):
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while head:
        parts.append(head[-2:])
        head = head[:-2]
    return ",".join(reversed(parts)) + "," + tail


def format_inr(value):
    negative = float(value) < 0
    cents = int(round(abs(float(value)) * 100))
    whole, frac = divmod(cents, 100)
    body = group_indian(str(whole))
    if frac:
        body = f"{body}.{frac:02d}"
    sign = "-" if negative else ""
    return f"{sign}₹{body}"


def format_lakhs(value):
    """A *_L column is already expressed in lakhs. Do not convert it."""
    negative = float(value) < 0
    number = abs(float(value))
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    sign = "-" if negative else ""
    return f"{sign}{text} L"


def format_money(value, field_name):
    if value is None:
        return ""
    if field_name.endswith("_L"):
        return format_lakhs(value)
    return format_inr(value)


def format_count(value):
    if value is None:
        return ""
    number = float(value)
    if number.is_integer():
        sign = "-" if number < 0 else ""
        return sign + group_indian(str(abs(int(number))))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def format_pct(value):
    if value is None:
        return ""
    hundredths = int(round(float(value) * 100))
    if hundredths == 0:
        return "0%"
    sign = "+" if hundredths > 0 else "-"
    whole, frac = divmod(abs(hundredths), 100)
    if frac == 0:
        body = str(whole)
    else:
        body = f"{whole}.{frac:02d}".rstrip("0")
    return f"{sign}{body}%"


def format_date(value):
    if not isinstance(value, date):
        return ""
    return f"{value.day} {value.strftime('%b %Y')}"


def _posist_field(row, field):
    if row is None:
        return ""
    value = row.get(field)
    if field in POSIST_MONEY or field.endswith("_L"):
        return format_money(value, field)
    if field in POSIST_COUNTS:
        return format_count(value)
    if field in POSIST_PERCENTS:
        return format_pct(value)
    if value is None:
        return ""
    return str(value)


def posist_for_day(feeds, store, day):
    display = {field: "" for field in POSIST_COLUMNS if field not in {"store", "date"}}
    display["source_label"] = ""
    display["provisional_label"] = ""
    if store is None or day is None:
        return {"has_row": False, "fields": display}
    row = _row_for_store(feeds["posist"], store, day)
    if row is None:
        return {"has_row": False, "fields": display}
    for field in display:
        if field in {"source_label", "provisional_label"}:
            continue
        display[field] = _posist_field(row, field)
    source = row.get("source")
    if source == "live":
        display["source_label"] = "Live"
    elif source == "historical":
        display["source_label"] = "Historical"
    elif source:
        display["source_label"] = str(source)
    provisional = row.get("provisional")
    if provisional is True:
        display["provisional_label"] = "Provisional"
    elif provisional is False:
        display["provisional_label"] = "Not provisional"
    return {"has_row": True, "fields": display}


def _row_for_store(table, store, day):
    for key in store.match_keys():
        row = table.get((key, day))
        if row is not None:
            return row
    return None


def _calendar_field(row, field):
    if row is None:
        return ""
    value = row.get(field)
    if field in CALENDAR_MONEY or field.endswith("_L"):
        return format_money(value, field)
    if field in CALENDAR_PERCENTS:
        return format_pct(value)
    if field == "status":
        if not value:
            return ""
        return STATUS_LABELS.get(value, str(value))
    if value is None:
        return ""
    return str(value)


def calendar_days(feeds, store, start, end):
    if start is None or end is None:
        return []
    days = []
    cursor = start
    while cursor <= end:
        row = _row_for_store(feeds["calendar"], store, cursor) if store else None
        fields = {field: _calendar_field(row, field) for field in CALENDAR_VALUE_COLUMNS if field != "date"}
        figure_fields = ("pred_low", "pred_high", "pred_mid", "actual_net")
        has_figure = any(fields[name] for name in figure_fields)
        days.append(
            {
                "date": cursor,
                "iso": cursor.isoformat(),
                "label": format_date(cursor),
                "chrome_weekday": cursor.strftime("%a"),
                "fields": fields,
                "has_figure": has_figure,
                "variance_negative": bool(row and row.get("variance_vs_mid") is not None and row["variance_vs_mid"] < 0),
                "variance_positive": bool(row and row.get("variance_vs_mid") is not None and row["variance_vs_mid"] > 0),
            }
        )
        cursor += timedelta(days=1)
    return days


def calendar_weeks(days):
    if not days:
        return []
    cells = [None] * days[0]["date"].weekday()
    cells.extend(days)
    while len(cells) % 7:
        cells.append(None)
    return [cells[index : index + 7] for index in range(0, len(cells), 7)]


def _free_id(candidate, ids):
    if candidate.id not in ids:
        return candidate
    suffix = 2
    while True:
        new_id = f"{candidate.id}-{suffix}"[:80]
        if new_id not in ids:
            return Store(
                id=new_id,
                public_name=candidate.public_name,
                region="",
                format="",
                posist_deployment_name=candidate.posist_deployment_name,
                deployment_code=candidate.deployment_code,
                extra_keys=candidate.extra_keys,
            )
        suffix += 1


def list_stores(feeds):
    stores = list(CATALOGUE)
    known = set()
    for store in stores:
        known.update(store.match_keys())
    seen = set()
    for table in (feeds["posist"], feeds["calendar"]):
        for store_name, _day in table:
            if store_name in known or store_name in seen:
                continue
            seen.add(store_name)
            extra = _free_id(store_from_feed(store_name), {store.id for store in stores})
            stores.append(extra)
            known.update(extra.match_keys())
    return stores


def grouped_stores(stores):
    groups = []
    buckets = {}
    for store in stores:
        label = store.format or "From the sales files"
        if label not in buckets:
            buckets[label] = []
            groups.append((label, buckets[label]))
        buckets[label].append(store)
    return groups


def resolve_store(stores, token):
    if not token:
        return None
    wanted = token.strip()
    for store in stores:
        if wanted == store.id or wanted in store.match_keys():
            return store
    return None


def parse_range(args, today):
    raw_start = (args.get("start") or "").strip()
    raw_end = (args.get("end") or "").strip()
    raw_day = (args.get("day") or "").strip()
    error = None
    start = end = None
    if not raw_start and not raw_end:
        end = today
        start = today - timedelta(days=13)
        raw_start = start.isoformat()
        raw_end = end.isoformat()
    else:
        try:
            start = date.fromisoformat(raw_start)
            end = date.fromisoformat(raw_end)
        except ValueError:
            error = "Enter a start date and an end date."
            start = end = None
        else:
            if end < start:
                error = "The end date is before the start date."
                start = end = None
            elif (end - start).days + 1 > MAX_RANGE_DAYS:
                error = f"Choose {MAX_RANGE_DAYS} days or fewer."
                start = end = None
    day = None
    if raw_day:
        try:
            day = date.fromisoformat(raw_day)
        except ValueError:
            error = error or "The Posist day is not a valid date."
            raw_day = ""
    elif end is not None:
        day = end
        raw_day = end.isoformat()
    return {
        "start": start,
        "end": end,
        "day": day,
        "error": error,
        "start_input": raw_start,
        "end_input": raw_end,
        "day_input": raw_day,
    }


def build_view(feeds, store, selection, today):
    days = calendar_days(feeds, store, selection["start"], selection["end"])
    filled = sum(1 for day in days if day["fields"]["actual_net"])
    predicted = sum(1 for day in days if day["fields"]["pred_mid"] or day["fields"]["pred_low"] or day["fields"]["pred_high"])
    return {
        "posist": posist_for_day(feeds, store, selection["day"]),
        "days": days,
        "weeks": calendar_weeks(days),
        "filled_actual_days": filled,
        "filled_prediction_days": predicted,
        "day_count": len(days),
        "today_iso": today.isoformat() if today else "",
        "posist_columns": POSIST_COLUMNS,
        "calendar_columns": CALENDAR_COLUMNS,
    }
