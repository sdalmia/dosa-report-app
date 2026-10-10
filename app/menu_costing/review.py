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
    lines_path = _lines_path(directory)
    batch_path = directory / "batch_recipes.csv"
    key = (str(directory), chosen, _file_token(lines_path), _file_token(batch_path))
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


def _lines_path(directory):
    path = directory / "menu_item_cost_lines.csv"
    if path.is_file():
        return path
    estimated = directory / "menu_item_cost_lines_estimated.csv"
    return estimated if estimated.is_file() else path


def _file_token(path):
    if path is None or not Path(path).is_file():
        return None
    st = Path(path).stat()
    return (str(Path(path).resolve()), st.st_mtime_ns, st.st_size)


def _scan(directory, names):
    hot_names = {_key(name) for name in names if _key(name)}
    if not hot_names:
        return set()
    lines_path = _lines_path(directory)
    batches = {}
    if lines_path.is_file():
        _read_batches(lines_path, batches)
    _read_batch_csv(directory / "batch_recipes.csv", batches)
    hot_by_city = {city: _expand(hot_names, items) for city, items in batches.items()}
    found = set()
    if lines_path.is_file():
        _read_dishes(lines_path, hot_names, hot_by_city, found)
    return found


def _read_batches(path, batches):
    """Non-menu recipes only. Menu dishes are matched on a second pass."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if _truthy(raw.get("is_menu_item")):
                continue
            city, item, ingredient = _line_identity(raw)
            if not city:
                continue
            batches.setdefault(city, {}).setdefault(item, set()).add(ingredient)


def _read_dishes(path, hot_names, hot_by_city, found):
    """Record a dish key when one ingredient is under review. Do not keep the recipe."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if not _truthy(raw.get("is_menu_item")):
                continue
            city, item, ingredient = _line_identity(raw)
            if not city:
                continue
            if (city, item) in found:
                continue
            hot = hot_by_city.get(city) or hot_names
            if _matches(ingredient, hot):
                found.add((city, item))


def _line_identity(raw):
    if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
        return "", "", ""
    if _truthy(raw.get("is_inactive_ingredient")):
        return "", "", ""
    city = (raw.get("city") or "").strip()
    item = (raw.get("item_name") or raw.get("recipe_name") or "").strip()
    ingredient = (raw.get("ingredient_name") or "").strip()
    if not city or not item or not ingredient:
        return "", "", ""
    return city, item.casefold(), ingredient


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
