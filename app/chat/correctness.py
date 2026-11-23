"""Checks that a figure matches the file it came from.

Nothing here is a remembered total. A single day's network net is the
published actual_net_L. A total across days is the sum of the unrounded
East and North figures in that file's notes, rounded once at the end.
A variance week is counted only when that file says so. "Isn't in yet"
is only for the latest expected day, inside the period that was asked,
when its _DONE marker is missing. An older day that already has an
actual in the sales file counts as loaded.
"""

import csv
import re
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[2]
_IST = ZoneInfo("Asia/Kolkata")
_COUNT_HINTS = ("stock_count", "physical_count", "counted", "count_flag", "has_stock_count", "physical")
_COUNTED_VALUES = {"1", "true", "yes", "y", "counted"}
# East/Kolkata and North/Delhi-NCR, with the extra decimals the notes keep.
_PRECISE_NET = re.compile(
    r"(?:East|Kolkata)\b.{0,80}?(?:₹|Rs\.?\s*)([0-9]+(?:\.[0-9]+)?)L"
    r".{0,30}?\+\s*(?:North|Delhi-?NCR|NCR)\b.{0,80}?(?:₹|Rs\.?\s*)([0-9]+(?:\.[0-9]+)?)L",
    re.IGNORECASE,
)


def network_net_rows(path=None):
    """Date to the file's own actual-net text. Blank actuals are left out."""
    file_path = Path(path) if path else _ROOT / "data" / "posist" / "sales_pred_vs_actual.csv"
    found = {}
    if not file_path.is_file():
        return found
    with file_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            day = str(row.get("date") or "")[:10]
            raw = str(row.get("actual_net_L") or "").strip()
            if not day or not raw:
                continue
            found[day] = raw
    return found


def network_net_on(day, path=None):
    rows = network_net_rows(path)
    return rows.get(str(day)[:10])


def _decimal(value):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        return None


def _column_amount(row, *hints):
    for key, value in row.items():
        token = str(key or "").casefold().replace(" ", "_")
        if not all(hint in token for hint in hints):
            continue
        amount = _decimal(value)
        if amount is not None:
            return amount
    return None


def precise_day(row):
    """Unrounded East, North, and network net for one file row, in lakhs.

    Notes win when they carry the extra decimals. A precise East/North
    column is the next choice. The published 2-decimal actual is only the
    fallback for a day whose notes have no split.
    """
    if not isinstance(row, dict):
        return None, None, None
    east = north = None
    match = _PRECISE_NET.search(str(row.get("notes") or ""))
    if match:
        east, north = _decimal(match.group(1)), _decimal(match.group(2))
    if east is None:
        east = _column_amount(row, "east", "net") or _column_amount(row, "kolkata", "net")
    if north is None:
        north = _column_amount(row, "north", "net") or _column_amount(row, "delhi", "net")
    if east is not None and north is not None:
        return east, north, east + north
    published = _decimal(row.get("actual_net_L") or row.get("actual_net"))
    return east, north, published


def _net_file_rows(path=None):
    file_path = Path(path) if path else _ROOT / "data" / "posist" / "sales_pred_vs_actual.csv"
    if not file_path.is_file():
        return []
    with file_path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def round_lakh(value):
    """One rounding, after the sum. Half up, to the paisa of a lakh."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def period_nets(start, end, path=None):
    """Unrounded sums for a date range, plus the figures rounded once.

    Missing dates are listed and the totals stay None, so a gap is not
    treated as zero.
    """
    empty = {
        "total": None, "east": None, "north": None,
        "rounded_total": None, "rounded_east": None, "rounded_north": None,
        "missing": [], "cells": {},
    }
    if not start or not end:
        return empty
    try:
        first = datetime.strptime(str(start)[:10], "%Y-%m-%d").date()
        last = datetime.strptime(str(end)[:10], "%Y-%m-%d").date()
    except ValueError:
        return empty
    by_day = {}
    for row in _net_file_rows(path):
        key = str(row.get("date") or "")[:10]
        if key:
            by_day[key] = row
    missing = []
    cells = {}
    total = Decimal("0")
    east_total = Decimal("0")
    north_total = Decimal("0")
    east_days = north_days = 0
    day = first
    while day <= last:
        key = day.isoformat()
        row = by_day.get(key)
        east, north, precise = precise_day(row) if row else (None, None, None)
        if precise is None:
            missing.append(key)
        else:
            total += precise
            cells[key] = format(precise, "f")
            if east is not None:
                east_total += east
                east_days += 1
            if north is not None:
                north_total += north
                north_days += 1
        day += timedelta(days=1)
    if missing:
        empty["missing"] = missing
        empty["cells"] = cells
        return empty
    span_days = (last - first).days + 1
    return {
        "total": total,
        "east": east_total if east_days == span_days else None,
        "north": north_total if north_days == span_days else None,
        "rounded_total": round_lakh(total),
        "rounded_east": round_lakh(east_total) if east_days == span_days else None,
        "rounded_north": round_lakh(north_total) if north_days == span_days else None,
        "missing": [],
        "cells": cells,
    }


def network_net_window(start, end, path=None):
    """Precise sum of daily net between two ISO dates, inclusive.

    Returns (unrounded total or None, missing ISO dates, precise daily cells).
    Round the total once, with round_lakh, when it is shown.
    """
    found = period_nets(start, end, path)
    return found["total"], found["missing"], found["cells"]


def net_lakh(raw):
    """The file's own decimals, labelled network net in Rs L."""
    text = str(raw).strip()
    if not text:
        return ""
    return f"Rs {text} L network net"


