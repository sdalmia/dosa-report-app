"""Popularity versus contribution for one menu.

Popularity is the item's share of orders. Orders are the export's order
counts, not quantity. When a recipe-cost file is on file, contribution is
the margin per order: Gross per order minus the base recipe cost per
portion. Stores with no numeric cost are left out of that margin, and their
sales are left out with them. Without a recipe file, contribution is share
of Gross.
"""

from xml.sax.saxutils import escape

from app.menu_ops.cost import load_menu_costs, match_outlet
from app.menu_ops.formatutil import format_count, format_inr, format_pct, format_period, format_sales, format_stamp
from app.menu_ops.loader import (
    _same_store,
    coming_stores,
    is_ideal_plaza,
    item_key,
    load_categories,
    load_regions,
    load_sales,
    menu_directory,
    procurement_directory,
    region_for_store,
    store_coverage,
)

NO_CATEGORY = "__none__"
NO_REGION = "__none__"
POPULARITY_OF_EQUAL = 0.70

QUADRANT_LABELS = {
    "star": "Star",
    "plowhorse": "Plowhorse",
    "puzzle": "Puzzle",
    "dog": "Dog",
}

MARGIN_INFO = (
    "Margin is Gross per order minus the base recipe cost per portion. "
    "The base cost leaves out packaging. A partial cost is missing at least one ingredient price, so the margin is high. "
    "Items with no exact recipe name, and outlets with no priced ingredients, stay empty. "
    "When several outlets in the same city are included, the cost is the order-weighted average of the outlets that have a cost, "
    "and the other outlets' Gross and orders are left out of that margin. "
    "Delhi and Kolkata are not averaged together. "
    "Swiggy and Zomato at Ideal Plaza use the takeout and delivery recipe, which includes packaging. "
    "Those costs are shown beside the item and are not subtracted from this Gross, because these sales are not split by channel. "
    "The lowest, city median and highest are within that city. They are not the margin."
)

CITY_RANK_NOTE = (
    "Delhi NCR and Kolkata are ranked separately. "
    "A cost is compared with that city's median, not with the other city. "
    "Delhi recipes use three chutneys per dish and Kolkata uses one, so a higher Delhi cost is expected."
)


def _city_rank_note(costs):
    """Say why the two cities are not placed on one cost or margin scale."""
    if not costs.get("present"):
        return ""
    cities = {str(value).strip() for value in (costs.get("outlet_city") or {}).values() if str(value).strip()}
    if len(cities) < 2:
        return ""
    summary = costs.get("summary") or {}
    east = _summary_median(summary, "Onion Uttapam", "Kolkata")
    north = _summary_median(summary, "Onion Uttapam", "Delhi NCR")
    comparison = ""
    if east not in (None, 0) and north is not None:
        comparison = (
            f" Onion Uttapam's city median is {format_inr(north)} in Delhi NCR and {format_inr(east)} in Kolkata."
        )
    return CITY_RANK_NOTE + comparison


def _summary_median(summary, item, city):
    row = summary.get((item_key(item), city.casefold())) or {}
    return row.get("median")


