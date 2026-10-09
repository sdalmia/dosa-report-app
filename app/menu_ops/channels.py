"""Delivery ratings and dine-in versus delivery.

Channel ratings are the current public scores. A missing rating means that
channel is not listed. It is not a zero.

Period totals are the rows with no date. Daily rows are a trend and are not
added into those totals. Average bill is Gross divided by orders, in whole
rupees. A store with no export is data coming, not zero. Forum and
Manisquare in-store bills include bulk mall-system entries, so those bills
and that average bill stay out of comparisons.
Payouts after commission are a separate empty state.
"""

import re
from collections import defaultdict
from datetime import timedelta

from app.menu_ops.formatutil import format_count, format_pct, format_period, format_rating, format_sales
from app.store_health.contract import parse_date
from app.menu_ops.loader import (
    _same_store,
    canonical_channel,
    channels_directory,
    coming_stores,
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
DELIVERY_CHANNELS = {"Swiggy", "Zomato"}
PAYOUT_NOTE = "What is left after commission is not in yet."
MALL_NOTE = (
    "In-store bills at Forum and Manisquare include bulk mall-system entries. "
    "Those bills and the average bill are not in the comparison."
)
_MALL_CODE = re.compile(r"\((?:01/)?000[34]\)\s*$")


def build_channels(famepilot=None, channels=None, store="", region="", window=None):
    ratings = load_channel_ratings(famepilot or famepilot_directory())
    sales = load_channel_sales(channels or channels_directory())
    regions, _region_warnings = load_regions()
    labels = list(regions)
    rows = list(ratings["rows"])
    if region:
        rows = [row for row in rows if _store_region(row["store"], region, regions)]
    if store:
        pool = labels or [store]
        rows = [row for row in rows if _same_store(row["store"], store, pool)]
    rows.sort(key=_rating_sort)
    as_of = sorted({row["as_of"] for row in rows if row.get("as_of")})
    usable, mode = channel_rows_for_window(sales["rows"], window)
    daily = [row for row in sales["rows"] if row.get("kind") == "daily"]
    if window and window[0] and window[1] and mode == "daily":
        daily = [row for row in daily if _day_inside(row, window[0], window[1])]
    if region:
        usable = [row for row in usable if _store_region(row["store"], region, regions)]
        daily = [row for row in daily if _store_region(row["store"], region, regions)]
    if store:
        pool = labels or [store]
        usable = [row for row in usable if _same_store(row["store"], store, pool)]
        daily = [row for row in daily if _same_store(row["store"], store, pool)]
    window_miss = mode == "miss"
    totals = [] if window_miss else usable
    for row in totals + daily:
        row["exclude_from_comparison"] = row.get("channel") == "POS" and is_mall_bulk(row.get("store"))
    mix = build_mix(totals)
    period_stores = {row["store"] for row in totals}
    coming = coming_stores(period_stores, regions) if sales["present"] and not window_miss else []
    if region:
        coming = [name for name in coming if _store_region(name, region, regions)]
    coverage = store_coverage(period_stores, regions) if sales["present"] and not window_miss else None
    store_names = sorted(set(regions) | period_stores, key=str.casefold) if regions else sorted(period_stores)
    if region:
        store_names = [name for name in store_names if _store_region(name, region, regions)]
    comparison = [] if window_miss else build_delivery(totals, coming, store)
    network_label = "Network" if not store and not region else "This selection"
    if window and window[0] and window[1] and mode in {"daily", "miss"}:
        period_label = format_period(window[0], window[1])
    else:
        period_label = _period_label(totals or sales["rows"])
    return {
        "ratings": [_present_rating(row) for row in rows],
        "rating_fields": RATING_FIELDS,
        "ratings_present": ratings["present"],
        "rating_columns": ratings["columns"],
        "rating_file": ratings["file"],
        "as_of": as_of,
        "rating_warnings": ratings["warnings"],
        "sales_present": sales["present"],
        "sales_file": sales["file"],
        "sales_columns": sales["columns"],
        "sales_warnings": sales["warnings"],
        "mix": mix,
        "trend": build_trend(daily),
        "totals_present": bool(totals),
        "daily_present": bool(daily) and not window_miss,
        "window_miss": window_miss,
        "window_mode": mode,
        "period_label": period_label,
        "coverage_label": _coverage_label(coverage),
        "stores": store_names,
        "store": store,
        "coming_stores": [name for name in coming if not store or _same_store(store, name, list(regions) or [name])],
        "store_coming": bool(store) and any(_same_store(store, name, list(regions) or [store]) for name in coming),
        "comparison": comparison,
        "mall_note": MALL_NOTE if any(row.get("exclude_from_comparison") for row in totals) or any(card.get("mall_bulk") for card in comparison) else "",
        "network_label": network_label,
        "network_line": "" if window_miss else _network_line(mix["channels"]),
        "payout_note": PAYOUT_NOTE,
        "pos_note": "POS includes dine-in and takeaway together. Delivery is Swiggy and Zomato. Rapido stays its own channel.",
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


def is_mall_bulk(store):
    """Forum (0003) and Manisquare (0004). Not the North stores 02/0003 and 02/0004."""
    return bool(_MALL_CODE.search(str(store or "").strip()))


def channel_rows_for_window(rows, window):
    """Period totals when that period sits inside the window.

    A shorter window uses daily rows, and only for a store whose every day
    in the window is on file. Daily rows are never added into a period total.
    """
    totals = [row for row in rows if row.get("kind") != "daily"]
    daily = [row for row in rows if row.get("kind") == "daily"]
    if not window or window[0] is None or window[1] is None:
        return totals, "period"
    start, end = window
    inside = [
        row for row in totals
        if row.get("period_from") and row.get("period_to")
        and row["period_from"] >= start and row["period_to"] <= end
    ]
    if inside:
        return inside, "period"
    needed = []
    cursor = start
    while cursor <= end:
        needed.append(cursor)
        cursor += timedelta(days=1)
    by_store = defaultdict(list)
    for row in daily:
        day = parse_date(row.get("when"))
        if day is not None and start <= day <= end:
            by_store[row["store"]].append((day, row))
    chosen = []
    for _store, pairs in by_store.items():
        have = {day for day, _row in pairs}
        if not set(needed).issubset(have):
            continue
        for _day, row in pairs:
            copied = dict(row)
            copied["kind"] = "total"
            chosen.append(copied)
    if chosen:
        return chosen, "daily"
    return [], "miss"


def _day_inside(row, start, end):
    day = parse_date(row.get("when"))
    return day is not None and start <= day <= end


def _store_region(store, region, regions):
    if not region:
        return True
    pool = list(regions)
    for label, name in regions.items():
        if name == region and _same_store(store, label, pool):
            return True
    return False


def store_delivery(store_label, window=None):
    """One store's dine-in and delivery card for the shared date window."""
    sales = load_channel_sales()
    empty = {
        "has_rows": False,
        "coming": False,
        "empty": "Delivery versus dine-in is not on file.",
        "period_label": "",
        "mall_bulk": False,
        "mall_note": "",
        "dine_gross": "",
        "dine_orders": "",
        "dine_apb": "",
        "delivery_gross": "",
        "delivery_orders": "",
        "delivery_apb": "",
        "others": [],
    }
    if not store_label:
        return empty
    if not sales["present"]:
        return empty
    regions, _warnings = load_regions()
    usable, mode = channel_rows_for_window(sales["rows"], window)
    pool = list(regions) or [store_label]
    matched = [row for row in usable if _same_store(row["store"], store_label, pool)]
    if window and window[0] and window[1] and mode in {"daily", "miss"}:
        label = format_period(window[0], window[1])
    else:
        label = _period_label(matched or usable)
    if not matched:
        empty["coming"] = True
        empty["empty"] = "Data coming"
        empty["period_label"] = label
        return empty
    for row in matched:
        row["exclude_from_comparison"] = row.get("channel") == "POS" and is_mall_bulk(row.get("store"))
    card = build_delivery(matched, [], "")[0]
    card["has_rows"] = True
    card["empty"] = ""
    card["period_label"] = label
    card["mall_note"] = MALL_NOTE if card.get("mall_bulk") else ""
    return card


def build_delivery(rows, coming, store=""):
    """One card per store: dine-in (POS) beside Swiggy and Zomato."""
    totals = [row for row in rows if row.get("kind") != "daily"]
    by_store = defaultdict(list)
    for row in totals:
        by_store[row["store"]].append(row)
    names = []
    if store:
        names = [name for name in list(by_store) + list(coming) if name == store or _same_store(store, name, [store, name])]
        if not names and (store in coming or any(_same_store(store, name, [store, name]) for name in coming)):
            names = [store]
    else:
        names = sorted(set(by_store) | set(coming), key=str.casefold)
    cards = []
    for name in names:
        group = by_store.get(name) or []
        if not group and name in coming:
            cards.append({"store": name, "coming": True, "mall_bulk": False})
            continue
        if not group:
            matched = next((label for label in coming if _same_store(name, label, [name, label])), "")
            if matched or name in coming:
                cards.append({"store": name, "coming": True, "mall_bulk": False})
                continue
        mall = is_mall_bulk(name)
        hidden_days = sorted({row.get("when") or "" for row in group if row.get("status") == "not shown"})
        dine = _side(group, {"POS"}, mall)
        delivery = _side(group, DELIVERY_CHANNELS, False)
        others = []
        for row in group:
            if row["channel"] in {"POS"} or row["channel"] in DELIVERY_CHANNELS:
                continue
            others.append(
                {
                    "channel": row["channel"],
                    "gross": format_sales(row.get("gross")),
                    "orders": format_count(row.get("orders")),
                }
            )
        cards.append(
            {
                "store": name,
                "coming": False,
                "mall_bulk": mall,
                "dine_gross": dine["gross"],
                "dine_orders": "" if mall else dine["orders"],
                "dine_apb": "" if mall else dine["apb"],
                "delivery_gross": delivery["gross"],
                "delivery_orders": delivery["orders"],
                "delivery_apb": delivery["apb"],
                "others": others,
                "not_shown": [day for day in hidden_days if day],
            }
        )
    return cards


def _side(group, channels, excluded):
    rows = [row for row in group if row.get("channel") in channels]
    if not rows:
        return {"gross": "", "orders": "", "apb": ""}
    gross = _sum_field(rows, "gross")
    orders = _sum_field(rows, "orders")
    apb = None
    if not excluded and gross is not None and orders not in (None, 0):
        apb = gross / orders
    return {
        "gross": format_sales(gross),
        "orders": format_count(orders),
        "apb": format_sales(apb),
    }


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
                "sources": group,
                "stores": sorted({row.get("store") for row in group if row.get("store")}),
                "whens": sorted({row["when"] for row in group if row.get("when")}),
            }
        )
    channels.sort(key=lambda row: (CHANNEL_ORDER.get(row["channel"], 9), row["channel"].casefold()))
    gross_known = [row for row in channels if row["gross"] is not None]
    gross_total = sum(row["gross"] for row in gross_known) if gross_known and len(gross_known) == len(channels) else None
    presented = []
    for row in channels:
        comparable = [source for source in row["sources"] if not source.get("exclude_from_comparison")]
        compare_gross = _sum_field(comparable, "gross") if comparable else None
        compare_orders = _sum_field(comparable, "orders") if comparable else None
        share = None
        order_share = None
        if gross_total not in (None, 0) and row["gross"] is not None:
            share = row["gross"] / gross_total * 100.0
        order_base = _comparable_order_total(channels)
        if order_base not in (None, 0) and compare_orders is not None:
            order_share = compare_orders / order_base * 100.0
        apb = None
        if compare_gross is not None and compare_orders not in (None, 0):
            apb = compare_gross / compare_orders
        presented.append(
            {
                "channel": row["channel"],
                "gross": format_sales(row["gross"]),
                "gross_value": row["gross"],
                "orders": format_count(compare_orders),
                "orders_value": compare_orders,
                "gross_share": format_pct(share),
                "gross_share_value": share,
                "orders_share": format_pct(order_share),
                "apb": format_sales(apb),
                "stores": row["stores"],
                "whens": row["whens"],
                "excluded": bool(row["sources"]) and not comparable,
            }
        )
    compare_orders_total = _comparable_order_total(channels)
    return {
        "channels": presented,
        "gross_total": format_sales(gross_total if gross_known and len(gross_known) == len(channels) else None),
        "orders_total": format_count(compare_orders_total),
        "whens": sorted({when for row in channels for when in row["whens"]}),
    }


