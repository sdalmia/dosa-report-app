"""Dishes whose recipe quantities are under review.

Edit UNDER_REVIEW when Sailesh corrects a quantity. A dish is included when a
base-recipe line uses one of these ingredients, or uses a batch item whose own
recipe uses one of them. Clear the tuple to clear the badge.
"""

import csv
from pathlib import Path

UNDER_REVIEW = (
    "Coconut Shredded",
    "Sambar Bucket",
    "Sambar Bucket - Delhi",
    "Jain Sambar Bucket",
    "Jain Sambar - Delhi",
    "Special Daal Bucket",
)

BADGE = "Recipe quantity under review"
NOTE = (
    "Food cost for these dishes is likely overstated. "
    "Recipe quantities are being corrected by Sailesh."
)

_CACHE = {}


def clear_review_cache():
    _CACHE.clear()


def review_dishes(directory=None, names=None):
    """Set of (city, item key) whose live base recipe is under review."""
    directory = Path(directory) if directory else _procurement_dir()
    chosen = tuple(names) if names is not None else UNDER_REVIEW
    key = (str(directory), chosen)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    found = _scan(directory, chosen)
    _CACHE[key] = found
    return found


def dish_under_review(city, item, directory=None, names=None):
    if not city or not item:
        return False
    return ((city or "").strip(), (item or "").strip().casefold()) in review_dishes(directory, names)


def highest_food_cost(rows, limit=8):
    """Highest food cost % . Dishes under review stay off this ranking.

    Their food cost % is still shown on the dish card. A blank percent is left out.
    """
    ranked = [
        row
        for row in rows
        if row.get("food_pct") is not None and not row.get("under_review")
    ]
    ranked.sort(key=lambda row: (-float(row["food_pct"]), (row.get("item") or "").casefold()))
    return ranked[:limit]


def _procurement_dir():
    return Path(__file__).resolve().parents[2] / "data" / "procurement"


def _scan(directory, names):
    hot_names = {_key(name) for name in names if _key(name)}
    if not hot_names:
        return set()
    lines_path = directory / "menu_item_cost_lines.csv"
    if not lines_path.is_file():
        lines_path = directory / "menu_item_cost_lines_estimated.csv"
    batches = {}
    dishes = {}
    if lines_path.is_file():
        _read_lines(lines_path, batches, dishes)
    _read_batch_csv(directory / "batch_recipes.csv", batches)
    hot_by_city = {}
    for city in set(batches) | set(dishes):
        hot_by_city[city] = _expand(hot_names, batches.get(city) or {})
    found = set()
    for city, items in dishes.items():
        hot = hot_by_city.get(city) or hot_names
        for item_key, ingredients in items.items():
            if any(_matches(name, hot) for name in ingredients):
                found.add((city, item_key))
    return found


def _read_lines(path, batches, dishes):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
                continue
            if _truthy(raw.get("is_inactive_ingredient")):
                continue
            city = (raw.get("city") or "").strip()
            item = (raw.get("item_name") or raw.get("recipe_name") or "").strip()
            ingredient = (raw.get("ingredient_name") or "").strip()
            if not city or not item or not ingredient:
                continue
            target = dishes if _truthy(raw.get("is_menu_item")) else batches
            target.setdefault(city, {}).setdefault(item.casefold(), set()).add(ingredient)


def _read_batch_csv(path, batches):
    if not path.is_file():
        return
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            city = (raw.get("city") or "").strip()
            item = (raw.get("batch_item") or "").strip()
            ingredient = (raw.get("ingredient") or "").strip()
            if not city or not item or not ingredient:
                continue
            batches.setdefault(city, {}).setdefault(item.casefold(), set()).add(ingredient)


def _expand(hot_names, batches):
    """Ingredient and batch names that reach an under-review ingredient."""
    hot = set(hot_names)
    changed = True
    while changed:
        changed = False
        for item_key, ingredients in batches.items():
            if item_key in hot:
                continue
            if any(_matches(name, hot) for name in ingredients):
                hot.add(item_key)
                changed = True
    return hot


def _matches(name, hot):
    key = _key(name)
    if not key:
        return False
    if key in hot:
        return True
    base = key.split("(")[0].strip()
    return base in hot and base != key


def _key(name):
    return " ".join((name or "").casefold().split())


def _truthy(value):
    return str(value or "").strip().casefold() in {"true", "1", "yes"}