def build_menu(
    directory=None,
    posist=None,
    procurement=None,
    category="",
    region="",
    store="",
    quadrant="",
):
    directory = directory or menu_directory()
    regions, region_warnings = load_regions(posist)
    rows, warnings, sources = load_sales(directory, posist_labels=list(regions))
    catalogue = load_categories(directory)
    costs = load_menu_costs(procurement or procurement_directory())
    warnings = list(warnings) + list(region_warnings)
    margin_mode = bool(costs.get("present"))

    enriched = []
    for row in rows:
        label, region_name = region_for_store(row["store"], regions)
        copied = dict(row)
        copied["posist"] = label
        copied["region"] = region_name or ""
        enriched.append(copied)

    category_map, show_category = _category_map(enriched, catalogue)
    outlets = costs.get("outlets") or []
    outlet_for_store = {name: match_outlet(name, outlets) for name in {row["store"] for row in enriched}}

    category_names = sorted({category_map.get(item_key(row["item"]), "") for row in enriched if category_map.get(item_key(row["item"]))})
    region_names = sorted({row["region"] for row in enriched if row["region"]})
    sales_names = {row["store"] for row in enriched}
    coming = coming_stores(sales_names, regions) if rows else []
    if regions:
        store_names = sorted(regions, key=str.casefold)
    else:
        store_names = sorted(sales_names)
    has_unknown_region = any(not row["region"] for row in enriched)
    has_unknown_category = show_category and any(not category_map.get(item_key(row["item"])) for row in enriched)

    filtered = []
    for row in enriched:
        if store and not _same_store(row["store"], store, list(regions) or [row["store"], store]):
            continue
        if region == NO_REGION and row["region"]:
            continue
        if region and region != NO_REGION and row["region"] != region:
            continue
        filtered.append(row)

    shown_coming = list(coming)
    if region == NO_REGION:
        shown_coming = [name for name in coming if not regions.get(name)]
    elif region:
        shown_coming = [name for name in coming if (regions.get(name) or "") == region]
    store_coming = bool(store) and any(_same_store(store, name, list(regions) or [store]) for name in coming)
    ideal_only = bool(filtered) and all(is_ideal_plaza(row["store"]) for row in filtered)
    items = _aggregate(filtered, category_map, costs, margin_mode, outlet_for_store, ideal_only)
    if show_category and category == NO_CATEGORY:
        items = [item for item in items if not item["category"]]
    elif show_category and category:
        items = [item for item in items if item["category"] == category]

    classified, cutoffs = _classify(items, margin_mode)
    counts = {name: 0 for name in QUADRANT_LABELS}
    counts["unclassified"] = 0
    for item in items:
        if item["quadrant"]:
            counts[item["quadrant"]] += 1
        else:
            counts["unclassified"] += 1

    listed = items
    if quadrant in QUADRANT_LABELS:
        listed = [item for item in items if item["quadrant"] == quadrant]
    elif quadrant == "unclassified":
        listed = [item for item in items if not item["quadrant"]]

    listed = sorted(
        listed,
        key=lambda item: (
            item.get("city") or "zzz",
            item["quadrant"] or "zzz",
            -(item["gross"] if item["gross"] is not None else float("-inf")),
            item["item"].casefold(),
        ),
    )
    plots = _plots(items, cutoffs, margin_mode)
    unmatched_items, unmatched_names, unmatched_outlets = _unmatched(filtered, costs, outlet_for_store)
    coverage = store_coverage({row["store"] for row in enriched}, regions) if rows else None
    return {
        "sources": sources,
        "warnings": warnings,
        "period_label": _period_label(rows),
        "category_source": catalogue,
        "recipe": costs,
        "margin_mode": margin_mode,
        "margin_note": _margin_note(costs, margin_mode),
        "margin_info": MARGIN_INFO if margin_mode else "",
        "cost_as_of": format_stamp(costs.get("as_of")) if margin_mode else "",
        "category": category if show_category else "",
        "region": region,
        "store": store,
        "quadrant": quadrant,
        "category_names": category_names if show_category else [],
        "show_category": show_category,
        "region_names": region_names,
        "store_names": store_names,
        "coming_stores": shown_coming,
        "store_coming": store_coming,
        "has_unknown_region": has_unknown_region,
        "has_unknown_category": has_unknown_category,
        "matched_categories": sum(1 for key in {item_key(row["item"]) for row in enriched} if key in category_map),
        "cutoffs": [_present_cutoff(cutoff, margin_mode) for cutoff in cutoffs],
        "counts": counts,
        "classified": len(classified),
        "items": [_present_item(item, margin_mode) for item in listed],
        "plots": plots,
        "gross_total": format_sales(_known_sum(classified, "gross")),
        "orders_total": format_count(_known_sum(classified, "orders")),
        "empty_sales": not rows,
        "ideal_only": ideal_only and margin_mode,
        "unmatched_items": unmatched_items,
        "unmatched_names": unmatched_names,
        "unmatched_outlets": unmatched_outlets,
        "coverage_label": _coverage_label(coverage),
        "partial_any": any(item.get("partial") for item in items),
        "city_note": _city_rank_note(costs) if margin_mode else "",
    }


