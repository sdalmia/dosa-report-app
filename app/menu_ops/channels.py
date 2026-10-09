"""Delivery ratings and the POS / Swiggy / Zomato sales mix.

Channel ratings are the current public scores. A missing rating means that
channel is not listed. It is not a zero.

Period totals are the rows with no date. Daily rows are a trend and are not
added into those totals. Average bill is Gross divided by orders.
Payouts after commission are a separate empty state.
"""

from collections import defaultdict

from app.menu_ops.formatutil import format_count, format_inr, format_pct, format_period, format_rating
from app.menu_ops.loader import (
    canonical_channel,
    channels_directory,
    famepilot_directory,
    load_channel_ratings,
    load_channel_sales,
    load_regions,
    store_coverage,
)

RATING_FIELDS = (
    ("zomato_delivery", "Zomato Delivery"),
    ("zomato_dining", "Zomato Dining"),
    ("google", "Google"),
    ("swiggy", "Swiggy"),
)
CHANNEL_ORDER = {"POS": 0, "Swiggy": 1, "Zomato": 2}
PAYOUT_NOTE = "What is left after commission is not in yet."


def build_channels(famepilot=None, channels=None, store=""):
    ratings = load_channel_ratings(famepilot or famepilot_directory())
    sales = load_channel_sales(channels or channels_directory())
    rows = list(ratings["rows"])
    rows.sort(key=_rating_sort)
    as_of = sorted({row["as_of"] for row in rows if row.get("as_of")})
    sales_rows = sales["rows"]
    if store:
        sales_rows = [row for row in sales_rows if row["store"] == store]
    totals = [row for row in sales_rows if row.get("kind", "total") != "daily"]
    daily = [row for row in sales_rows if row.get("kind") == "daily"]
    mix = build_mix(totals)
    regions, _region_warnings = load_regions()
    coverage = store_coverage({row["store"] for row in (totals or daily)}, regions) if sales["present"] else None
    return {
        "ratings": [_present_rating(row) for row in rows],
        "rating_fields": RATING_FIELDS,
        "ratings_present": ratings["present"],
        "rating_columns": ratings["columns"],
        "rating_file": ratings["file"],
        "as_of": as_of,
        "rating_warnings": ratings["warnings"],
        "sales_present": sales["present"] and bool(sales_rows or not store),
        "sales_file": sales["file"],
        "sales_columns": sales["columns"],
        "sales_warnings": sales["warnings"],
        "mix": mix,
        "trend": build_trend(daily),
        "totals_present": bool(totals),
        "daily_present": bool(daily),
        "period_label": _period_label(totals or sales_rows),
        "coverage_label": _coverage_label(coverage),
        "stores": sorted({row["store"] for row in sales["rows"]}),
        "store": store,
        "payout_note": PAYOUT_NOTE,
        "pos_note": "POS includes dine-in and takeaway together.",
    }


def _rating_sort(row):
    rating = row.get("zomato_delivery")
    if not rating:
        return (1, 0.0, row["store"].casefold())
    return (0, rating["value"], row["store"].casefold())


def _present_rating(row):
    presented = {"store": row["store"], "as_of": row.get("as_of") or ""}
    for key, _label in RATING_FIELDS:
        rating = row.get(key)
        if not rating:
            presented[key] = ""
            presented[key + "_style"] = ""
        else:
            presented[key] = format_rating(rating["text"])
            presented[key + "_class"] = heat_class(rating["value"])
    return presented


def heat_class(value):
    """Bucket a public rating. Missing ratings are not coloured."""
    if value is None:
        return ""
    if value < 4.2:
        return "heat-low"
    if value < 4.6:
        return "heat-mid"
    return "heat-high"


def build_mix(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[canonical_channel(row["channel"])].append(row)
    channels = []
    for name, group in grouped.items():
        channels.append(
            {
                "channel": name,
                "gross": _sum_field(group, "gross"),
                "orders": _sum_field(group, "orders"),
                "stores": sorted({row.get("store") for row in group if row.get("store")}),
                "whens": sorted({row["when"] for row in group if row.get("when")}),
            }
        )
    channels.sort(key=lambda row: (CHANNEL_ORDER.get(row["channel"], 9), row["channel"].casefold()))
    gross_known = [row for row in channels if row["gross"] is not None]
    order_known = [row for row in channels if row["orders"] is not None]
    gross_total = sum(row["gross"] for row in gross_known) if gross_known and len(gross_known) == len(channels) else None
    order_total = sum(row["orders"] for row in order_known) if order_known and len(order_known) == len(channels) else None
    # A channel with a blank gross does not become zero, and it is left out of the
    # denominator only when every channel is complete. Partial totals stay blank.
    if gross_total is None and gross_known and len(gross_known) != len(channels):
        gross_total = None
    presented = []
    for row in channels:
        share = None
        order_share = None
        if gross_total not in (None, 0) and row["gross"] is not None:
            share = row["gross"] / gross_total * 100.0
        if order_total not in (None, 0) and row["orders"] is not None:
            order_share = row["orders"] / order_total * 100.0
        apb = None
        if row["gross"] is not None and row["orders"] not in (None, 0):
            apb = row["gross"] / row["orders"]
        presented.append(
            {
                "channel": row["channel"],
                "gross": format_inr(row["gross"]),
                "gross_value": row["gross"],
                "orders": format_count(row["orders"]),
                "orders_value": row["orders"],
                "gross_share": format_pct(share),
                "gross_share_value": share,
                "orders_share": format_pct(order_share),
                "apb": format_inr(apb),
                "stores": row["stores"],
                "whens": row["whens"],
            }
        )
    return {
        "channels": presented,
        "gross_total": format_inr(gross_total if gross_known and len(gross_known) == len(channels) else None),
        "orders_total": format_count(order_total if order_known and len(order_known) == len(channels) else None),
        "whens": sorted({when for row in channels for when in row["whens"]}),
    }


def build_trend(rows):
    by_date = defaultdict(list)
    for row in rows:
        by_date[row.get("when") or ""].append(row)
    days = []
    for when in sorted(by_date):
        mix = build_mix(by_date[when])
        days.append({"when": when, "channels": mix["channels"]})
    return days


def _period_label(rows):
    starts = {row.get("period_from") for row in rows if row.get("period_from")}
    ends = {row.get("period_to") for row in rows if row.get("period_to")}
    if len(starts) == 1 and len(ends) == 1:
        return format_period(next(iter(starts)), next(iter(ends)))
    if starts and ends:
        return format_period(min(starts), max(ends))
    return ""


def _coverage_label(coverage):
    if not coverage:
        return ""
    hit, total = coverage
    return f"{hit} of {total} stores loaded"


def _sum_field(group, field):
    values = [row.get(field) for row in group]
    if any(value is None for value in values):
        return None
    return float(sum(values))
