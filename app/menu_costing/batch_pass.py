"""Procurement's first batch pass.

The files on hand are 1–8 Oct. A later file for 24 Sep–8 Oct becomes the
default period as soon as those rows are present. A blank made quantity stays
blank and is shown as Not recorded, never as zero.
"""

import csv
from datetime import date
from pathlib import Path
from statistics import median

from app.procurement.numbers import (
    format_period,
    format_qty,
    num_attr,
    parse_number,
    parse_period,
    sum_present,
)

PREFERRED = (date(2026, 9, 24), date(2026, 10, 8))
NOT_RECORDED = "Not recorded"
COMING = "Use for this date range is not on file. Data coming."
UNRECORDED = (
    "Kitchens don't record what they make, so yield and wastage can't be measured. "
    "Fix: daily production entry in Restroworks (Sailesh, Kolkata; Shanker, Delhi)."
)
RATE_NOTE = (
    "Transfer prices differ by city. These are transfer prices, not recipe cost. "
    "Each city is compared with itself."
)
_NAME_PAIRS = (
    ("Medu Vada Batter", "Medu Vada Batter Mix"),
    ("Malabar Paratha Dough", "Malabar Paratha  (1pkt= 6Pcs)"),
)
_RATE_PAIRS = (
    ("Coconut Shredded", "Coconut Shredded"),
    ("Dosa Batter Mix", "Dosa Batter Mix"),
    ("Sambar Bucket", "Sambar Bucket - Delhi"),
)
_FOCUS = {name.casefold() for pair in _NAME_PAIRS for name in pair}
_FOCUS.add("tomato onion chutney bucket")


def pass_view(procurement=None, *, city="", store="", store_id="", query="", filters=None):
    procurement = Path(procurement) if procurement else _procurement_dir()
    detail = _read_detail(procurement)
    coverage = _read_coverage(procurement)
    chosen = _choose_period(detail, coverage, filters)
    if chosen == "coming":
        return _empty(COMING)
    if chosen is None:
        return _empty("")
    start, end, raw = chosen
    label = format_period(start, end)
    detail = [row for row in detail if row["period"] == raw]
    coverage = [row for row in coverage if row["period"] == raw]
    detail = _filter_rows(detail, city, store, store_id, query)
    coverage_city = _filter_coverage(coverage, city, query)
    tiles = _tiles(detail, coverage_city, city, bool(store or store_id))
    alerts = _alerts(detail, coverage, city, label, query)
    return {
        "ready": bool(tiles or alerts),
        "period": label,
        "note": "",
        "alerts": alerts,
        "tiles": tiles,
    }


def _empty(note):
    return {"ready": False, "period": "", "note": note, "alerts": [], "tiles": []}


def _procurement_dir():
    return Path(__file__).resolve().parents[2] / "data" / "procurement"


def _read_detail(directory):
    rows = []
    for path in sorted(directory.glob("batch_actual_use_detail*.csv")):
        rows.extend(_detail_rows(path))
    return rows


def _read_coverage(directory):
    rows = []
    for path in sorted(directory.glob("batch_item_coverage*.csv")):
        rows.extend(_coverage_rows(path))
    return rows


def _detail_rows(path):
    from app.menu_costing.batches import _store_index

    places = _store_index()
    found = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                item = (raw.get("batch_item") or "").strip()
                city = (raw.get("city") or "").strip()
                if not item or not city:
                    continue
                store = (raw.get("store") or "").strip()
                place = places.get(store.casefold()) or {}
                found.append({
                    "city": city,
                    "store": store,
                    "store_id": place.get("store_id") or "",
                    "item": item,
                    "unit": (raw.get("unit") or "").strip(),
                    "period": (raw.get("period") or "").strip(),
                    "made": parse_number(raw.get("city_made_qty")),
                    "issued": parse_number(raw.get("issued_qty")),
                    "issued_amt": parse_number(raw.get("issued_amt")),
                    "used": parse_number(raw.get("consumption_qty")),
                    "used_amt": parse_number(raw.get("consumption_amt")),
                    "closing": parse_number(raw.get("closing_qty")),
                    "rate": parse_number(raw.get("avg_price")),
                })
    except OSError:
        return []
    return found