def _category_map(rows, catalogue):
    """Sales category column wins. An all-empty column hides the filter."""
    has_column = any(row.get("category_from_sales") is not None for row in rows)
    if has_column:
        filled = {}
        for row in rows:
            name = row.get("category_from_sales") or ""
            if name:
                filled[item_key(row["item"])] = name
        return filled, bool(filled)
    borrowed = dict(catalogue.get("by_item") or {})
    return borrowed, bool(borrowed)


def _aggregate(rows, categories, costs, margin_mode, outlet_for_store, ideal_only):
    grouped = {}
    for row in rows:
        city = _city_for(row["store"], outlet_for_store, costs) if margin_mode else ""
        grouped.setdefault((row["item"], city), []).append(row)
    items = []
    for (name, city), group in grouped.items():
        gross = _sum_known(group, "gross")
        orders = _sum_known(group, "orders")
        key = item_key(name)
        category = categories.get(key, "")
        regions = sorted({row["region"] for row in group if row["region"]})
        margin = _margin_for_group(name, city, group, costs, outlet_for_store) if margin_mode else _empty_margin()
        file_contribution = group[0].get("contribution_pct") if len(group) == 1 else None
        summary = _summary_for(costs, key, city) if margin_mode else None
        channels = (costs.get("channels") or {}).get(key) if ideal_only else None
        items.append(
            {
                "item": name,
                "city": city,
                "gross": gross,
                "orders": orders,
                "category": category,
                "regions": regions,
                "region_missing": any(not row["region"] for row in group),
                "stores": sorted({row["store"] for row in group}),
                "file_contribution": file_contribution,
                "quadrant": "",
                "popularity": None,
                "contribution": None,
                "reason": "",
                "margin_mode": margin_mode,
                "summary": summary,
                "channel_costs": channels,
                **margin,
            }
        )
    return items


def _city_for(store, outlet_for_store, costs):
    outlet = outlet_for_store.get(store)
    if not outlet:
        return ""
    return str((costs.get("outlet_city") or {}).get(outlet) or "").strip()


def _summary_for(costs, key, city):
    summary = costs.get("summary") or {}
    found = summary.get((key, city.casefold()))
    if found:
        return found
    if city:
        return None
    matches = [row for (item, _row_city), row in summary.items() if item == key]
    if len(matches) == 1:
        return matches[0]
    return None


def _empty_margin():
    return {
        "unit_margin": None,
        "recipe_cost": None,
        "partial": False,
        "cost_coverage": "",
        "cost_stores": 0,
        "item_stores_for_cost": 0,
        "margin_reason": "",
        "coverage_note": "",
        "city_median": None,
        "vs_city": None,
    }


def _margin_for_group(name, city, group, costs, outlet_for_store):
    used = []
    gaps = []
    for row in group:
        outlet = outlet_for_store.get(row["store"])
        record = None
        if outlet:
            record = (costs.get("by_outlet") or {}).get(outlet, {}).get(item_key(name))
        if record is None or record.get("cost") is None:
            gaps.append(_gap_reason(outlet, record))
            continue
        if row.get("gross") is None or row.get("orders") is None:
            gaps.append("Gross or orders are missing, so this store is left out of the margin.")
            continue
        if row.get("orders") == 0:
            gaps.append("Orders are 0, so margin per order is empty.")
            continue
        used.append((row, record))

    store_total = len({row["store"] for row in group})
    if not used:
        return {
            **_empty_margin(),
            "cost_coverage": f"0 of {store_total} stores" if store_total else "",
            "item_stores_for_cost": store_total,
            "margin_reason": _combine_gaps(gaps),
        }
    unit_margin, recipe_cost, partial = _weighted_margin(used)
    used_stores = len({row["store"] for row, _record in used})
    note = f"Margin uses {used_stores} of {store_total} stores." if used_stores != store_total else ""
    city_median = _group_city_median(name, city, used, costs)
    vs_city = None
    if city_median not in (None, 0) and recipe_cost is not None:
        vs_city = (recipe_cost - city_median) / city_median * 100.0
    return {
        "unit_margin": unit_margin,
        "recipe_cost": recipe_cost,
        "partial": partial,
        "cost_coverage": f"{used_stores} of {store_total} stores" if store_total else "",
        "cost_stores": used_stores,
        "item_stores_for_cost": store_total,
        "margin_reason": "",
        "coverage_note": note,
        "city_median": city_median,
        "vs_city": vs_city,
    }


