"""Recipe cost for the menu page.

Stock Recipe cost excludes takeaway packaging and banana leaf.
Recipe consumption cost is the billing-driven cost at Ideal Plaza only.
Selling price is not in these files, so margin stays blank.
"""

import csv
from pathlib import Path

from app.procurement.loader import (
    newest_file,
    posist_daily_path,
    preferred_recipe_item_path,
    procurement_dir,
)
from app.procurement.numbers import (
    format_inr,
    format_pct,
    format_period,
    format_qty,
    money_pair,
    parse_number,
    parse_period,
    pct_pair,
    percent,
)

RECIPE_LABEL = "recipe cost excl. packaging"


def recipe_costs(
    directory=None,
    outlet=None,
    menu_item=None,
    include_lines=False,
    include_non_menu=False,
    recipe_tab=None,
):
    """Recipe cost for the menu page. Reads whichever cost file is on disk.

    menu_item_cost*.csv wins when it is present. Otherwise recipe_cost_by_item.csv.
    Summary and channel files are not the item file.
    `outlet` matches the outlet or deployment name.
    `recipe_tab` limits rows to base, table, takeout, or delivery. Omit it to keep every tab.
    Margin is always null: these files have no selling price.
    """
    directory = Path(directory) if directory else procurement_dir()
    item_path = preferred_recipe_item_path(directory)
    kind = _source_kind(item_path)
    lines_path = None if kind == "menu_item_cost" else newest_file(directory, "recipe_cost_lines*.csv")
    consumption_path = newest_file(
        directory,
        "recipe_consumption_cost_ideal_plaza*.csv",
        exclude=lambda path: "_lines" in path.name,
    )
    check_path = newest_file(directory, "recipe_cost_ideal_plaza_check_vs_consumption*.csv")
    if item_path is None:
        return {
            "available": False,
            "label": RECIPE_LABEL,
            "source_kind": "",
            "missing_source": "",
            "margin": None,
            "margin_unavailable": "Recipe cost is not on file, so margin is blank.",
            "items": [],
            "outlets": [],
        }
    items = _read_items(item_path, kind)
    outlets = sorted({row["outlet"] for row in items if row.get("outlet")})
    if not include_non_menu:
        items = [row for row in items if row["is_menu_item"]]
    if recipe_tab:
        wanted_tab = recipe_tab.casefold()
        items = [row for row in items if (row.get("recipe_tab") or "base").casefold() == wanted_tab]
    if outlet:
        wanted = outlet.casefold()
        items = [
            row
            for row in items
            if wanted in (row.get("outlet") or "").casefold() or wanted in (row.get("city") or "").casefold()
        ]
    if menu_item:
        wanted_item = menu_item.casefold()
        items = [row for row in items if row["menu_item"].casefold() == wanted_item]
    packaging = _packaging_gap(check_path)
    payload = {
        "available": True,
        "label": RECIPE_LABEL,
        "source_kind": kind,
        "missing_source": "",
        "source": item_path.name,
        "lines_source": lines_path.name if lines_path else "",
        "outlets": outlets,
        "other_outlets_missing": _coverage_sentence(kind, outlets),
        "basis": (
            "Base recipe at average price and last price. "
            "This is recipe cost excl. packaging: takeaway packaging and banana leaf are not in the base recipe."
        ),
        "margin": None,
        "margin_unavailable": _margin_reason(),
        "item_count": len(items),
        "items_with_unpriced": sum(1 for row in items if row.get("partial")),
        "items": items,
        "packaging_gap": packaging,
        "consumption": _consumption_block(consumption_path),
        "summary": _read_summary(newest_file(directory, "menu_item_cost*summary*.csv")),
    }
    if include_lines and lines_path and menu_item and kind != "menu_item_cost":
        payload["lines"] = _read_stock_lines(lines_path, menu_item, outlet)
    elif include_lines:
        payload["lines"] = []
        payload["lines_note"] = "Ingredient lines are not in this export. Ask for one item on the older recipe file."
    return payload


