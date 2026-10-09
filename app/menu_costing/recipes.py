"""Recipe costs from menu_item_cost.csv and ingredient lines.

A blank cost stays blank. Each outlet is compared with its own city's median.
"""

import csv
from pathlib import Path

from app.procurement.numbers import parse_number

_CACHE = {}
_LINE_CACHE = {}

INCOMPLETE_STATUSES = frozenset({"partial_unpriced_ingredients", "no_priced_ingredients"})


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
    items = _read_items(directory / "menu_item_cost.csv")
    summary = _read_summary(directory / "menu_item_cost_summary.csv")
    by_outlet = {}
    outlets = {}
    for row in items:
        if row["tab"] != "base" or not row["menu"]:
            continue
        by_outlet[(row["city"], row["outlet"], row["key"])] = row
        outlets.setdefault(row["city"], set()).add(row["outlet"])
    by_city = {}
    for row in summary:
        if not row["menu"]:
            continue
        by_city[(row["city"], row["key"])] = row
    cities = sorted(set(outlets) | {row["city"] for row in summary}, key=_city_rank)
    return {
        "directory": directory,
        "by_outlet": by_outlet,
        "by_city": by_city,
        "outlets": {city: sorted(names) for city, names in outlets.items()},
        "cities": cities,
        "lines_path": directory / "menu_item_cost_lines.csv",
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
                    "unpriced_names": names,
                    "incomplete": dish_incomplete(excl, status),
                }
            )
    return rows


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
            line = parse_number(raw.get("ingredient_cost_avg_per_portion"))
            if line is None:
                line = parse_number(raw.get("ingredient_cost_avg"))
            unit_cost = None
            if line is not None and qty not in (None, 0):
                unit_cost = line / qty
            rows.append(
                {
                    "ingredient": ingredient,
                    "qty": qty,
                    "unit": (raw.get("ingredient_unit") or "").strip(),
                    "unit_cost": unit_cost,
                    "line_cost": line,
                    "unpriced": _truthy(raw.get("unpriced")),
                    "inactive": _truthy(raw.get("is_inactive_ingredient")),
                }
            )
    _LINE_CACHE[cache_key] = rows
    return rows