def gross_label(amount_lakh):
    return f"Rs {amount_lakh} L gross"


def variance_basis(row):
    """Counted only when the variance row itself carries a stock-count flag."""
    if not isinstance(row, dict) or not row:
        return "uncounted"
    for key, value in row.items():
        token = str(key or "").strip().casefold().replace(" ", "_")
        if not any(hint in token for hint in _COUNT_HINTS):
            continue
        flag = str(value or "").strip().casefold()
        if flag in _COUNTED_VALUES:
            return "counted"
        return "uncounted"
    return "uncounted"


def variance_label(basis):
    if basis == "counted":
        return "true food cost (physical stock count)"
    return "recipe use + booked wastage, no stock count"


def like_for_like(left, right):
    """Two weeks compare only when both were physically counted."""
    return left == "counted" and right == "counted"


def day_is_loaded(day, root=None):
    """A Posist day is in only when daily_sales has _DONE_<date>."""
    base = Path(root) if root else _ROOT
    stamp = str(day)[:10]
    return (base / "data" / "posist" / "daily_sales" / f"_DONE_{stamp}").is_file()


def latest_expected_day(now=None):
    """The newest day a Posist drop should already be in.

    Before 08:50 IST the new day has not normally arrived, so the expected
    day is the one before yesterday. After that, it is yesterday.
    """
    moment = now or datetime.now(_IST)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_IST)
    else:
        moment = moment.astimezone(_IST)
    yesterday = moment.date() - timedelta(days=1)
    if moment.time() < time(8, 50):
        return yesterday - timedelta(days=1)
    return yesterday


def _in_period(day, asked_start, asked_end):
    stamp = str(day)[:10]
    if not asked_start or not asked_end:
        return True
    return str(asked_start)[:10] <= stamp <= str(asked_end)[:10]


def day_counts_as_loaded(day, root=None, path=None, now=None):
    """A _DONE marker, or an older day that already has an actual."""
    if day_is_loaded(day, root):
        return True
    stamp = str(day)[:10]
    if stamp == latest_expected_day(now).isoformat():
        return False
    return network_net_on(stamp, path) is not None


def day_status(day, root=None, asked_start=None, asked_end=None, now=None):
    """'Isn't in yet' only for the latest expected day, inside the asked period."""
    stamp = str(day)[:10]
    if not _in_period(stamp, asked_start, asked_end):
        return ""
    if stamp != latest_expected_day(now).isoformat():
        return ""
    if day_is_loaded(stamp, root):
        return ""
    return f"{stamp} isn't in yet."


def drop_pending(day, root=None, now=None):
    """The latest expected day is pending only when its _DONE marker is missing.

    An older day is not pending. If the sales file already has its actual,
    that day counts as loaded.
    """
    stamp = str(day)[:10]
    if day_is_loaded(stamp, root):
        return False
    return stamp == latest_expected_day(now).isoformat()


def quoted_day_net(day, path=None, root=None, now=None):
    """One day's published network net, or 'not in yet' for the latest gap."""
    stamp = str(day)[:10]
    if not day_counts_as_loaded(stamp, root, path, now):
        status = day_status(stamp, root=root, now=now)
        if status:
            return f"{status} No partial number from that day is used."
        return ""
    raw = network_net_on(stamp, path)
    if not raw:
        return ""
    return f"{stamp} {net_lakh(raw)}, from sales_pred_vs_actual.csv."


def reconciles(parts, total, tolerance="0.02"):
    try:
        left = sum(Decimal(str(part)) for part in parts)
        right = Decimal(str(total))
    except (InvalidOperation, TypeError):
        return False
    return abs(left - right) <= Decimal(str(tolerance))


