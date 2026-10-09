"""Food cost for Kolkata (East) and Delhi (North).

Purchases are warehouse GRN. Sales are Posist gross, because net is blank.
Raw means Food + Beverage. Semi-process is not included.
"""

import re

from app.procurement.loader import (
    CITY_FOR_REGION,
    CITY_ORDER,
    REGION_FOR_CITY,
    source_name,
)
from app.procurement.numbers import (
    format_period,
    format_qty,
    money_pair,
    parse_number,
    parse_period,
    pct_pair,
    percent,
    sum_present,
)
from app.procurement.recipe import recipe_section

COVER_OVER_DAYS = 15
EXCESS_COVER_DAYS = 10
_DAYS = re.compile(r"=\s*([\d,]+(?:\.\d+)?)\s*days", re.IGNORECASE)
_BOUGHT = re.compile(r"bought\s+([\d,]+(?:\.\d+)?)", re.IGNORECASE)
_STORE_NOISE = re.compile(r"\([^)]*\)")
_CODE = re.compile(r"\b\d{2}/\d{4}\b")
_LEADING_CODE = re.compile(r"\b0\d{2,}\b")


def build_food_cost(bundle):
    week_start, week_end = _consumption_bounds(bundle)
    span_start, span_end = _grn_bounds(bundle)
    if week_start is None:
        week_start, week_end = bundle["period_start"], bundle["period_end"]
    comparable = week_start is not None and week_end is not None
    cities = _cities(bundle, week_start, week_end, span_start, span_end)
    week_label = format_period(week_start, week_end)
    span_label = format_period(span_start, span_end)
    return {
        "period_label": _page_period(week_label, span_label),
        "week_label": week_label,
        "span_label": span_label,
        "period_start": week_start.isoformat() if week_start else "",
        "period_end": week_end.isoformat() if week_end else "",
        "september_note": _coverage_note(week_start, week_end, span_start, span_end),
        "sales_note": (
            "Sales are Posist gross from posist_daily.csv. "
            "Net is blank in that file, so net is not used."
        ),
        "raw_note": "Raw is Food + Beverage. Semi-process is excluded.",
        "variance_note": (
            "Warehouse and central-kitchen variance is not shown. "
            "Their physical stock is ₹0 in the source, so the variance is not meaningful. "
            "store_consumption_wastage.csv also leaves physical_amt blank on those rows."
        ),
        "store_purchase_note": _store_purchase_note(bundle),
        "cities": cities,
        "stores": _stores(bundle, week_start, week_end) if comparable else [],
        "alerts": _alerts(bundle, week_start, week_end),
        "hershey": _hershey(bundle),
        "wastage": _wastage(bundle),
        "recipe": recipe_section(bundle),
        "unassigned": _unassigned(bundle),
        "warnings": list(bundle["warnings"]),
        "missing_grn": _missing(bundle, "grn_lines", "grn_lines_warehouses.csv"),
        "missing_consumption": _missing(bundle, "consumption", "store_consumption_wastage.csv"),
        "missing_posist": _missing_posist(bundle),
        "sources": {
            "grn": source_name(bundle, "grn_lines") or "grn_lines_warehouses.csv",
            "charges": source_name(bundle, "grn_charges") or "grn_charges_warehouses.csv",
            "consumption": source_name(bundle, "consumption") or "store_consumption_wastage.csv",
            "wastage": source_name(bundle, "wastage") or "store_item_wastage_top.csv",
            "workbook": source_name(bundle, "workbook") or "consumption_vs_purchase workbook",
            "posist": bundle["posist_path"].name,
        },
    }


def _consumption_bounds(bundle):
    periods = {row.get("period") for row in bundle["consumption"] if row.get("period")}
    if len(periods) != 1:
        return None, None
    return parse_period(next(iter(periods)))


def _grn_bounds(bundle):
    dates = [row["date"] for row in bundle["grn_lines"] if row.get("date")]
    if not dates:
        return None, None
    return min(dates), max(dates)