def _coverage_rows(path):
    found = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                item = (raw.get("batch_item") or "").strip()
                city = (raw.get("city") or "").strip()
                if not item or not city:
                    continue
                found.append({
                    "city": city,
                    "item": item,
                    "unit": (raw.get("unit") or "").strip(),
                    "period": (raw.get("period") or "").strip(),
                    "made": (raw.get("made") or "").strip().casefold(),
                    "issued": (raw.get("issued") or "").strip().casefold(),
                    "used": (raw.get("consumed") or "").strip().casefold(),
                    "costed": (raw.get("cost") or "").strip().casefold(),
                    "rate": parse_number(raw.get("avg_price_max")),
                    "used_amt": parse_number(raw.get("consumption_amt")),
                    "issued_qty": parse_number(raw.get("issued_qty")),
                    "used_qty": parse_number(raw.get("consumption_qty")),
                })
    except OSError:
        return []
    return found


def _choose_period(detail, coverage, filters):
    periods = {}
    for row in list(detail) + list(coverage):
        raw = row.get("period") or ""
        start, end = parse_period(raw)
        if start and end:
            periods[(start, end)] = raw
    if not periods:
        return None
    kind = (filters or {}).get("cc_range") or ""
    if kind:
        from app.view_filters import resolve_bounds

        matched = []
        for (start, end), raw in periods.items():
            chosen_start, chosen_end = resolve_bounds(filters, start, end)
            if chosen_start == start and chosen_end == end:
                matched.append((start, end, raw))
        if not matched:
            return "coming"
        return _prefer(matched)
    return _prefer([(start, end, raw) for (start, end), raw in periods.items()])


def _prefer(periods):
    for start, end, raw in periods:
        if (start, end) == PREFERRED:
            return start, end, raw
    return max(periods, key=lambda row: row[1])


def _filter_rows(rows, city, store, store_id, query):
    from app.menu_costing.batches import _store_match

    query_key = (query or "").strip().casefold()
    kept = []
    for row in rows:
        if city and row["city"] != city:
            continue
        if not _store_match(row, store, store_id):
            continue
        if query_key and query_key not in row["item"].casefold():
            continue
        kept.append(row)
    return kept


def _filter_coverage(rows, city, query):
    query_key = (query or "").strip().casefold()
    kept = []
    for row in rows:
        if city and row["city"] != city:
            continue
        if query_key and query_key not in row["item"].casefold():
            continue
        kept.append(row)
    return kept


def _tiles(detail, coverage, city, narrowed):
    from app.menu_costing.catalog import owner_count, owner_rupee

    grouped = {}
    for row in detail:
        key = (row["city"], row["item"])
        bucket = grouped.setdefault(key, {
            "city": row["city"],
            "item": row["item"],
            "unit": row["unit"],
            "made": [],
            "issued": [],
            "used": [],
            "used_amt": [],
            "issued_amt": [],
            "rates": [],
            "closing": [],
        })
        bucket["made"].append(row["made"])
        bucket["issued"].append(row["issued"])
        bucket["used"].append(row["used"])
        bucket["used_amt"].append(row["used_amt"])
        bucket["issued_amt"].append(row["issued_amt"])
        bucket["closing"].append(row["closing"])
        if row["rate"] is not None:
            bucket["rates"].append(row["rate"])
        if row["unit"]:
            bucket["unit"] = row["unit"]
    flags = {(row["city"], row["item"]): row for row in coverage}
    for key, row in flags.items():
        grouped.setdefault(key, {
            "city": row["city"],
            "item": row["item"],
            "unit": row["unit"],
            "made": [],
            "issued": [],
            "used": [],
            "used_amt": [],
            "issued_amt": [],
            "rates": [],
            "closing": [],
        })
    tiles = []
    for key, bucket in grouped.items():
        flag = flags.get(key)
        if city and not narrowed and flag is None and not any(bucket["issued"]) and not any(value is not None for value in bucket["used"]):
            continue
        made = sum_present(bucket["made"])
        issued = sum_present(bucket["issued"])
        used = sum_present(bucket["used"])
        rate = _rate(bucket, flag, narrowed)
        unit = _unit_label(bucket["unit"] or (flag or {}).get("unit") or "")
        tiles.append({
            "city": bucket["city"],
            "item": bucket["item"],
            "issued": _qty(issued, unit, owner_count),
            "issued_attr": num_attr(issued),
            "used": _qty(used, unit, owner_count),
            "used_attr": num_attr(used),
            "rate": _rate_text(rate, unit, owner_rupee),
            "rate_attr": num_attr(rate),
            "made": _made_text(made, flag, unit, owner_count),
            "made_attr": num_attr(made),
            "issued_flag": _yes_no(flag, "issued", issued),
            "used_flag": _yes_no(flag, "used", used),
            "costed_flag": _yes_no(flag, "costed", rate),
            "used_amt": sum_present(bucket["used_amt"]) or 0,
            "focus": bucket["item"].casefold() in _FOCUS or (issued is None and used not in (None, 0)),
        })
    tiles.sort(key=lambda row: (0 if row["focus"] else 1, -row["used_amt"], row["item"].casefold()))
    for row in tiles:
        row.pop("used_amt", None)
        row.pop("focus", None)
    return tiles