def _group_city_median(name, city, used, costs):
    summary = _summary_for(costs, item_key(name), city)
    if summary and summary.get("median") is not None:
        return summary["median"]
    values = [record.get("city_median") for _row, record in used if record.get("city_median") is not None]
    if values and all(value == values[0] for value in values):
        return values[0]
    return None


def _weighted_margin(pairs):
    if not pairs:
        return None, None, False
    gross = sum(row["gross"] for row, _record in pairs)
    orders = sum(row["orders"] for row, _record in pairs)
    cost_total = sum(record["cost"] * row["orders"] for row, record in pairs)
    return (gross - cost_total) / orders, cost_total / orders, any(record["partial"] for _row, record in pairs)


def _gap_reason(outlet, record):
    if not outlet:
        return "This outlet is not on the recipe list, so the margin is empty."
    if record is None:
        return "No recipe uses this exact item name, so the margin is empty."
    return "This outlet has no priced ingredients, so the margin is empty."


def _combine_gaps(gaps):
    unique = list(dict.fromkeys(gaps))
    if not unique:
        return "Recipe cost is not available, so the margin is empty."
    if len(unique) == 1:
        return unique[0]
    return "Recipe cost is not available for these stores, so the margin is empty."


def _sum_known(group, field):
    values = [row.get(field) for row in group]
    if any(value is None for value in values):
        return None
    return float(sum(values))


def _known_sum(items, field):
    values = [item.get(field) for item in items]
    if not values or any(value is None for value in values):
        return None
    return float(sum(values))


def _classify(items, margin_mode):
    """Rank each city on its own. A blank city is its own group, not mixed in."""
    buckets = {}
    for item in items:
        buckets.setdefault(item.get("city") or "", []).append(item)
    classified = []
    cutoffs = []
    for city in sorted(buckets, key=lambda name: (name == "", name.casefold())):
        done, cutoff = _classify_city(buckets[city], margin_mode)
        classified.extend(done)
        cutoff["city"] = city
        cutoffs.append(cutoff)
    return classified, cutoffs


def _classify_city(items, margin_mode):
    classified = []
    for item in items:
        if item["orders"] is None:
            item["reason"] = "Orders are missing, so popularity is empty."
            continue
        if margin_mode:
            if item["unit_margin"] is None:
                item["reason"] = item.get("margin_reason") or "Margin is empty."
                continue
        elif item["gross"] is None:
            item["reason"] = "Gross is missing, so revenue contribution is empty."
            continue
        classified.append(item)

    cutoff = {"popularity": None, "contribution": None, "unit": "percent", "city": ""}
    if not classified:
        return classified, cutoff
    count = len(classified)
    order_total = sum(item["orders"] for item in classified)
    cutoff["popularity"] = POPULARITY_OF_EQUAL * (100.0 / count)
    if order_total == 0:
        for item in classified:
            item["reason"] = "Orders total 0, so popularity is empty."
            item["quadrant"] = ""
        return [], cutoff

    if margin_mode:
        cutoff["contribution"] = sum(item["unit_margin"] for item in classified) / count
        cutoff["unit"] = "inr"
    else:
        gross_total = sum(item["gross"] for item in classified)
        cutoff["contribution"] = 100.0 / count
        if gross_total == 0:
            for item in classified:
                item["reason"] = "Gross totals 0, so revenue contribution is empty."
                item["quadrant"] = ""
            return [], cutoff

    for item in classified:
        item["popularity"] = item["orders"] / order_total * 100.0
        high_popularity = item["popularity"] >= cutoff["popularity"]
        if margin_mode:
            item["contribution"] = item["unit_margin"]
            high_contribution = item["unit_margin"] >= cutoff["contribution"]
        else:
            item["contribution"] = item["gross"] / gross_total * 100.0
            high_contribution = item["contribution"] >= cutoff["contribution"]
        if high_popularity and high_contribution:
            item["quadrant"] = "star"
        elif high_popularity:
            item["quadrant"] = "plowhorse"
        elif high_contribution:
            item["quadrant"] = "puzzle"
        else:
            item["quadrant"] = "dog"
    return classified, cutoff