def ideal_plaza_recipe_costs(directory=None, menu_item=None, include_lines=False):
    """Ideal Plaza slice of recipe_costs, for the menu page."""
    return recipe_costs(
        directory=directory,
        outlet="Ideal Plaza",
        menu_item=menu_item,
        include_lines=include_lines,
    )


def recipe_section(bundle):
    payload = recipe_costs(bundle["directory"])
    summary = payload.get("summary") or []
    menu_summary = [row for row in summary if row.get("is_menu_item")]
    if menu_summary:
        payload["list_kind"] = "summary"
        payload["rows"] = [
            {
                "menu_item": row["item_name"],
                "unit": row["unit"],
                "low": money_pair(row["min_cost"]),
                "typical": money_pair(row["median_cost"]),
                "high": money_pair(row["max_cost"]),
                "outlet_min": row["outlet_min"],
                "outlet_max": row["outlet_max"],
                "spread": pct_pair(row["spread_pct"]),
                "outlets": row["outlets_with_recipe"],
            }
            for row in menu_summary
        ]
        payload["rows"].sort(key=lambda row: row["menu_item"].casefold())
    else:
        payload["list_kind"] = "items"
        rows = []
        for item in payload.get("items") or []:
            if not _is_base_tab(item):
                continue
            rows.append(
                {
                    "deployment": item["outlet"],
                    "city": item["city"],
                    "menu_item": item["menu_item"],
                    "unit": item["recipe_unit"],
                    "avg": money_pair(item["cost_per_unit_avg_price"]),
                    "last": money_pair(item["cost_per_unit_last_price"]),
                    "gap": pct_pair(item["last_vs_avg_pct"]),
                    "unpriced": item["unpriced_ingredient_count"] or 0,
                    "partial": item.get("partial") or False,
                    "margin_text": "",
                }
            )
        rows.sort(key=lambda row: (row["city"], row["menu_item"].casefold()))
        payload["rows"] = rows
    consumption = payload.get("consumption") or {}
    cons_rows = []
    for item in consumption.get("items") or []:
        cons_rows.append(
            {
                "menu_item": item["menu_item"],
                "qty_text": format_qty(item["qty_sold"]),
                "cost": money_pair(item["theoretical_cost_per_unit"]),
                "total": money_pair(item["ingredient_cost_total"]),
                "missing_price": item["lines_missing_price"] or 0,
            }
        )
    cons_rows.sort(key=lambda row: -(row["total"]["value"] or 0))
    payload["consumption_rows"] = cons_rows
    return payload


def _source_kind(path):
    if path is None:
        return ""
    name = path.name.casefold()
    if name.startswith("menu_item_cost"):
        return "menu_item_cost"
    return "recipe_cost_by_item"


def _coverage_sentence(kind, outlets):
    if kind == "menu_item_cost":
        count = len(outlets)
        if count:
            return f"Base recipe cost is on file for {count} outlets."
        return "Base recipe cost is on file for the outlets in this export."
    if outlets:
        return "On file for " + " and ".join(outlets) + " only."
    return "Only some outlets are on file."


def _is_base_tab(item):
    tab = (item.get("recipe_tab") or "").casefold()
    return tab in {"", "base"}


def _truthy(value):
    return str(value or "").strip().casefold() in {"true", "1", "yes"}


def _item_record(
    *,
    outlet,
    city,
    menu_item,
    unit,
    is_menu_item,
    avg,
    last,
    unpriced,
    recipe_tab="",
    has_unpriced=None,
    cost_status="",
    comparable=None,
    region="",
    as_of="",
):
    gap = None
    if avg is not None and last is not None:
        gap = percent(last - avg, avg)
    partial = bool(has_unpriced) if has_unpriced is not None else bool(unpriced)
    return {
        "deployment": outlet,
        "outlet": outlet,
        "city": city,
        "menu_item": menu_item,
        "item_name": menu_item,
        "recipe_unit": unit,
        "unit": unit,
        "is_menu_item": is_menu_item,
        "recipe_tab": recipe_tab or "base",
        "cost_per_unit_avg_price": avg,
        "cost_per_portion_avg": avg,
        "cost_per_unit_last_price": last,
        "cost_per_portion_last": last,
        "last_vs_avg_pct": gap,
        "unpriced_ingredient_count": unpriced,
        "has_unpriced_ingredient": partial,
        "partial": partial,
        "cost_status": cost_status,
        "comparable_for_cross_outlet": comparable,
        "selling_price": None,
        "margin": None,
        "label": RECIPE_LABEL,
        "region": region,
        "as_of": as_of,
    }