def _rate(bucket, flag, narrowed):
    if narrowed and bucket["rates"]:
        return float(median(bucket["rates"]))
    if flag and flag.get("rate") is not None:
        return flag["rate"]
    if bucket["rates"]:
        return float(median(bucket["rates"]))
    return None


def _made_text(made, flag, unit, owner_count):
    recorded = flag and flag.get("made") == "yes"
    if made is None and not recorded:
        return NOT_RECORDED
    if made is None:
        return NOT_RECORDED
    return _qty(made, unit, owner_count)


def _yes_no(flag, field, value):
    if flag and flag.get(field) in {"yes", "no"}:
        return "Yes" if flag[field] == "yes" else "No"
    if field == "costed":
        return "Yes" if value is not None else "No"
    return "Yes" if value is not None else "No"


def _qty(value, unit, owner_count):
    if value is None:
        return ""
    if abs(value) >= 10 or abs(value - round(value)) < 0.05:
        shown = owner_count(value)
        if shown == "0" and value != 0:
            shown = format_qty(value)
    else:
        shown = format_qty(value)
    return f"{shown} {unit}".strip()


def _rate_text(rate, unit, owner_rupee):
    if rate is None:
        return ""
    text = owner_rupee(rate)
    if not text:
        return ""
    return f"{text}/{unit}" if unit else text


def _unit_label(unit):
    key = " ".join((unit or "").casefold().split())
    return {
        "kg": "kg",
        "ltr": "L",
        "l": "L",
        "pc": "pc",
        "gm": "g",
        "g": "g",
        "pkt": "pkt",
    }.get(key, unit)


def _alerts(detail, coverage, city, label, query):
    from app.menu_costing.catalog import owner_count, owner_rupee

    alerts = []
    if _made_missing(detail, coverage):
        alerts.append({
            "kind": "unrecorded",
            "severity": "amber",
            "kicker": label,
            "title": "Production is not recorded",
            "detail": UNRECORDED,
            "pairs": [],
        })
    names = _name_alert(detail, city, owner_count)
    if names:
        alerts.append(names)
    tomato = _tomato_alert(detail, coverage, city, label, owner_count, owner_rupee)
    if tomato:
        alerts.append(tomato)
    rates = _rate_alert(coverage, city, owner_rupee)
    if rates:
        alerts.append(rates)
    if query:
        needle = query.strip().casefold()
        alerts = [row for row in alerts if needle in " ".join([
            row.get("title") or "",
            row.get("detail") or "",
            " ".join(pair.get("left", "") + pair.get("right", "") for pair in row.get("pairs") or []),
        ]).casefold()]
    return alerts


def _made_missing(detail, coverage):
    if any(row["made"] is not None for row in detail):
        return False
    if any(row.get("made") == "yes" for row in coverage):
        return False
    return bool(detail or coverage)


