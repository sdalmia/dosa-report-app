"""Recipe costs from menu_item_cost.csv and ingredient lines.

A blank cost stays blank. Each outlet is compared with its own city's median.
"""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

from app.procurement.numbers import parse_number, percent

_CACHE = {}
_LINE_CACHE = {}

INCOMPLETE_STATUSES = frozenset({"partial_unpriced_ingredients", "no_priced_ingredients"})
FULL_OUTLETS = 3
STALE_GAP = 10
_KIND = {"fully_priced": "full", "estimated": "estimated", "incomplete": "incomplete"}


def procurement_dir():
    return Path(__file__).resolve().parents[2] / "data" / "procurement"


def load_recipes(directory=None):
    directory = Path(directory) if directory else procurement_dir()
    key = str(directory.resolve()) if directory.exists() else str(directory)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    bundle = _read(directory)
    _CACHE[key] = bundle
    return bundle


def clear_caches():
    _CACHE.clear()
    _LINE_CACHE.clear()


def _read(directory):
    estimated = directory / "menu_item_cost_estimated.csv"
    lines_path = directory / "menu_item_cost_lines.csv"
    price_gaps = []
    if estimated.is_file():
        items = _read_estimated_items(estimated)
        estimated_lines = directory / "menu_item_cost_lines_estimated.csv"
        if estimated_lines.is_file():
            lines_path = estimated_lines
            receipts, rates, labels = _scan_estimated_lines(estimated_lines)
            _attach_receipts(items, receipts)
            price_gaps = _price_gaps(directory / "supplier_item_rates.csv", rates, labels)
    else:
        items = _read_items(directory / "menu_item_cost.csv")
    by_outlet = {}
    outlets = {}
    for row in items:
        if row["tab"] != "base" or not row["menu"]:
            continue
        by_outlet[(row["city"], row["outlet"], row["key"])] = row
        outlets.setdefault(row["city"], set()).add(row["outlet"])
    by_city = _apply_full_medians(by_outlet)
    cities = sorted(set(outlets) | {row["city"] for row in by_city.values()}, key=_city_rank)
    return {
        "directory": directory,
        "by_outlet": by_outlet,
        "by_city": by_city,
        "outlets": {city: sorted(names) for city, names in outlets.items()},
        "cities": cities,
        "lines_path": lines_path,
        "price_gaps": price_gaps,
    }


def _city_rank(city):
    key = (city or "").casefold()
    if "kolkata" in key:
        return (0, key)
    if "delhi" in key:
        return (1, key)
    return (9, key)


def _truthy(value):
    return str(value or "").strip().casefold() in {"true", "1", "yes"}


def is_ro_water(name):
    text = " ".join((name or "").casefold().replace(".", " ").split())
    return text in {"ro water", "r o water"}


def split_names(value):
    names = []
    for part in str(value or "").split(";"):
        name = part.strip()
        if name:
            names.append(name)
    return names


def dish_incomplete(excl_count, status):
    if excl_count is not None and excl_count > 0:
        return True
    return (status or "").strip() in INCOMPLETE_STATUSES


def summary_incomplete(compared, fully_priced, names):
    if any(name for name in names if not is_ro_water(name)):
        return True
    if compared is None or fully_priced is None:
        return False
    return fully_priced < compared


def _read_items(path):
    if not path.is_file():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            outlet = (raw.get("outlet") or "").strip()
            if not name or not city or not outlet:
                continue
            excl = parse_number(raw.get("unpriced_excl_ro_water_count"))
            status = (raw.get("cost_status") or "").strip()
            names = split_names(raw.get("unpriced_ingredients"))
            rows.append(
                {
                    "outlet": outlet,
                    "city": city,
                    "item": name,
                    "key": name.casefold(),
                    "tab": (raw.get("recipe_tab") or "base").strip() or "base",
                    "menu": _truthy(raw.get("is_menu_item")),
                    "cost": parse_number(raw.get("cost_per_portion_avg")),
                    "median": parse_number(raw.get("city_baseline_median_cost")),
                    "vs_pct": parse_number(raw.get("vs_city_baseline_pct")),
                    "partial": _truthy(raw.get("has_unpriced_ingredient")),
                    "unpriced_excl": excl,
                    "cost_status": status,
                    "unpriced_names": [name for name in names if not is_ro_water(name)],
                    "incomplete": dish_incomplete(excl, status),
                    "cost_kind": "incomplete" if dish_incomplete(excl, status) else "full",
                    "receipt_title": "",
                }
            )
    return rows