def _plots(items, cutoffs, margin_mode):
    plots = []
    for cutoff in cutoffs:
        city = cutoff.get("city") or ""
        points = [item for item in items if item["quadrant"] and (item.get("city") or "") == city]
        svg = scatter_svg(points, cutoff, margin_mode)
        if not svg:
            continue
        title = "Popularity vs contribution"
        if city:
            title = f"{title} · {city}"
        plots.append({"city": city, "title": title, "svg": svg})
    return plots


def _present_cutoff(cutoff, margin_mode):
    contribution = cutoff.get("contribution")
    if margin_mode:
        contribution_text = format_inr(contribution)
    else:
        contribution_text = format_pct(contribution)
    return {
        "city": cutoff.get("city") or "",
        "popularity": cutoff.get("popularity"),
        "contribution": contribution,
        "popularity_text": format_pct(cutoff.get("popularity")),
        "contribution_text": contribution_text,
    }


def _unmatched(rows, costs, outlet_for_store):
    if not costs.get("present"):
        return 0, [], []
    names = {}
    for row in rows:
        names.setdefault(item_key(row["item"]), row["item"])
    recipe_names = costs.get("item_names") or set()
    missing = sorted((names[key] for key in names if key not in recipe_names), key=str.casefold)
    outlets = sorted(
        {row["store"] for row in rows if not outlet_for_store.get(row["store"])},
        key=str.casefold,
    )
    return len(missing), missing, outlets


def _coverage_label(coverage):
    if not coverage:
        return ""
    hit, total = coverage
    return f"{hit} of {total} stores loaded"


def _period_label(rows):
    starts = {row["period_start"] for row in rows if row.get("period_start")}
    ends = {row["period_end"] for row in rows if row.get("period_end")}
    if len(starts) == 1 and len(ends) == 1:
        return format_period(next(iter(starts)), next(iter(ends)))
    if starts and ends:
        return format_period(min(starts), max(ends))
    return ""


def _margin_note(costs, margin_mode):
    if margin_mode:
        when = format_stamp(costs.get("as_of"))
        dated = f" as of {when}" if when else ""
        return f"Margin is Gross per order minus the base recipe cost per portion{dated}. The base cost is excl. packaging."
    if costs.get("found"):
        return "A recipe-cost file is on file, but no base costs could be read, so true margin is not on file."
    return "True margin is not on file. Contribution is share of Gross."


