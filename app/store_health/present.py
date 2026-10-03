"""Turn contract rows into display strings. Missing values stay empty strings."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.store_health.contract import (
    AUDIT_COLUMNS,
    AUDIT_FILE,
    FAMEPILOT_COLUMNS,
    FAMEPILOT_FILE,
    CALENDAR_COLUMNS,
    CALENDAR_MONEY,
    CALENDAR_PERCENTS,
    CALENDAR_VALUE_COLUMNS,
    KEKA_COLUMNS,
    KEKA_FILE,
    REELO_COLUMNS,
    REELO_FILE,
    POSIST_COLUMNS,
    POSIST_COUNTS,
    POSIST_MONEY,
    POSIST_PERCENTS,
    describe_feeds,
    parse_number,
)
from app.store_health.stores import Store, extra_store_labels, store_from_label


IST = ZoneInfo("Asia/Kolkata")
MAX_RANGE_DAYS = 93

STATUS_LABELS = {
    "pending": "Pending",
    "actual": "Actual",
    "actual_provisional_eod": "Actual, provisional end of day",
    "share_of_network_band": "Share of the network band",
    "not_on_deployment_report": "Not on the deployment report",
}
CALENDAR_SHARE_LABEL = (
    "Low, mid, and high are this store's share of the network judgment band, not a separate model."
)
# Same border class for a tier on every store. Colour is a border, not a cell fill.
TIER_BORDER_CLASS = {
    "Weather caution": "tier-weather-caution",
    "Puja / festive": "tier-puja-festive",
    "Holiday": "tier-holiday",
    "Weekend": "tier-weekend",
    "Working weekday": "tier-working-weekday",
}

KEKA_CAVEAT = (
    "Headcount is registered employees, not people on shift. "
    "Primary lead is the largest reporting line, not a confirmed single store manager."
)
REELO_PHONE_CAVEAT = "Phone capture is valid visits / (valid + blocked) x 100."
REELO_WINDOW = "Last 30 Days, 03 Sep 2026 to 03 Oct 2026."
FAMEPILOT_WINDOW = (
    "Past 30 days preset. The dates printed on screen were 26 Sep 26 - 02 Oct 26 (7 days). "
    "Those printed dates are not a verified 30-day range."
)
SALT_LAKE_FAMEPILOT_LOCATION = "01/0002 / Dosa Coffee- Saltlake Sec 3"
SALT_LAKE_FAMEPILOT_NOTE = 'Matched "01/0002 / Dosa Coffee- Saltlake Sec 3" by code 0002.'


def business_today():
    return datetime.now(IST).date()


def format_ist(value):
    if value is None:
        return ""
    local = value.astimezone(IST)
    hour = int(local.strftime("%I"))
    minute = local.strftime("%M")
    ampm = local.strftime("%p").lower()
    return f"{local.day} {local.strftime('%b %Y')}, {hour}:{minute} {ampm} IST"


def present_freshness(status):
    if status["state"] == "saved":
        return {
            "state": "saved",
            "detail": "",
            "saved_at": format_ist(status["saved_at"]),
            "newest_date": "",
        }
    if status["state"] != "ready":
        return {
            "state": status["state"],
            "detail": status["detail"],
            "saved_at": "",
            "newest_date": "",
        }
    return {
        "state": "ready",
        "detail": "",
        "saved_at": format_ist(status["saved_at"]),
        "newest_date": format_date(status["newest_date"]),
    }


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


def _sum_present(rows, field, kind):
    """Sum cells that exist. A blank cell is not zero, and an all-blank column stays blank."""
    values = [row.get(field) for row in rows if row.get(field) is not None]
    if not values:
        return None
    if kind == "money":
        cents = 0
        for value in values:
            cents += int(round(float(value) * 100))
        return cents / 100.0
    total = 0
    for value in values:
        number = float(value)
        if not number.is_integer():
            return sum(float(item) for item in values)
        total += int(number)
    return total


def _window_bounds(feeds):
    days = [day for (_store, day) in feeds["posist"]]
    if not days:
        return None, None
    return min(days), max(days)


def _dates_in_window(start, end):
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _window_apb(gross, bills):
    """Window APB is summed gross divided by summed bills.

    The daily apb column is that day's gross divided by that day's bills.
    Averaging those days is a different number, so the window does not use it.
    No bills means there is no APB. Do not invent one.
    """
    if gross is None or bills is None or bills == 0:
        return None
    return float(gross) / float(bills)


def posist_window(feeds, store):
    """One total per store across the dates that store actually has."""
    display = {field: "" for field in POSIST_COLUMNS if field not in {"store", "date"}}
    display["source_label"] = ""
    display["provisional_label"] = ""
    start, end = _window_bounds(feeds)
    window_label = ""
    if start is not None and end is not None:
        window_label = f"{format_date(start)} through {format_date(end)}"
    result = {
        "has_row": False,
        "not_on_report": False,
        "window_label": window_label,
        "days_summed": "",
        "missing_label": "",
        "fields": display,
    }
    if store is None:
        return result
    rows = []
    for (store_name, _day), row in feeds["posist"].items():
        if store_name in store.match_keys():
            rows.append(row)
    if not rows:
        result["not_on_report"] = True
        return result
    result["has_row"] = True
    summed = {
        "net": _sum_present(rows, "net", "money"),
        "gross": _sum_present(rows, "gross", "money"),
        "bills": _sum_present(rows, "bills", "count"),
        "unsettled_bills": _sum_present(rows, "unsettled_bills", "count"),
        "unsettled_amount": _sum_present(rows, "unsettled_amount", "money"),
        "void_bills": _sum_present(rows, "void_bills", "count"),
    }
    for field, value in summed.items():
        display[field] = _posist_field({field: value}, field)
    display["apb"] = _posist_field({"apb": _window_apb(summed["gross"], summed["bills"])}, "apb")
    store_days = sorted({row["date"] for row in rows})
    result["days_summed"] = str(len(store_days))
    if start is not None and end is not None:
        missing = [day for day in _dates_in_window(start, end) if day not in set(store_days)]
        if missing:
            listed = ", ".join(format_date(day) for day in missing)
            result["missing_label"] = f"Not a full window. Missing {listed}."
    return result


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


def _posist_daily_actual(row):
    """Figure to show as Actual Net when the calendar file has none.

    Use Posist net when that cell has a number, including a real zero.
    The shipped drop leaves net blank and keeps the day's revenue in gross,
    so gross is the on-file figure only in that case. Never invent a prediction.
    """
    if row is None:
        return None, ""
    if row.get("net") is not None:
        return row.get("net"), "posist_net"
    if row.get("gross") is not None:
        return row.get("gross"), "posist_gross"
    return None, ""


def calendar_days(feeds, store, start, end):
    if start is None or end is None:
        return []
    days = []
    cursor = start
    while cursor <= end:
        row = _row_for_store(feeds["calendar"], store, cursor) if store else None
        fields = {field: _calendar_field(row, field) for field in CALENDAR_VALUE_COLUMNS if field != "date"}
        if row is not None and row.get("actual_net") is not None:
            actual_source = "calendar"
        else:
            posist_row = _row_for_store(feeds["posist"], store, cursor) if store else None
            amount, actual_source = _posist_daily_actual(posist_row)
            if actual_source:
                fields["actual_net"] = format_money(amount, "actual_net")
            else:
                actual_source = ""
        figure_fields = ("pred_low", "pred_high", "pred_mid", "actual_net")
        has_figure = any(fields[name] for name in figure_fields)
        tier = row.get("tier") if row else ""
        days.append(
            {
                "date": cursor,
                "iso": cursor.isoformat(),
                "label": format_date(cursor),
                "chrome_weekday": cursor.strftime("%a"),
                "tier_class": TIER_BORDER_CLASS.get(tier or "", ""),
                "fields": fields,
                "has_figure": has_figure,
                "actual_source": actual_source,
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


def _with_free_id(candidate, ids):
    if candidate.id not in ids:
        return candidate
    suffix = 2
    while True:
        new_id = f"{candidate.id}-{suffix}"[:80]
        if new_id not in ids:
            return Store(id=new_id, label=candidate.label, region=candidate.region)
        suffix += 1


def list_stores(feeds):
    """Picker entries are the exact store cells in posist_daily.csv.

    A store that is on Keka, Reelo, or Famepilot but missing from the Posist
    report stays in the list under the exact label from those files.
    """
    latest = {}
    for (store_name, day), row in feeds["posist"].items():
        current = latest.get(store_name)
        if current is None or day >= current[0]:
            region = row.get("region") or ""
            latest[store_name] = (day, region.strip() if isinstance(region, str) else "")
    stores = []
    used_ids = set()
    for store_name in sorted(latest, key=str.casefold):
        _day, region = latest[store_name]
        store = _with_free_id(store_from_label(store_name, region), used_ids)
        used_ids.add(store.id)
        stores.append(store)
    outside_rows = (feeds.get("keka") or []) + (feeds.get("reelo") or []) + (feeds.get("famepilot") or [])
    for store_name in extra_store_labels(outside_rows, list(latest)):
        store = _with_free_id(store_from_label(store_name, ""), used_ids)
        used_ids.add(store.id)
        stores.append(store)
    return stores


def grouped_stores(stores):
    buckets = {}
    for store in stores:
        buckets.setdefault(store.region or "", []).append(store)
    for items in buckets.values():
        items.sort(key=lambda store: store.label.casefold())
    groups = []
    for name in ("East", "North"):
        if name in buckets:
            groups.append((name, buckets.pop(name)))
    for name in sorted(key for key in buckets if key):
        groups.append((name, buckets[name]))
    if "" in buckets:
        groups.append(("Region not in the file", buckets[""]))
    return groups


def resolve_store(stores, token):
    if not token:
        return None
    wanted = token.strip()
    for store in stores:
        if wanted == store.id or wanted in store.match_keys():
            return store
    return None


def calendar_bounds(feeds):
    """First and last dates in the store calendar, when the file has any."""
    days = [day for (_store, day) in feeds.get("calendar") or {}]
    if not days:
        return None
    return min(days), max(days)


def parse_range(args, today, default_span=None):
    raw_start = (args.get("start") or "").strip()
    raw_end = (args.get("end") or "").strip()
    raw_day = (args.get("day") or "").strip()
    error = None
    start = end = None
    if not raw_start and not raw_end:
        if (
            default_span
            and default_span[0]
            and default_span[1]
            and (default_span[1] - default_span[0]).days + 1 <= MAX_RANGE_DAYS
        ):
            start, end = default_span
        else:
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
        if start is not None and start <= today <= end:
            day = today
        else:
            day = end
        raw_day = day.isoformat()
    return {
        "start": start,
        "end": end,
        "day": day,
        "error": error,
        "start_input": raw_start,
        "end_input": raw_end,
        "day_input": raw_day,
    }


def _file_state(directory, filename, rows):
    if not (directory / filename).exists():
        return "missing"
    if not rows:
        return "empty"
    return "ready"


def _text(row, field):
    if row is None:
        return ""
    value = row.get(field)
    if value is None:
        return ""
    return str(value).strip()


def present_keka(feeds, store):
    row = feeds["keka_by_store"].get(store.label) if store else None
    status = _text(row, "match_status")
    no_match = status.casefold() == "no keka match"
    headcount = ""
    primary = ""
    location = ""
    other = ""
    note = ""
    if row is not None and not no_match:
        raw_headcount = _text(row, "headcount")
        if parse_number(raw_headcount) is not None:
            headcount = raw_headcount
        raw_primary = _text(row, "primary_lead")
        if raw_primary.casefold() != "no keka match":
            primary = raw_primary
        raw_location = _text(row, "keka_location")
        if raw_location.casefold() != "no keka location":
            location = raw_location
        other = _text(row, "other_leads")
        note = _text(row, "note")
    return {
        "state": _file_state(feeds["directory"], KEKA_FILE, feeds["keka"]),
        "caveat": KEKA_CAVEAT,
        "has_row": row is not None,
        "no_match": no_match,
        "fields": {
            "keka_location": location,
            "headcount": headcount,
            "primary_lead": primary,
            "other_leads": other,
            "match_status": status,
            "keka_note": note,
        },
    }


def _audit_display(row, prefix):
    mapping = (
        ("period", "period"),
        ("avg_score", "avg"),
        ("weekday_score", "weekday"),
        ("weekend_score", "weekend"),
        ("note", "note"),
        ("status", "status"),
    )
    return {f"{prefix}_{name}": _text(row, source) for source, name in mapping}


def present_audit(feeds, store):
    row = feeds["audit_by_store"].get(store.label) if store else None
    brand = feeds.get("audit_brand")
    fields = {}
    fields.update(_audit_display(row, "audit"))
    fields.update(_audit_display(brand, "brand"))
    return {
        "state": _file_state(feeds["directory"], AUDIT_FILE, feeds["audit"]),
        "has_row": row is not None,
        "has_brand": brand is not None,
        "fields": fields,
    }


_REELO_MONEY = {
    "redemption_revenue_inr",
    "avg_revenue_per_redemption_inr",
    "sales_total_inr_last30d",
}


def _reelo_value(row, field):
    raw = _text(row, field)
    if raw.casefold() == "not in reelo":
        return ""
    if field in _REELO_MONEY:
        number = parse_number(raw)
        if number is None:
            return ""
        return format_money(number, field)
    if field == "phone_capture_pct":
        if not raw or parse_number(raw) is None:
            return ""
        if raw.endswith("%"):
            return raw
        return f"{raw}%"
    return raw


def present_reelo(feeds, store):
    row = feeds["reelo_by_store"].get(store.label) if store else None
    status = _text(row, "match_status")
    not_in = status.casefold() == "not in reelo"
    fields = {
        "reelo_store": _text(row, "reelo_store"),
        "reelo_date_range": _text(row, "date_range"),
        "reelo_match_status": status,
        "times_redeemed": _reelo_value(row, "times_rewards_redeemed"),
        "redemption_rate": _reelo_value(row, "redemption_rate"),
        "redemption_revenue": _reelo_value(row, "redemption_revenue_inr"),
        "avg_redemption_revenue": _reelo_value(row, "avg_revenue_per_redemption_inr"),
        "points_issued": _reelo_value(row, "points_issued"),
        "sales_total": _reelo_value(row, "sales_total_inr_last30d"),
        "visits": _reelo_value(row, "visits_last30d"),
        "phones_valid": _reelo_value(row, "phones_valid_visits"),
        "phones_blocked": _reelo_value(row, "phones_blocked_visits"),
        "phone_capture": _reelo_value(row, "phone_capture_pct"),
        "customers_with_purchase": _reelo_value(row, "customers_with_purchase"),
        "active_customers": _reelo_value(row, "active_customers"),
        "inactive_customers": _reelo_value(row, "inactive_customers"),
        "reelo_note": _text(row, "note"),
    }
    return {
        "state": _file_state(feeds["directory"], REELO_FILE, feeds["reelo"]),
        "phone_caveat": REELO_PHONE_CAVEAT,
        "window": REELO_WINDOW,
        "has_row": row is not None,
        "not_in_reelo": not_in,
        "fields": fields,
    }


def present_famepilot(feeds, store):
    row = feeds["famepilot_by_store"].get(store.label) if store else None
    location = _text(row, "famepilot_location")
    no_location = row is not None and not location
    note = ""
    if location == SALT_LAKE_FAMEPILOT_LOCATION:
        note = SALT_LAKE_FAMEPILOT_NOTE
    fields = {
        "famepilot_location": location,
        "rating": "" if no_location else _text(row, "rating"),
        "review_count": "" if no_location else _text(row, "review_count"),
        "main_threat": "" if no_location else _text(row, "main_threat"),
        "private_rating": "" if no_location else _text(row, "private_rating"),
        "private_review_count": "" if no_location else _text(row, "private_review_count"),
        "overall_reviews": "" if no_location else _text(row, "overall_reviews"),
        "famepilot_note": note,
    }
    return {
        "state": _file_state(feeds["directory"], FAMEPILOT_FILE, feeds["famepilot"]),
        "window": FAMEPILOT_WINDOW,
        "has_row": row is not None,
        "no_location": no_location,
        "fields": fields,
    }


def calendar_story(feeds, store):
    """How to label this store's calendar bands. Does not invent a figure."""
    share = False
    absent_note = ""
    if store is not None:
        for (name, _day), row in feeds["calendar"].items():
            if name not in store.match_keys():
                continue
            if row.get("status") == "share_of_network_band":
                share = True
            elif row.get("status") == "not_on_deployment_report" and row.get("notes") and not absent_note:
                absent_note = row["notes"]
    return {
        "share_label": CALENDAR_SHARE_LABEL if share else "",
        "absent_note": "" if share else absent_note,
    }


