"""Display figures. None stays blank. A real zero is kept and formatted."""

from app.store_health.present import format_count, format_inr, format_pct


def fig(value, text=""):
    if value is None:
        return {"value": None, "text": ""}
    return {"value": float(value), "text": text}


def money_fig(value):
    if value is None:
        return fig(None)
    return fig(value, format_inr(value))


def count_fig(value):
    if value is None:
        return fig(None)
    number = float(value)
    return fig(number, format_count(number))


def pct_fig(value):
    if value is None:
        return fig(None)
    return fig(value, format_pct(value))


def score_fig(value):
    if value is None:
        return fig(None)
    return fig(value, f"{float(value):.1f}")


def plain_pct_fig(value):
    """A share of a target, without a plus sign. A change uses pct_fig instead."""
    if value is None:
        return fig(None)
    number = float(value)
    text = f"{number:.1f}".rstrip("0").rstrip(".")
    return fig(number, f"{text}%")


def ratio_fig(value):
    if value is None:
        return fig(None)
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return fig(value, text)


def date_label(day):
    if day is None:
        return ""
    return f"{day.strftime('%a')} {day.day} {day.strftime('%b %Y')}"


def month_label(key):
    if not key or len(key) != 7:
        return key or ""
    year, month = key.split("-")
    names = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    return f"{names[int(month) - 1]} {year}"