def _present_item(item, margin_mode):
    if margin_mode:
        contribution = format_inr(item["contribution"])
    else:
        contribution = format_pct(item["contribution"])
    regions = list(item["regions"])
    if item["region_missing"]:
        regions.append("Region not on file")
    summary = item.get("summary") or {}
    return {
        "item": item["item"],
        "city": item.get("city") or "",
        "quadrant": item["quadrant"],
        "quadrant_label": QUADRANT_LABELS.get(item["quadrant"], ""),
        "gross": format_sales(item["gross"]),
        "orders": format_count(item["orders"]),
        "popularity": format_pct(item["popularity"]),
        "contribution": contribution,
        "margin": format_inr(item["unit_margin"]),
        "recipe_cost": format_inr(item["recipe_cost"]),
        "partial": bool(item.get("partial")),
        "city_median": format_inr(item.get("city_median")) if item.get("city_median") is not None else "",
        "vs_city": format_pct(item.get("vs_city")) if item.get("vs_city") is not None else "",
        "cost_coverage": item.get("cost_coverage") or "",
        "coverage_note": item.get("coverage_note") or "",
        "file_contribution": format_pct(item["file_contribution"]),
        "category": item["category"],
        "regions": ", ".join(regions),
        "stores": item["stores"],
        "store_count": len(item["stores"]),
        "reason": item["reason"],
        "x": item["popularity"],
        "y": item["contribution"],
        "cost_min": format_inr(summary.get("min")) if summary else "",
        "cost_median": format_inr(summary.get("median")) if summary else "",
        "cost_max": format_inr(summary.get("max")) if summary else "",
        "channel_costs": _present_channels(item.get("channel_costs")),
    }


def _present_channels(record):
    if not record:
        return None
    takeout = record.get("takeout")
    delivery = record.get("delivery")
    if takeout is None and delivery is None:
        return None
    same = takeout is not None and delivery is not None and round(float(takeout), 2) == round(float(delivery), 2)
    return {
        "takeout": format_inr(takeout),
        "delivery": format_inr(delivery),
        "same": same,
        "packaging": format_inr(takeout) if same else "",
    }


def scatter_svg(points, cutoff, margin_mode):
    plotted = [point for point in points if point.get("popularity") is not None and point.get("contribution") is not None]
    if not plotted:
        return ""
    width, height = 360, 280
    left, right, top, bottom = 44, 12, 16, 32
    xs = [point["popularity"] for point in plotted]
    ys = [point["contribution"] for point in plotted]
    x_cut = cutoff.get("popularity")
    y_cut = cutoff.get("contribution")
    x_max = max(xs + ([x_cut] if x_cut is not None else []))
    y_max = max(ys + ([y_cut] if y_cut is not None else []))
    y_min = min([0.0] + ys + ([y_cut] if y_cut is not None else []))
    x_max = x_max * 1.08 if x_max else 1
    if y_max == y_min:
        y_max = y_min + 1
    span = y_max - y_min
    y_max = y_max + span * 0.08
    y_min = y_min - span * 0.04

    def x_pos(value):
        return left + (value / x_max) * (width - left - right)

    def y_pos(value):
        return top + (1 - (value - y_min) / (y_max - y_min)) * (height - top - bottom)

    parts = [
        f'<svg class="matrix" viewBox="0 0 {width} {height}" role="img">',
        "<title>Popularity versus contribution</title>",
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" class="axis"/>',
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" class="axis"/>',
    ]
    if x_cut is not None:
        x_line = x_pos(x_cut)
        parts.append(f'<line x1="{x_line:.1f}" y1="{top}" x2="{x_line:.1f}" y2="{height - bottom}" class="cutoff"/>')
    if y_cut is not None:
        y_line = y_pos(y_cut)
        parts.append(f'<line x1="{left}" y1="{y_line:.1f}" x2="{width - right}" y2="{y_line:.1f}" class="cutoff"/>')
    for point in plotted:
        css = point["quadrant"] or "dog"
        cx = x_pos(point["popularity"])
        cy = y_pos(point["contribution"])
        label = escape(point["item"])
        parts.append(
            f'<circle class="dot {css}" cx="{cx:.1f}" cy="{cy:.1f}" r="4">'
            f"<title>{label}</title></circle>"
        )
    y_name = "Margin per order" if margin_mode else "Revenue contribution"
    parts.append(f'<text x="{width / 2:.0f}" y="{height - 6}" text-anchor="middle" class="axis-label">Popularity (share of orders)</text>')
    parts.append(f'<text x="12" y="{height / 2:.0f}" text-anchor="middle" class="axis-label" transform="rotate(-90 12 {height / 2:.0f})">{escape(y_name)}</text>')
    parts.append("</svg>")
    return "".join(parts)