def _read_estimated_items(path):
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            outlet = (raw.get("outlet") or "").strip()
            if not name or not city or not outlet:
                continue
            excl = parse_number(raw.get("still_unpriced_excl_ro_water_count"))
            status = (raw.get("cost_status_estimated") or "").strip()
            kind = _cost_kind(status, excl)
            rows.append(
                {
                    "outlet": outlet,
                    "city": city,
                    "item": name,
                    "key": name.casefold(),
                    "tab": (raw.get("recipe_tab") or "base").strip() or "base",
                    "menu": _truthy(raw.get("is_menu_item")),
                    "cost": parse_number(raw.get("cost_per_portion_estimated")),
                    "median": None,
                    "vs_pct": None,
                    "partial": kind != "full",
                    "unpriced_excl": excl,
                    "cost_status": status,
                    "unpriced_names": [n for n in split_names(raw.get("still_unpriced_ingredients")) if not is_ro_water(n)],
                    "incomplete": kind == "incomplete",
                    "cost_kind": kind,
                    "receipt_title": "",
                }
            )
    return rows


def _cost_kind(status, excl):
    if excl is not None and excl > 0:
        return "incomplete"
    return _KIND.get((status or "").strip(), "incomplete")


def _apply_full_medians(by_outlet):
    """City median from full-cost dishes only. Fewer than 3 outlets leaves it blank."""
    groups = defaultdict(list)
    for row in by_outlet.values():
        groups[(row["city"], row["key"])].append(row)
    by_city = {}
    for (city, key), rows in groups.items():
        full = [row["cost"] for row in rows if row.get("cost_kind") == "full" and row.get("cost") is not None]
        median = statistics.median(full) if len(full) >= FULL_OUTLETS else None
        spread = None
        if median not in (None, 0) and full:
            spread = percent(max(full) - min(full), median)
        by_city[(city, key)] = {
            "city": city,
            "item": rows[0]["item"],
            "key": key,
            "menu": True,
            "median": median,
            "spread": spread,
            "full_outlets": len(full),
            "incomplete": False,
        }
        for row in rows:
            row["median"] = median
            if row.get("cost_kind") == "full" and median not in (None, 0) and row.get("cost") is not None:
                row["vs_pct"] = percent(row["cost"] - median, median)
            else:
                row["vs_pct"] = None
    return by_city


def _attach_receipts(items, receipts):
    for row in items:
        titles = receipts.get((row["outlet"].casefold(), row["key"])) or []
        row["receipt_title"] = " · ".join(titles)


def _scan_estimated_lines(path):
    receipts = defaultdict(list)
    seen = defaultdict(set)
    rates = defaultdict(lambda: defaultdict(list))
    labels = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
                continue
            outlet = (raw.get("outlet") or "").strip()
            item = (raw.get("item_name") or "").strip()
            ingredient = (raw.get("ingredient_name") or "").strip()
            if not outlet or not ingredient:
                continue
            source = (raw.get("price_source") or "").strip().casefold()
            if source == "grn_estimate" and item:
                title = _receipt_title(raw.get("receipt_ref"), ingredient)
                key = (outlet.casefold(), item.casefold())
                if title and title not in seen[key]:
                    seen[key].add(title)
                    receipts[key].append(title)
            if source == "restroworks":
                qty = parse_number(raw.get("ingredient_qty"))
                cost = parse_number(raw.get("ingredient_cost_avg"))
                unit = (raw.get("ingredient_unit") or "").strip()
                city = (raw.get("city") or "").strip()
                if city and qty not in (None, 0) and cost is not None:
                    rate_key = (city, ingredient.casefold(), unit.casefold())
                    labels[rate_key] = ingredient
                    rates[rate_key][outlet].append(cost / qty)
    return receipts, rates, labels


def _receipt_title(ref, ingredient):
    kept = []
    for part in str(ref or "").split(";"):
        text = part.strip()
        low = text.casefold()
        if not text or ".csv" in low or ".xls" in low or "lines," in low:
            continue
        kept.append(text)
    if not kept:
        return ingredient
    return ingredient + " — " + ", ".join(kept)


def _price_gaps(path, rates, labels):
    if not path.is_file():
        return []
    receipts = _receipt_rates(path)
    gaps = []
    for (city, name_key, unit_key), outlets in rates.items():
        outlet_rates = [statistics.median(values) for values in outlets.values() if values]
        if not outlet_rates:
            continue
        recipe_rate = statistics.median(outlet_rates)
        receipt = receipts.get((_receipt_city(city), name_key, unit_key))
        if receipt is None or recipe_rate in (None, 0):
            continue
        gap = percent(receipt["rate"] - recipe_rate, recipe_rate)
        if gap is None or abs(gap) <= STALE_GAP:
            continue
        gaps.append(
            {
                "city": city,
                "item": labels.get((city, name_key, unit_key), name_key),
                "unit": receipt["unit"] or unit_key,
                "recipe_rate": recipe_rate,
                "receipt_rate": receipt["rate"],
                "gap": gap,
            }
        )
    gaps.sort(key=lambda row: (-abs(row["gap"]), row["item"].casefold()))
    return gaps