def reconcile_note(parts, total):
    if reconciles(parts, total):
        return ""
    return "doesn't reconcile"


def channel_exceeds_gross(channel_total, store_gross):
    try:
        return Decimal(str(channel_total)) > Decimal(str(store_gross))
    except (InvalidOperation, TypeError):
        return False


def accountant_flags(root=None):
    base = Path(root) if root else _ROOT
    path = base / "data" / "flags" / "accountant.csv"
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [row for row in csv.DictReader(handle) if (row.get("title") or "").strip()]
    except OSError:
        return []


def provisional_line(role, owner=False, root=None):
    from app.chat.guard import can_see_pl

    if not can_see_pl(role, owner):
        return ""
    rows = accountant_flags(root)
    if not rows:
        return ""
    lead = rows[0]
    note = (lead.get("detail") or "").strip()
    title = (lead.get("title") or "").strip()
    extra = f" {note}" if note else ""
    return f"Provisional: {title}.{extra}"


def tracker_through_line():
    """Last stock-entry date in the ingredient tracker. Blank when it is not loaded."""
    try:
        from flask import has_app_context
        if not has_app_context():
            return "Ingredient tracker stock-entry date is not loaded."
        from app.extensions import db
        from app.models import IngredientPrice
        last = db.session.query(db.func.max(IngredientPrice.date)).scalar()
    except Exception:
        return "Ingredient tracker stock-entry date is not loaded."
    if not last:
        return "Ingredient tracker stock-entry date is not loaded."
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"Stock entries run through {last.day} {months[last.month - 1]} {last.year}."


def data_footer(data, question=""):
    windows = (data or {}).get("sales_windows") or {}
    summary = (data or {}).get("summary") or {}
    latest = str(windows.get("latest") or summary.get("as_of_date") or summary.get("actuals_through") or "")[:10]
    if latest:
        try:
            day = datetime.strptime(latest, "%Y-%m-%d")
            months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
            through = f"{day.day} {months[day.month - 1]} {day.year}"
        except ValueError:
            through = latest
    else:
        through = "not loaded"
    folded = " ".join((question or "").casefold().split())
    sources = []
    if any(token in folded for token in ("sale", "week", "yesterday", "forecast", "pace", "net", "bill", "gross", "target", "behind", "attention")):
        sources.append("sales_pred_vs_actual.csv (network net)")
        sources.append("Posist daily gross")
    if any(token in folded for token in ("price", "pay", "paneer", "milk", "cheese", "daal", "bought")):
        sources.append("procurement summary")
        sources.append("ingredient tracker")
    if "tally" in folded or "what did we pay" in folded:
        sources.append("Tally day book")
    if not sources:
        sources.append("loaded files for this question")
    asked_end = latest
    asked_start = str(windows.get("week_start") or latest or "")[:10]
    pending = day_status(latest, asked_start=asked_start, asked_end=asked_end) if latest else ""
    line = f"Data through {through} | Sources: {', '.join(sources)}."
    if pending:
        line += " " + pending
    return line


def network_net_sentence(data, path=None):
    """Authoritative network net for the loaded sales week and its last day."""
    windows = (data or {}).get("sales_windows") or {}
    start = windows.get("week_start")
    end = windows.get("latest")
    found = period_nets(start, end, path)
    total, missing, cells = found["total"], found["missing"], found["cells"]
    if not end:
        return ""
    gap = day_status(end, asked_start=start, asked_end=end)
    if gap:
        return f"{gap} No partial network net is shown."
    end_raw = network_net_on(end, path)
    if missing or total is None or not end_raw:
        missing_text = ", ".join(missing) if missing else end
        return f"Network net doesn't reconcile for {missing_text}. Store rows stay gross, not net."
    end_text = net_lakh(end_raw)
    total_text = net_lakh(format(found["rounded_total"], "f"))
    city = ""
    if found["rounded_east"] is not None and found["rounded_north"] is not None:
        city = (
            f" East Rs {format(found['rounded_east'], 'f')} L net, "
            f"North Rs {format(found['rounded_north'], 'f')} L net, "
            "each rounded once after its own unrounded daily sum."
        )
    check = reconcile_note(list(cells.values()), total)
    note = f" {check}." if check else ""
    return (
        f"{end} {end_text}, from sales_pred_vs_actual.csv. "
        f"{start} to {end} {total_text}, the unrounded daily nets summed and then rounded once.{city}{note} "
        "Store rows are gross, not net."
    )