def _comparable_order_total(channels):
    comparable_groups = []
    for row in channels:
        comparable = [source for source in row["sources"] if not source.get("exclude_from_comparison")]
        if not comparable:
            continue
        total = _sum_field(comparable, "orders")
        if total is None:
            return None
        comparable_groups.append(total)
    if not comparable_groups:
        return None
    return float(sum(comparable_groups))


def build_trend(rows):
    by_date = defaultdict(list)
    for row in rows:
        by_date[row.get("when") or ""].append(row)
    days = []
    for when in sorted(by_date):
        day_rows = by_date[when]
        shown = [row for row in day_rows if row.get("status") != "not shown"]
        hidden = sorted({row["store"] for row in day_rows if row.get("status") == "not shown"})
        mix = build_mix(shown)
        days.append({"when": when, "channels": mix["channels"], "not_shown": hidden})
    return days


def _network_line(channels):
    """POS + Zomato + Swiggy + every other source. Blank if any source has no gross."""
    if not channels:
        return ""
    values = {row["channel"]: row.get("gross_value") for row in channels}
    if any(value is None for value in values.values()):
        return ""
    total = sum(values.values())
    others = sum(value for name, value in values.items() if name not in {"POS", "Zomato", "Swiggy"})
    return (
        f"{format_sales(total)} = POS {format_sales(values.get('POS'))}"
        f" + Zomato {format_sales(values.get('Zomato'))}"
        f" + Swiggy {format_sales(values.get('Swiggy'))}"
        f" + others {format_sales(others)}"
    )


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
    """Sum shown rows. A not-shown day is left out, not added as zero."""
    rows = [row for row in group if row.get("status") != "not shown"]
    if not rows:
        return None
    values = [row.get(field) for row in rows]
    if any(value is None for value in values):
        return None
    return float(sum(values))
