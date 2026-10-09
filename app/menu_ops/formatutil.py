"""Display helpers. A missing value stays a blank string, never zero."""

from datetime import date, datetime


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
    if value is None:
        return ""
    negative = float(value) < 0
    cents = int(round(abs(float(value)) * 100))
    whole, frac = divmod(cents, 100)
    body = group_indian(str(whole))
    if frac:
        body = f"{body}.{frac:02d}"
    sign = "-" if negative else ""
    return f"{sign}₹{body}"


def format_sales(value):
    """Owner money. Whole rupees, lakhs, or crores. No paise."""
    from app.store_health.present import format_owner_rupee

    return format_owner_rupee(value)


def format_count(value):
    if value is None:
        return ""
    number = float(value)
    if number.is_integer():
        sign = "-" if number < 0 else ""
        return sign + group_indian(str(abs(int(number))))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def format_pct(value):
    """A share already expressed in percent. Blank stays blank. Zero stays 0%."""
    if value is None:
        return ""
    number = float(value)
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def format_hours(value):
    if value is None:
        return ""
    number = float(value)
    if number >= 100:
        return str(int(round(number)))
    return f"{number:.1f}"


def format_rating(text):
    """Keep the digits that were in the file. Do not turn 4 into 4.0."""
    if text is None:
        return ""
    return str(text).strip()


def format_period(start, end):
    if not isinstance(start, date) or not isinstance(end, date):
        return ""
    if start == end:
        return _day(start)
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {start.strftime('%b %Y')}"
    if start.year == end.year:
        return f"{start.day} {start.strftime('%b')}–{end.day} {end.strftime('%b %Y')}"
    return f"{_day(start)}–{_day(end)}"


def format_stamp(value):
    if isinstance(value, datetime):
        return value.strftime("%-d %b %Y, %H:%M")
    if isinstance(value, date):
        return _day(value)
    return ""


def _day(value):
    return f"{value.day} {value.strftime('%b %Y')}"