def _name_alert(detail, city, owner_count):
    lines = []
    pairs = []
    for issued_name, used_name in _NAME_PAIRS:
        issued = _sum_item(detail, issued_name)
        used = _sum_item(detail, used_name)
        if issued["issued"] is None and used["used"] is None:
            continue
        unit_issued = _unit_label(issued["unit"])
        unit_used = _unit_label(used["unit"])
        lines.append(
            f"{issued_name} is issued and {used_name} is what the recipe deducts. "
            "Stock builds on one name and goes negative on the other."
        )
        pairs.append({
            "left_label": f"{issued_name} issued",
            "left": _qty(issued["issued"], unit_issued, owner_count),
            "left_attr": num_attr(issued["issued"]),
            "right_label": f"{used_name} used",
            "right": _qty(used["used"], unit_used, owner_count),
            "right_attr": num_attr(used["used"]),
        })
    if not pairs:
        return None
    scope = city or "Both cities"
    return {
        "kind": "names",
        "severity": "red",
        "kicker": scope,
        "title": "Batter and dough names do not match",
        "detail": " ".join(lines),
        "pairs": pairs,
    }


def _tomato_alert(detail, coverage, city, label, owner_count, owner_rupee):
    if city and city != "Delhi NCR":
        return None
    item = "Tomato Onion Chutney Bucket"
    totals = _sum_item(detail, item, city="Delhi NCR")
    covered = next((row for row in coverage if row["city"] == "Delhi NCR" and row["item"] == item), None)
    used = totals["used"]
    issued = totals["issued"]
    amount = totals["used_amt"]
    if covered and amount is None:
        amount = covered.get("used_amt")
    if used is None and (covered is None or covered.get("used") != "yes"):
        return None
    if issued not in (None, 0):
        return None
    unit = _unit_label(totals["unit"] or (covered or {}).get("unit") or "Kg")
    return {
        "kind": "tomato",
        "severity": "red",
        "kicker": label,
        "title": "Tomato Onion Chutney used with nothing received",
        "detail": f"Delhi stores deducted {item} and nothing was received. {label}.",
        "pairs": [{
            "left_label": "Used",
            "left": _qty(used if used is not None else (covered or {}).get("used_qty"), unit, owner_count),
            "left_attr": num_attr(used if used is not None else (covered or {}).get("used_qty")),
            "right_label": "Transfer value",
            "right": owner_rupee(amount),
            "right_attr": num_attr(amount),
        }],
    }


def _rate_alert(coverage, city, owner_rupee):
    pairs = []
    by_key = {(row["city"], row["item"]): row for row in coverage}
    examples = (
        ("Coconut Shredded", "Kolkata", "Coconut Shredded", "Delhi NCR"),
        ("Dosa Batter Mix", "Kolkata", "Dosa Batter Mix", "Delhi NCR"),
        ("Sambar Bucket", "Kolkata", "Sambar Bucket - Delhi", "Delhi NCR"),
    )
    for left_name, left_city, right_name, right_city in examples:
        if city and city not in {left_city, right_city}:
            continue
        left = by_key.get((left_city, left_name))
        right = by_key.get((right_city, right_name))
        if not left or not right or left.get("rate") is None or right.get("rate") is None:
            continue
        left_text = _rate_text(left["rate"], _unit_label(left["unit"]), owner_rupee)
        right_text = _rate_text(right["rate"], _unit_label(right["unit"]), owner_rupee)
        if left_text == right_text and left_name == right_name:
            continue
        pairs.append({
            "left_label": f"Kolkata {left_name}",
            "left": left_text,
            "left_attr": num_attr(left["rate"]),
            "right_label": f"Delhi {right_name}",
            "right": right_text,
            "right_attr": num_attr(right["rate"]),
        })
    if not pairs:
        return None
    return {
        "kind": "rates",
        "severity": "",
        "kicker": "Transfer price",
        "title": "Transfer prices differ by city",
        "detail": RATE_NOTE,
        "pairs": pairs,
    }


def _sum_item(detail, item, city=""):
    rows = [row for row in detail if row["item"] == item and (not city or row["city"] == city)]
    unit = next((row["unit"] for row in rows if row["unit"]), "")
    return {
        "issued": sum_present(row["issued"] for row in rows),
        "used": sum_present(row["used"] for row in rows),
        "used_amt": sum_present(row["used_amt"] for row in rows),
        "closing": sum_present(row["closing"] for row in rows),
        "unit": unit,
    }