def _receipt_city(city):
    key = (city or "").casefold()
    if "delhi" in key:
        return "delhi"
    if "kolkata" in key:
        return "kolkata"
    return key


def _receipt_rates(path):
    totals = defaultdict(lambda: [0.0, 0.0, ""])
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            unit = (raw.get("unit") or "").strip()
            rate = parse_number(raw.get("wavg_rate"))
            qty = parse_number(raw.get("qty"))
            if not name or not city or rate is None or qty in (None, 0):
                continue
            bucket = totals[(city.casefold(), name.casefold(), unit.casefold())]
            bucket[0] += qty * rate
            bucket[1] += qty
            bucket[2] = unit
    rates = {}
    for key, (amount, qty, unit) in totals.items():
        if qty:
            rates[key] = {"rate": amount / qty, "unit": unit}
    return rates


def _read_summary(path):
    if not path.is_file():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            if not name or not city:
                continue
            compared = parse_number(raw.get("outlets_compared"))
            fully = parse_number(raw.get("outlets_fully_priced"))
            names = split_names(raw.get("common_unpriced_ingredients"))
            rows.append(
                {
                    "city": city,
                    "item": name,
                    "key": name.casefold(),
                    "menu": _truthy(raw.get("is_menu_item")),
                    "median": parse_number(raw.get("city_baseline_median_cost")),
                    "spread": parse_number(raw.get("spread_within_city_pct")),
                    "low": parse_number(raw.get("min_cost_avg")),
                    "high": parse_number(raw.get("max_cost_avg")),
                    "outlet_min": (raw.get("outlet_min") or "").strip(),
                    "outlet_max": (raw.get("outlet_max") or "").strip(),
                    "compared": compared,
                    "fully_priced": fully,
                    "common_unpriced": names,
                    "with_recipe": parse_number(raw.get("outlets_with_recipe")),
                    "incomplete": summary_incomplete(compared, fully, names),
                }
            )
    return rows


def recipe_lines(bundle, outlet, item):
    """Ingredient rows for one store and item. Blank line costs stay blank."""
    path = bundle.get("lines_path")
    if path is None or not Path(path).is_file():
        return []
    cache_key = (str(path), (outlet or "").casefold(), (item or "").casefold())
    if cache_key in _LINE_CACHE:
        return _LINE_CACHE[cache_key]
    wanted_outlet = (outlet or "").casefold()
    wanted_item = (item or "").casefold()
    rows = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
                continue
            if (raw.get("outlet") or "").strip().casefold() != wanted_outlet:
                continue
            name = (raw.get("item_name") or raw.get("recipe_name") or "").strip()
            if name.casefold() != wanted_item:
                continue
            ingredient = (raw.get("ingredient_name") or "").strip()
            if not ingredient:
                continue
            qty = parse_number(raw.get("ingredient_qty"))
            source = (raw.get("price_source") or "").strip().casefold()
            if source:
                line = parse_number(raw.get("ingredient_cost_estimated_per_portion"))
                if line is None and source == "restroworks":
                    line = parse_number(raw.get("ingredient_cost_avg_per_portion"))
                blank = source == "none" or line is None
            else:
                line = parse_number(raw.get("ingredient_cost_avg_per_portion"))
                if line is None:
                    line = parse_number(raw.get("ingredient_cost_avg"))
                blank = _truthy(raw.get("unpriced")) or line is None
            unit_cost = parse_number(raw.get("est_rate")) if source == "grn_estimate" else None
            if unit_cost is None and line is not None and qty not in (None, 0) and not blank:
                unit_cost = line / qty
            rows.append(
                {
                    "ingredient": ingredient,
                    "qty": qty,
                    "unit": (raw.get("ingredient_unit") or "").strip(),
                    "unit_cost": None if blank else unit_cost,
                    "line_cost": None if blank else line,
                    "unpriced": blank,
                    "estimated": source == "grn_estimate" and not blank,
                    "receipt": _receipt_title(raw.get("receipt_ref"), ingredient) if source == "grn_estimate" and not blank else "",
                    "inactive": _truthy(raw.get("is_inactive_ingredient")),
                }
            )
    _LINE_CACHE[cache_key] = rows
    return rows