def _page_period(week_label, span_label):
    parts = []
    if span_label:
        parts.append(f"Purchases {span_label}")
    if week_label and week_label != span_label:
        parts.append(f"consumption {week_label}")
    elif week_label and not parts:
        parts.append(week_label)
    return " · ".join(parts) or "Period not on file"


def _coverage_note(week_start, week_end, span_start, span_end):
    week = format_period(week_start, week_end)
    span = format_period(span_start, span_end)
    if week and span and (week_start != span_start or week_end != span_end):
        return (
            f"GRN lines cover {span}. "
            f"Store consumption and wastage cover {week} only. "
            "There is no September consumption file, so a food-cost % that uses consumption "
            f"is for {week}, not the full purchase window."
        )
    if span:
        return f"GRN lines cover {span}."
    return ""


def _missing(bundle, key, expected):
    if bundle["files"].get(key):
        return ""
    return f"Missing source: {expected}"


def _missing_posist(bundle):
    if bundle["posist"]:
        return ""
    return f"Missing source: {bundle['posist_path'].name} (Posist gross)."


def _store_purchase_note(bundle):
    outlets = [row for row in bundle["consumption"] if row.get("store_type") == "Outlet"]
    if not outlets:
        return ""
    purchases = [row.get("purchase_amt_raw") for row in outlets]
    if any(value is None for value in purchases):
        return ""
    if any(value != 0 for value in purchases):
        return ""
    return (
        "Outlet raw purchases are ₹0 on every outlet row in store_consumption_wastage.csv. "
        "That zero is recorded. City purchases below are warehouse GRN."
    )


def _cities(bundle, week_start, week_end, span_start, span_end):
    names = []
    for name in CITY_ORDER:
        names.append(name)
    for row in bundle["grn_lines"]:
        city = row.get("city")
        if city and city not in names:
            names.append(city)
    for row in bundle["consumption"]:
        city = row.get("city")
        if city and city not in names:
            names.append(city)
    same_window = week_start == span_start and week_end == span_end
    return [
        _city_block(bundle, city, week_start, week_end, span_start, span_end, same_window)
        for city in names
    ]


def _sum_dated(rows, city, start, end, field):
    if start is None or end is None:
        return None
    values = []
    seen = False
    for row in rows:
        if row.get("city") != city:
            continue
        day = row.get("date")
        if day is None or not (start <= day <= end):
            continue
        seen = True
        values.append(row.get(field))
    if not seen:
        return None
    return sum_present(values)


def _city_block(bundle, city, week_start, week_end, span_start, span_end, same_window):
    region = REGION_FOR_CITY.get(city, "")
    slug = city.casefold().replace(" ", "-")
    rows = [row for row in bundle["consumption"] if row.get("city") == city]
    week = _consumption_window(bundle, city, region, rows, week_start, week_end)
    span = None
    if not same_window:
        span = _purchase_window(bundle, city, region, span_start, span_end, week_start, week_end)
    return {
        "city": city,
        "slug": slug,
        "region": region,
        "region_label": f"{city} · {region}" if region else city,
        "week": week,
        "span": span,
    }


