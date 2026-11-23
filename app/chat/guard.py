"""Who may see what, and how a figure is allowed to be described.

Full P&L, store EBITDA, rent amounts, rent as a percent of sales, and margin
percent stay on the roles in WIZARD_PL_ROLES. The default is the owner only.
Add a role in that variable to widen it. No code change.

Tally books, bank statements, and the inbox stay on the owner login.
Reelo answers stay at store aggregates. A guest list is never written.
"""

import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")
_HOLD = ("on hold", "on-hold", "unconfirmed")


def pl_roles():
    raw = os.environ.get("WIZARD_PL_ROLES", "owner")
    return frozenset(part.strip().casefold() for part in str(raw).split(",") if part.strip())


def can_see_pl(role, owner=False):
    """Full P&L, EBITDA, rent amounts, rent percent, and margin percent."""
    allowed = pl_roles()
    if owner and "owner" in allowed:
        return True
    return (role or "").casefold() in allowed


def can_see_books(role, owner=False):
    """Tally, bank statements, and the inbox. Owner only."""
    if owner and (role in {None, "", "owner"}):
        return True
    return (role or "").casefold() == "owner"


def flag_unconfirmed(row):
    """True when the flag's own status text says on hold or unconfirmed."""
    if not isinstance(row, dict):
        return False
    blob = " ".join(
        str(row.get(key) or "")
        for key in ("status", "state", "hold", "title", "detail", "note")
    ).casefold()
    return any(token in blob for token in _HOLD)


def unconfirmed_label():
    return "unconfirmed - possible data-entry error"


def asks_for_guest_list(question):
    folded = " ".join((question or "").casefold().split())
    if any(token in folded for token in (
        "guest list", "guest name", "guests name", "customer name", "customers name",
        "list of guest", "list of customer", "lapsed guest", "lapsed customer",
        "phone number", "mobile number", "their numbers", "who are the guest",
        "who hasn't visited", "who has not visited",
    )):
        if "captur" in folded and "list" not in folded and "name" not in folded and "lapsed" not in folded:
            return False
        return True
    return False


def guest_refusal():
    return (
        "Campaign audiences stay in Reelo, and Logan runs the sends. "
        "This answer does not list guests, names, or phone numbers. "
        "Store phone capture, repeat share, redemption, and ratings are available."
    )


def sales_stamp(data, now=None):
    """Sales-through date, the morning lag, and a labelled forecast when one is loaded."""
    latest = _latest_day(data)
    if latest is None:
        return ""
    moment = now or datetime.now(_IST)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_IST)
    else:
        moment = moment.astimezone(_IST)
    yesterday = moment.date() - timedelta(days=1)
    line = f"Sales through {_day_text(latest)}."
    if latest < yesterday:
        if moment.time() < time(8, 50):
            line += " Yesterday's sales may not be loaded yet. The day usually arrives after about 8:50 AM IST."
        else:
            line += " Yesterday's sales are not in the file yet."
    forecast = _forecast_line(data, moment.date())
    if forecast:
        line += " " + forecast
    return line


def _latest_day(data):
    windows = (data or {}).get("sales_windows") or {}
    summary = (data or {}).get("summary") or {}
    raw = windows.get("latest") or summary.get("as_of_date") or summary.get("actuals_through") or ""
    return _parse_day(raw)


def _parse_day(value):
    text = str(value or "").strip()[:10]
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _day_text(day):
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{day.day} {months[day.month - 1]}"


def _forecast_line(data, today):
    """A forward figure is a forecast, with its range when the file has one."""
    summary = (data or {}).get("summary") or {}
    low = summary.get("forecast_low_L") or summary.get("point_low_L")
    high = summary.get("forecast_high_L") or summary.get("point_high_L")
    mid = summary.get("point_forecast_L")
    if mid is not None and (low is not None or high is not None):
        return _range_sentence("The point", mid, low, high, "L")
    try:
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        network = root / "data" / "posist" / "sales_pred_vs_actual.csv"
        line = _next_band(network, today, "L")
        if line:
            return line
        folder = root / "data" / "forecast"
        if folder.is_dir():
            files = sorted(folder.glob("*.csv"))
            if files:
                return _next_band(files[-1], today, "")
    except Exception:
        return ""
    return ""


def _range_sentence(when, mid, low, high, unit):
    mid_text = f"₹{float(mid):.1f}{unit}" if unit == "L" else f"₹{float(mid):,.0f}"
    if low is None or high is None:
        return f"{when} forecast {mid_text}. This is a forecast, not an actual."
    if unit == "L":
        span = f"₹{float(low):.1f}–{float(high):.1f}{unit}"
    else:
        span = f"₹{float(low):,.0f}–₹{float(high):,.0f}"
    return f"{when} forecast {mid_text}, likely {span}. This is a forecast, not an actual."


def _next_band(path, today, unit):
    import csv
    if not path.is_file():
        return ""
    best = None
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            day = _parse_day(row.get("date"))
            mid = _num(row.get("pred_mid_L") if unit == "L" else row.get("pred_mid"))
            actual = _num(row.get("actual_net_L") or row.get("actual_gross") or row.get("actual"))
            if day is None or mid is None or day < today or actual not in (None, 0):
                continue
            if best is None or day < best["day"]:
                low_key = "pred_low_L" if unit == "L" else "pred_low"
                high_key = "pred_high_L" if unit == "L" else "pred_high"
                best = {
                    "day": day,
                    "weekday": row.get("weekday") or "",
                    "mid": mid,
                    "low": _num(row.get(low_key)),
                    "high": _num(row.get(high_key)),
                }
    if not best:
        return ""
    when = f"{(best['weekday'] or '')[:3]} {_day_text(best['day'])}".strip()
    return _range_sentence(when, best["mid"], best["low"], best["high"], unit)


def _num(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