def _read_items(path, kind):
    if kind == "menu_item_cost":
        return _read_menu_items(path)
    return _read_stock_items(path)


def _read_menu_items(path):
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = (raw.get("item_name") or raw.get("menu_item") or "").strip()
            if not name:
                continue
            unpriced = parse_number(raw.get("unpriced_ingredient_count"))
            flagged = raw.get("has_unpriced_ingredient")
            rows.append(
                _item_record(
                    outlet=(raw.get("outlet") or raw.get("deployment") or "").strip(),
                    city=(raw.get("city") or "").strip(),
                    menu_item=name,
                    unit=(raw.get("unit") or raw.get("recipe_unit") or "").strip(),
                    is_menu_item=_truthy(raw.get("is_menu_item")),
                    avg=parse_number(raw.get("cost_per_portion_avg")),
                    last=parse_number(raw.get("cost_per_portion_last")),
                    unpriced=unpriced,
                    recipe_tab=(raw.get("recipe_tab") or "base").strip(),
                    has_unpriced=_truthy(flagged) if (flagged or "").strip() else None,
                    cost_status=(raw.get("cost_status") or "").strip(),
                    comparable=_truthy(raw.get("comparable_for_cross_outlet"))
                    if (raw.get("comparable_for_cross_outlet") or "").strip()
                    else None,
                    region=(raw.get("region") or "").strip(),
                    as_of=(raw.get("as_of") or "").strip(),
                )
            )
    return rows


def _read_summary(path):
    if path is None:
        return []
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = (raw.get("item_name") or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "item_name": name,
                    "unit": (raw.get("unit") or "").strip(),
                    "is_menu_item": _truthy(raw.get("is_menu_item")),
                    "outlets_with_recipe": parse_number(raw.get("outlets_with_recipe")),
                    "min_cost": parse_number(raw.get("min_cost_avg")),
                    "median_cost": parse_number(raw.get("median_cost_avg")),
                    "max_cost": parse_number(raw.get("max_cost_avg")),
                    "outlet_min": (raw.get("outlet_min") or "").strip(),
                    "outlet_max": (raw.get("outlet_max") or "").strip(),
                    "spread_pct": parse_number(raw.get("spread_pct")),
                    "median_east": parse_number(raw.get("median_cost_east")),
                    "median_north": parse_number(raw.get("median_cost_north")),
                }
            )
    return rows


def _margin_reason():
    mix_label = _menu_mix_period()
    if mix_label:
        return (
            "Margin is blank. These recipes have no selling price. "
            f"Menu mix covers {mix_label}, which is a different period, so it is not used."
        )
    return "Margin is blank. These recipes have no selling price."


def _menu_mix_period():
    path = posist_daily_path().parent / "menu_mix.csv"
    if not path.exists():
        return ""
    starts = []
    ends = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (row.get("period_start") or "").strip():
                starts.append(row["period_start"].strip())
            if (row.get("period_end") or "").strip():
                ends.append(row["period_end"].strip())
            if starts and ends:
                break
    if not starts or not ends:
        return ""
    parsed_start, parsed_end = parse_period(f"{min(starts)} to {max(ends)}")
    return format_period(parsed_start, parsed_end)