def _consumption_window(bundle, city, region, rows, start, end):
    gross, gross_rows, gross_blanks = _region_gross(bundle["posist"], region, start, end)
    grn_all = _sum_dated(bundle["grn_lines"], city, start, end, "total") if bundle["files"].get("grn_lines") else None
    freight = _sum_dated(bundle["grn_charges"], city, start, end, "amount") if bundle["files"].get("grn_charges") else None
    grn_raw = _workbook_metric(bundle, "grn_value_raw", city)
    consumption = sum_present(row.get("consumption_amt_raw") for row in rows) if rows else None
    outlets = [row for row in rows if row.get("store_type") == "Outlet"]
    kitchens = [row for row in rows if _is_kitchen(row)]
    warehouses = [row for row in rows if _is_warehouse(row)]
    wastage = _wastage_sum(rows) if rows else None
    return {
        "label": format_period(start, end),
        "gross": money_pair(gross),
        "gross_rows": gross_rows,
        "gross_blanks": gross_blanks,
        "grn_all": money_pair(grn_all),
        "grn_all_pct": pct_pair(percent(grn_all, gross)),
        "grn_raw": money_pair(grn_raw),
        "grn_raw_pct": pct_pair(percent(grn_raw, gross)),
        "grn_raw_missing": grn_raw is None,
        "freight": money_pair(freight),
        "consumption": money_pair(consumption),
        "consumption_pct": pct_pair(percent(consumption, gross)),
        "outlet_consumption": money_pair(sum_present(row.get("consumption_amt_raw") for row in outlets) if outlets else None),
        "kitchen_consumption": money_pair(sum_present(row.get("consumption_amt_raw") for row in kitchens) if kitchens else None),
        "warehouse_consumption": money_pair(
            sum_present(row.get("consumption_amt_raw") for row in warehouses) if warehouses else None
        ),
        "wastage": money_pair(wastage),
    }


def _purchase_window(bundle, city, region, start, end, week_start, week_end):
    gross, gross_rows, gross_blanks = _region_gross(bundle["posist"], region, start, end)
    grn_all = _sum_dated(bundle["grn_lines"], city, start, end, "total") if bundle["files"].get("grn_lines") else None
    freight = _sum_dated(bundle["grn_charges"], city, start, end, "amount") if bundle["files"].get("grn_charges") else None
    week = format_period(week_start, week_end) or "the consumption file"
    return {
        "label": format_period(start, end),
        "gross": money_pair(gross),
        "gross_rows": gross_rows,
        "gross_blanks": gross_blanks,
        "grn_all": money_pair(grn_all),
        "grn_all_pct": pct_pair(percent(grn_all, gross)),
        "freight": money_pair(freight),
        "consumption_missing": (
            f"Raw consumption is not shown for {format_period(start, end)}. "
            f"store_consumption_wastage.csv covers {week} only. "
            "There is no September consumption file."
        ),
    }


def _region_gross(posist, region, start, end):
    if not region or start is None or end is None:
        return None, 0, 0
    matched = [
        row
        for row in posist
        if row.get("region") == region and start <= row["date"] <= end
    ]
    blanks = sum(1 for row in matched if row.get("gross") is None)
    gross = sum_present(row.get("gross") for row in matched)
    return gross, len(matched), blanks


def _workbook_metric(bundle, metric, city):
    workbook = bundle.get("workbook")
    if not workbook:
        return None
    row = workbook["summary"].get(metric) or {}
    return row.get(city)


def _is_kitchen(row):
    name = (row.get("store") or "").casefold()
    return "central kitchen" in name


def _is_warehouse(row):
    name = (row.get("store") or "").casefold()
    return "warehouse" in name


def _wastage_sum(rows):
    parts = []
    for row in rows:
        parts.append(row.get("wastage_amt_raw"))
        parts.append(row.get("yield_wastage_amt_raw"))
    return sum_present(parts)


def store_key(label):
    text = (label or "").casefold().replace("dosa coffee", " ")
    text = _STORE_NOISE.sub(" ", text)
    text = _CODE.sub(" ", text)
    text = _LEADING_CODE.sub(" ", text)
    cleaned = []
    for char in text:
        cleaned.append(char if char.isalnum() else " ")
    return " ".join("".join(cleaned).split())


