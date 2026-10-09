"""Parsing and display. A blank cell is missing. Zero is kept when the file has 0."""

import re
from datetime import date, datetime

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_CROSS_MONTH = re.compile(
    r"(?P<d1>\d{1,2})(?P<m1>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"-(?P<d2>\d{1,2})(?P<m2>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"(?P<y>\d{4})",
    re.IGNORECASE,
)
_SAME_MONTH = re.compile(
    r"(?P<d1>\d{1,2})-(?P<d2>\d{1,2})"
    r"(?P<m>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?P<y>\d{4})",
    re.IGNORECASE,
)
_ISO = re.compile(r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})")
_DMY = re.compile(r"(?P<d>\d{2})-(?P<m>\d{2})-(?P<y>\d{4})")


def blank(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def parse_number(value):
    """Float, or None when the cell is blank or not a number. Zero stays zero."""
    if blank(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("₹", "").replace(",", "").replace("%", "")
    text = text.replace(" ", "")
    if text[:1] == "+":
        text = text[1:]
    elif text[:1] == "−":
        text = "-" + text[1:]
    if text in {"", "-", ".", "-."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value):
    number = parse_number(value)
    if number is None:
        return None
    return int(number)


def sum_present(values):
    """Sum numbers. All-blank is None, not zero. Real zeros are included."""
    present = [value for value in values if value is not None]
    if not present:
        return None
    return float(sum(present))


def percent(part, whole):
    if part is None or whole is None or whole == 0:
        return None
    return part / whole * 100.0


def parse_date(value):
    if blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    iso = _ISO.fullmatch(text[:10])
    if iso and len(text) >= 10 and text[4] == "-":
        try:
            return date(int(iso.group("y")), int(iso.group("m")), int(iso.group("d")))
        except ValueError:
            return None
    dmy = _DMY.fullmatch(text)
    if dmy:
        try:
            return date(int(dmy.group("y")), int(dmy.group("m")), int(dmy.group("d")))
        except ValueError:
            return None
    return None


def parse_period(text):
    """'2026-10-01 to 2026-10-08' -> (start, end)."""
    if blank(text):
        return None, None
    parts = re.split(r"\s+to\s+", str(text).strip(), maxsplit=1)
    if len(parts) != 2:
        return None, None
    return parse_date(parts[0]), parse_date(parts[1])


def _mdy(day, month_name, year):
    month = MONTHS.get(month_name.casefold())
    if month is None:
        return None
    try:
        return date(int(year), month, int(day))
    except ValueError:
        return None


def dates_in_filename(name):
    """Return (start, end) for the latest range written in a filename.

    Undated names return (None, None). Same-month form is 01-08Oct2026.
    Cross-month form is 08Sep-08Oct2026.
    """
    found = []
    for match in _CROSS_MONTH.finditer(name):
        start = _mdy(match.group("d1"), match.group("m1"), match.group("y"))
        end = _mdy(match.group("d2"), match.group("m2"), match.group("y"))
        if start and end:
            found.append((start, end))
    for match in _SAME_MONTH.finditer(name):
        start = _mdy(match.group("d1"), match.group("m"), match.group("y"))
        end = _mdy(match.group("d2"), match.group("m"), match.group("y"))
        if start and end:
            found.append((start, end))
    for match in _ISO.finditer(name):
        try:
            day = date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
        except ValueError:
            continue
        found.append((day, day))
    if not found:
        return None, None
    found.sort(key=lambda pair: (pair[1], pair[0]))
    return found[-1]


def file_rank(path):
    start, end = dates_in_filename(path.name)
    latest = end or start
    return (
        latest is not None,
        latest or date.min,
        start or date.min,
        path.name,
    )


def format_period(start, end):
    if start is None and end is None:
        return ""
    if start is None:
        return _format_day(end)
    if end is None or start == end:
        return _format_day(start)
    if start.year == end.year and start.month == end.month:
        return f"{start.day}–{end.day} {end.strftime('%b %Y')}"
    if start.year == end.year:
        return f"{start.day} {start.strftime('%b')}–{end.day} {end.strftime('%b %Y')}"
    return f"{_format_day(start)}–{_format_day(end)}"


def _format_day(day):
    return f"{day.day} {day.strftime('%b %Y')}"


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


def format_pct(value):
    if value is None:
        return ""
    return f"{value:.1f}%"


def format_qty(value):
    if value is None:
        return ""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text


def num_attr(value):
    if value is None:
        return ""
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def money_pair(value):
    return {"value": value, "text": format_inr(value), "attr": num_attr(value)}


def pct_pair(value):
    return {"value": value, "text": format_pct(value), "attr": num_attr(value)}