def _read_stock_items(path):
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = (raw.get("menu_item") or "").strip()
            if not name:
                continue
            flag = (raw.get("is_menu_item") or "").strip().casefold()
            unpriced = parse_number(raw.get("unpriced_ingredient_count"))
            record = _item_record(
                outlet=(raw.get("deployment") or "").strip(),
                city=(raw.get("city") or "").strip(),
                menu_item=name,
                unit=(raw.get("recipe_unit") or "").strip(),
                is_menu_item=flag == "true",
                avg=parse_number(raw.get("cost_per_unit_avg_price")),
                last=parse_number(raw.get("cost_per_unit_last_price")),
                unpriced=unpriced,
                recipe_tab="base",
            )
            recorded_gap = parse_number(raw.get("last_vs_avg_pct"))
            if recorded_gap is not None:
                record["last_vs_avg_pct"] = recorded_gap
            record["recipe_code"] = (raw.get("recipe_code") or "").strip()
            record["ingredient_count"] = parse_number(raw.get("ingredient_count"))
            record["unpriced_ingredient_count_last"] = parse_number(raw.get("unpriced_ingredient_count_last"))
            rows.append(record)
    return rows


def _read_stock_lines(path, menu_item, outlet):
    wanted = menu_item.casefold()
    outlet_key = (outlet or "").casefold()
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = (raw.get("menu_item") or raw.get("recipe_name") or "").strip()
            if name.casefold() != wanted:
                continue
            deployment = (raw.get("deployment") or "").strip()
            if outlet_key and outlet_key not in deployment.casefold() and outlet_key not in (raw.get("city") or "").casefold():
                continue
            rows.append(
                {
                    "deployment": deployment,
                    "menu_item": name,
                    "ingredient_name": (raw.get("ingredient_name") or "").strip(),
                    "ingredient_unit": (raw.get("ingredient_unit") or "").strip(),
                    "ingredient_cost_avg": parse_number(raw.get("ingredient_cost_avg")),
                    "ingredient_cost_last": parse_number(raw.get("ingredient_cost_last")),
                    "price_missing": (raw.get("unpriced_avg") or "").strip().casefold() in {"true", "1", "yes"},
                }
            )
    return rows


def _consumption_block(path):
    if path is None:
        return {
            "available": False,
            "missing_source": "",
            "items": [],
        }
    items = []
    outlet = ""
    period = ""
    basis = ""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            name = (raw.get("menu_item") or "").strip()
            if not name:
                continue
            outlet = outlet or (raw.get("outlet") or "").strip()
            period = period or (raw.get("period") or "").strip()
            basis = basis or (raw.get("basis") or "").strip()
            items.append(
                {
                    "menu_item": name,
                    "qty_sold": parse_number(raw.get("qty_sold")),
                    "ingredient_cost_total": parse_number(raw.get("ingredient_cost_total")),
                    "theoretical_cost_per_unit": parse_number(raw.get("theoretical_cost_per_unit")),
                    "lines_missing_price": parse_number(raw.get("lines_missing_price")),
                    "selling_price": None,
                    "margin": None,
                }
            )
    start, end = parse_period(period)
    return {
        "available": True,
        "missing_source": "",
        "outlet": outlet or "Ideal Plaza",
        "period": period,
        "period_label": format_period(start, end),
        "basis": basis,
        "source": path.name,
        "scope_note": "What was actually spent is Ideal Plaza only. Connaught Place does not have this figure.",
        "items": items,
    }


def _packaging_gap(path):
    if path is None:
        return None
    extra = 0.0
    consumed = 0.0
    extra_seen = False
    consumed_seen = False
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            qty = parse_number(raw.get("qty_sold"))
            unit_extra = parse_number(raw.get("consumption_cost_extra_not_in_base_recipe"))
            unit_cost = parse_number(raw.get("theoretical_cost_per_unit"))
            if qty is None:
                continue
            if unit_extra is not None:
                extra += qty * unit_extra
                extra_seen = True
            if unit_cost is not None:
                consumed += qty * unit_cost
                consumed_seen = True
    if not extra_seen or not consumed_seen or consumed == 0:
        return None
    share = extra / consumed * 100.0
    return {
        "extra": extra,
        "extra_text": format_inr(extra),
        "consumed": consumed,
        "consumed_text": format_inr(consumed),
        "share": share,
        "share_text": format_pct(share),
        "source": path.name,
        "note": (
            "At Ideal Plaza the base recipe excludes takeaway packaging and banana leaf. "
            f"Those extras are {format_inr(extra)} of {format_inr(consumed)} consumed cost "
            f"({format_pct(share)})."
        ),
    }
