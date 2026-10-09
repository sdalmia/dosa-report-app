"""Recipe cost for the menu page.

Stock Recipe cost excludes takeaway packaging and banana leaf.
Recipe consumption cost is the billing-driven cost at Ideal Plaza only.
Selling price is not in these files, so margin stays blank.
"""

import csv
from pathlib import Path

from app.procurement.loader import newest_file, posist_daily_path, procurement_dir, source_name
from app.procurement.numbers import format_inr, format_pct, format_period, format_qty, money_pair, parse_number, parse_period, pct_pair

RECIPE_LABEL = "recipe cost excl. packaging"


def recipe_costs(directory=None, outlet=None, menu_item=None, include_lines=False, include_non_menu=False):
    """CSV-backed recipe cost. Another blueprint can import this.

    `outlet` matches the deployment name (Ideal Plaza or Connaught Place).
    Margin is always null: these files have no selling price.
    """
    directory = Path(directory) if directory else procurement_dir()
    item_path = newest_file(directory, "recipe_cost_by_item*.csv")
    lines_path = newest_file(directory, "recipe_cost_lines*.csv")
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
            "missing_source": "recipe_cost_by_item.csv",
            "margin": None,
            "margin_unavailable": "Recipe cost file is missing, so margin is blank.",
            "items": [],
            "outlets": [],
        }
    items = _read_stock_items(item_path)
    if not include_non_menu:
        items = [row for row in items if row["is_menu_item"]]
    if outlet:
        wanted = outlet.casefold()
        items = [row for row in items if wanted in row["deployment"].casefold() or wanted in row["city"].casefold()]
    if menu_item:
        wanted_item = menu_item.casefold()
        items = [row for row in items if row["menu_item"].casefold() == wanted_item]
    outlets = sorted({row["deployment"] for row in _read_stock_items(item_path)})
    packaging = _packaging_gap(check_path)
    payload = {
        "available": True,
        "label": RECIPE_LABEL,
        "missing_source": "",
        "source": item_path.name,
        "lines_source": lines_path.name if lines_path else "",
        "outlets": outlets,
        "other_outlets_missing": (
            "Stock recipe cost is on file for Ideal Plaza and Connaught Place only. "
            "Other outlets are not in recipe_cost_by_item.csv."
        ),
        "basis": (
            "Restroworks Stock Recipe, average price and last price. "
            "This is recipe cost excl. packaging: the base recipe omits takeaway packaging and banana leaf."
        ),
        "margin": None,
        "margin_unavailable": _margin_reason(),
        "item_count": len(items),
        "items_with_unpriced": sum(1 for row in items if (row.get("unpriced_ingredient_count") or 0) > 0),
        "items": items,
        "packaging_gap": packaging,
        "consumption": _consumption_block(consumption_path),
    }
    if include_lines and lines_path and menu_item:
        payload["lines"] = _read_stock_lines(lines_path, menu_item, outlet)
    elif include_lines:
        payload["lines"] = []
        payload["lines_note"] = "Pass item= to include ingredient lines for one recipe."
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
    payload["source"] = source_name(bundle, "recipe_items") or payload.get("source") or ""
    rows = []
    for item in payload.get("items") or []:
        rows.append(
            {
                "deployment": item["deployment"],
                "city": item["city"],
                "menu_item": item["menu_item"],
                "unit": item["recipe_unit"],
                "avg": money_pair(item["cost_per_unit_avg_price"]),
                "last": money_pair(item["cost_per_unit_last_price"]),
                "gap": pct_pair(item["last_vs_avg_pct"]),
                "unpriced": item["unpriced_ingredient_count"] or 0,
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


def _margin_reason():
    mix_label = _menu_mix_period()
    if mix_label:
        return (
            "No selling price is in recipe_cost_by_item.csv or recipe_consumption_cost_ideal_plaza.csv. "
            f"menu_mix.csv covers {mix_label}, which is not the recipe-consumption window, so it is not used. "
            "Margin is blank."
        )
    return (
        "No selling price column is in the recipe files, and menu_mix.csv was not found. Margin is blank."
    )


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
            rows.append(
                {
                    "deployment": (raw.get("deployment") or "").strip(),
                    "city": (raw.get("city") or "").strip(),
                    "recipe_code": (raw.get("recipe_code") or "").strip(),
                    "menu_item": name,
                    "recipe_unit": (raw.get("recipe_unit") or "").strip(),
                    "is_menu_item": flag == "true",
                    "cost_per_unit_avg_price": parse_number(raw.get("cost_per_unit_avg_price")),
                    "cost_per_unit_last_price": parse_number(raw.get("cost_per_unit_last_price")),
                    "last_vs_avg_pct": parse_number(raw.get("last_vs_avg_pct")),
                    "ingredient_count": parse_number(raw.get("ingredient_count")),
                    "unpriced_ingredient_count": parse_number(raw.get("unpriced_ingredient_count")),
                    "unpriced_ingredient_count_last": parse_number(raw.get("unpriced_ingredient_count_last")),
                    "selling_price": None,
                    "margin": None,
                    "label": RECIPE_LABEL,
                }
            )
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
            "missing_source": "recipe_consumption_cost_ideal_plaza.csv",
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
        "scope_note": "Actual consumed recipe cost is Ideal Plaza only, for the period on this file. Connaught Place does not have this export.",
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
            f"Those extras are {format_inr(extra)} of {format_inr(consumed)} theoretical consumed cost "
            f"({format_pct(share)}), from {path.name}."
        ),
    }