def _stores(bundle, start, end):
    grouped = {}
    for row in bundle["consumption"]:
        if row.get("store_type") != "Outlet":
            continue
        city = row.get("city")
        deployment = row.get("deployment")
        if not city or not deployment:
            continue
        bucket = grouped.setdefault(
            (city, deployment),
            {"city": city, "deployment": deployment, "rows": []},
        )
        bucket["rows"].append(row)
    posist_index = _posist_index(bundle["posist"], start, end)
    stores = []
    for bucket in grouped.values():
        rows = bucket["rows"]
        consumption = sum_present(row.get("consumption_amt_raw") for row in rows)
        wastage = _wastage_sum(rows)
        physical_values = [row.get("physical_gain_loss_amt_raw") for row in rows]
        counted = [value for value in physical_values if value is not None]
        physical = sum_present(counted)
        gross_info = posist_index.get(store_key(bucket["deployment"]))
        gross = gross_info["gross"] if gross_info else None
        stores.append(
            {
                "city": bucket["city"],
                "region": REGION_FOR_CITY.get(bucket["city"], ""),
                "name": bucket["deployment"],
                "key": store_key(bucket["deployment"]),
                "consumption": money_pair(consumption),
                "wastage": money_pair(wastage),
                "physical": money_pair(physical),
                "physical_partial": physical is not None and any(value is None for value in physical_values),
                "physical_blank": physical is None,
                "gross": money_pair(gross),
                "gross_matched": gross_info is not None,
                "gross_blanks": gross_info["blanks"] if gross_info else 0,
                "posist_name": gross_info["store"] if gross_info else "",
                "food_cost_pct": pct_pair(percent(consumption, gross)),
            }
        )
    stores.sort(key=lambda store: (CITY_ORDER.index(store["city"]) if store["city"] in CITY_ORDER else 99, -(store["consumption"]["value"] or 0)))
    return stores


def _posist_index(posist, start, end):
    if start is None or end is None:
        return {}
    buckets = {}
    for row in posist:
        if not (start <= row["date"] <= end):
            continue
        key = store_key(row["store"])
        if not key:
            continue
        bucket = buckets.setdefault(
            key, {"store": row["store"], "gross_values": [], "blanks": 0, "ambiguous": False}
        )
        if bucket["store"] != row["store"]:
            bucket["ambiguous"] = True
        if row.get("gross") is None:
            bucket["blanks"] += 1
        else:
            bucket["gross_values"].append(row["gross"])
    index = {}
    for key, bucket in buckets.items():
        if bucket["ambiguous"]:
            continue
        index[key] = {
            "store": bucket["store"],
            "gross": sum_present(bucket["gross_values"]),
            "blanks": bucket["blanks"],
        }
    return index


def _unassigned(bundle):
    rows = [row for row in bundle["consumption"] if not row.get("city")]
    if not rows:
        return None
    return {
        "names": sorted({row.get("deployment") or "Unnamed deployment" for row in rows}),
        "consumption": money_pair(sum_present(row.get("consumption_amt_raw") for row in rows)),
    }