def build_view(feeds, store, selection, today):
    # The calendar is the dates in the file, not a chosen from-to range.
    span = calendar_bounds(feeds) if store else None
    if span:
        days = calendar_days(feeds, store, span[0], span[1])
    else:
        days = []
    filled = sum(1 for day in days if day["fields"]["actual_net"])
    predicted = sum(1 for day in days if day["fields"]["pred_mid"] or day["fields"]["pred_low"] or day["fields"]["pred_high"])
    story = calendar_story(feeds, store)
    described = describe_feeds(feeds["directory"])
    return {
        "posist": posist_window(feeds, store),
        "days": days,
        "weeks": calendar_weeks(days),
        "filled_actual_days": filled,
        "filled_prediction_days": predicted,
        "calendar_share_label": story["share_label"],
        "calendar_absent_note": story["absent_note"],
        "posist_actual_days": sum(1 for day in days if str(day.get("actual_source", "")).startswith("posist")),
        "day_count": len(days),
        "today_iso": today.isoformat() if today else "",
        "posist_columns": POSIST_COLUMNS,
        "calendar_columns": CALENDAR_COLUMNS,
        "keka_columns": KEKA_COLUMNS,
        "audit_columns": AUDIT_COLUMNS,
        "reelo_columns": REELO_COLUMNS,
        "famepilot_columns": FAMEPILOT_COLUMNS,
        "keka": present_keka(feeds, store),
        "audit": present_audit(feeds, store),
        "reelo": present_reelo(feeds, store),
        "fame": present_famepilot(feeds, store),
        "freshness": {
            "posist": present_freshness(described["posist"]),
            "calendar": present_freshness(described["calendar"]),
            "reelo": present_freshness(described["reelo"]),
            "famepilot": present_freshness(described["famepilot"]),
        },
    }