def _alerts(bundle, start, end):
    workbook = bundle.get("workbook")
    if not workbook:
        return {
            "available": False,
            "missing": "Missing source: consumption_vs_purchase workbook (item sheets and flags).",
            "cover": [],
            "beyond_10": [],
            "stock": [],
        }
    period_days = None
    if start and end:
        period_days = (end - start).days + 1
    cover = []
    beyond = []
    seen = set()
    for item in workbook["items"]:
        days = item.get("WH closing days of cover")
        key = (item.get("city"), item.get("Item"))
        seen.add(key)
        if days is not None and days > COVER_OVER_DAYS:
            cover.append(_cover_row(item, days, "WH closing days of cover"))
        if days is not None and days > EXCESS_COVER_DAYS:
            beyond.append(_beyond_row(item, days, period_days, workbook["source"]))
    for flag in workbook["flags"]:
        kind = _flag_kind(flag.get("flag"))
        key = (flag.get("city"), flag.get("item_or_store"))
        days = _parse_days(flag.get("detail"))
        if kind in {"beyond_10", "packaging"} and key not in seen and days is not None and days > COVER_OVER_DAYS:
            cover.append(
                {
                    "city": flag.get("city") or "",
                    "item": flag.get("item_or_store") or "",
                    "unit": "",
                    "days_text": format_qty(days),
                    "days_attr": f"{days:.4f}".rstrip("0").rstrip("."),
                    "closing_qty_text": "",
                    "basis": "flags sheet",
                    "detail": flag.get("detail") or "",
                }
            )
        if kind == "beyond_10" and key not in seen:
            beyond.append(
                {
                    "city": flag.get("city") or "",
                    "item": flag.get("item_or_store") or "",
                    "unit": "",
                    "days_text": format_qty(days) if days is not None else "",
                    "excess_qty_text": "",
                    "value": money_pair(flag.get("amount_rs")),
                    "rate_text": "",
                    "detail": flag.get("detail") or "",
                    "source": f"{workbook['source']} flags, stock beyond 10 days of use",
                }
            )
    cover.sort(key=lambda row: (-float(row["days_attr"] or 0), row["city"], row["item"]))
    beyond.sort(key=lambda row: (-(row["value"]["value"] or 0), row["city"], row["item"]))
    stock = _stock_alerts(workbook)
    return {
        "available": True,
        "missing": "",
        "cover": cover,
        "beyond_10": beyond,
        "stock": stock,
        "period_days": period_days,
        "source": workbook["source"],
    }


def _cover_row(item, days, basis):
    return {
        "city": item.get("city") or "",
        "item": item.get("Item") or "",
        "unit": item.get("Unit (Restroworks)") or "",
        "days_text": format_qty(days),
        "days_attr": f"{float(days):.4f}".rstrip("0").rstrip("."),
        "closing_qty_text": format_qty(item.get("WH closing qty")),
        "basis": basis,
        "detail": "",
    }


def _beyond_row(item, days, period_days, source):
    closing = item.get("WH closing qty")
    consumed = item.get("Network consumed qty")
    rate = item.get("Avg GRN rate Rs")
    excess_qty = None
    excess_value = None
    if (
        closing is not None
        and consumed is not None
        and period_days
    ):
        daily = consumed / period_days
        excess_qty = closing - EXCESS_COVER_DAYS * daily
        if rate is not None:
            excess_value = excess_qty * rate
    if excess_qty is not None and excess_qty <= 0:
        excess_qty = None
        excess_value = None
    return {
        "city": item.get("city") or "",
        "item": item.get("Item") or "",
        "unit": item.get("Unit (Restroworks)") or "",
        "days_text": format_qty(days),
        "excess_qty_text": format_qty(excess_qty),
        "value": money_pair(excess_value),
        "rate_text": format_qty(rate),
        "detail": "",
        "source": (
            f"{source} item sheet. "
            f"Value is warehouse closing qty minus {EXCESS_COVER_DAYS} days of network use, "
            "times the average GRN rate. A missing rate stays blank."
        ),
    }


def _stock_alerts(workbook):
    rows = []
    for flag in workbook["flags"]:
        kind = _flag_kind(flag.get("flag"))
        detail = flag.get("detail") or ""
        if kind == "little_purchase":
            bought = _parse_bought(detail)
            negative = "NEGATIVE" in detail.upper()
            no_purchase = bought == 0
            if not no_purchase and not negative:
                continue
            if no_purchase and negative:
                label = "Used, none bought, and stock went negative"
            elif no_purchase:
                label = "Used and none bought"
            else:
                label = "Stock went negative"
        elif kind == "wh_negative":
            label = "Warehouse closing is negative"
            no_purchase = False
        else:
            continue
        rows.append(
            {
                "city": flag.get("city") or "",
                "item": flag.get("item_or_store") or "",
                "label": label,
                "severity": flag.get("severity") or "",
                "amount": money_pair(flag.get("amount_rs")),
                "detail": detail,
            }
        )
    rows.sort(key=lambda row: (row["city"], row["item"]))
    return rows


def _flag_kind(label):
    text = label or ""
    if text.startswith("1b"):
        return "packaging"
    if text.startswith("1w"):
        return "watch"
    if text.startswith("1 "):
        return "beyond_10"
    if text.startswith("2b"):
        return "wh_negative"
    if text.startswith("2 "):
        return "little_purchase"
    if text.startswith("5"):
        return "data_entry"
    return ""


def _parse_days(detail):
    if not detail:
        return None
    match = _DAYS.search(detail)
    if not match:
        return None
    return parse_number(match.group(1))


def _parse_bought(detail):
    if not detail:
        return None
    match = _BOUGHT.search(detail)
    if not match:
        return None
    return parse_number(match.group(1))


def _hershey(bundle):
    lines = []
    for row in bundle["indent_rows"]:
        if "hershey" not in (row.get("item_name") or "").casefold():
            continue
        lines.append(
            {
                "date": row["date"].isoformat() if row.get("date") else "",
                "date_text": format_period(row.get("date"), row.get("date")),
                "receiver": row.get("receiver") or "",
                "item": row.get("item_name") or "",
                "unit": row.get("unit") or "",
                "qty_text": format_qty(row.get("stock_out_qty")),
                "qty_attr": f"{row['stock_out_qty']:.4f}".rstrip("0").rstrip(".") if row.get("stock_out_qty") is not None else "",
                "unit_price": money_pair(row.get("unit_price")),
                "subtotal": money_pair(row.get("stock_out_subtotal")),
                "reference": row.get("stock_out_reference") or "",
                "source": row.get("source") or "",
                "is_error": (row.get("stock_out_reference") or "") == "IN-1854",
            }
        )
    lines.sort(key=lambda row: (row["date"], row["reference"]))
    flag = None
    workbook = bundle.get("workbook")
    if workbook:
        for row in workbook["flags"]:
            if _flag_kind(row.get("flag")) == "data_entry" and "1854" in (row.get("detail") or ""):
                flag = {
                    "item": row.get("item_or_store") or "",
                    "city": row.get("city") or "",
                    "amount": money_pair(row.get("amount_rs")),
                    "detail": row.get("detail") or "",
                    "action": row.get("suggested_action") or "",
                    "source": workbook["source"],
                }
                break
    indent_names = [
        name
        for name in (source_name(bundle, "indent_delhi"), source_name(bundle, "indent_kolkata"))
        if name
    ]
    if not lines and not flag:
        return {
            "available": False,
            "missing": (
                "Missing source: indent stock-out CSV (consumption_stockInStockOut_Indent) "
                "and the Hershey's flag in the consumption workbook."
            ),
            "lines": [],
            "flag": None,
        }
    return {
        "available": True,
        "missing": "" if lines else "The IN-1854 line is not in the indent CSV.",
        "lines": lines,
        "flag": flag,
        "sources": indent_names,
    }


def _wastage(bundle):
    if not bundle["files"].get("wastage"):
        return {"available": False, "missing": "Missing source: store_item_wastage_top.csv", "rows": []}
    rows = []
    for row in bundle["wastage"]:
        amount = row.get("total_wastage_amt")
        if amount is None:
            continue
        rows.append(
            {
                "city": row.get("city") or "",
                "store": row.get("store") or "",
                "deployment": row.get("deployment") or "",
                "item": row.get("item_name") or "",
                "unit": row.get("unit") or "",
                "qty_text": format_qty(row.get("wastage_qty")),
                "amount": money_pair(amount),
                "pct": pct_pair(row.get("wastage_pct_of_consumption")),
                "super_category": row.get("super_category") or "",
            }
        )
    rows.sort(key=lambda row: -(row["amount"]["value"] or 0))
    return {
        "available": True,
        "missing": "",
        "rows": rows[:8],
        "total_lines": len(rows),
        "source": source_name(bundle, "wastage"),
    }


def city_for_region(region):
    return CITY_FOR_REGION.get(region or "", "")
