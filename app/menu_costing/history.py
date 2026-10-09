"""Monthly recipe snapshots from data/procurement/history/YYYY-MM/.

Each folder is one month. Cost per portion comes from that month's
menu_item_cost.csv. Ingredient lines are read only for the dish being compared.
"""

import csv
import re
from datetime import date
from pathlib import Path

from app.menu_costing.catalog import owner_rupee
from app.menu_costing.recipes import procurement_dir, recipe_lines
from app.procurement.numbers import format_qty, num_attr, parse_number

_CACHE = {}
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def clear_history_cache():
    _CACHE.clear()


def load_history(directory=None):
    root = Path(directory) if directory else procurement_dir() / "history"
    key = str(root.resolve()) if root.exists() else str(root)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    bundle = _read(root)
    _CACHE[key] = bundle
    return bundle


def archive_note(months):
    if not months:
        return "No recipe snapshots are on file."
    if len(months) == 1:
        return f"{months[0]['label']} is the first snapshot. There is no earlier month to compare."
    return ""


def dish_history(history, city, outlet, item):
    months = history.get("months") or []
    points = []
    if city and outlet and item:
        wanted = (city, outlet, (item or "").strip().casefold())
        for month in months:
            row = month["costs"].get(wanted)
            points.append(
                {
                    "key": month["key"],
                    "label": month["label"],
                    "cost": None if row is None else row["cost"],
                    "directory": month["directory"],
                    "has_lines": month["has_lines"],
                }
            )
    changes = []
    for older, newer in zip(points, points[1:]):
        changes.append(_compare(older, newer, outlet, item))
    return {
        "months": [{"key": month["key"], "label": month["label"]} for month in months],
        "note": archive_note(months),
        "points": points,
        "changes": changes,
    }


def present_history(detail):
    points = []
    for row in detail.get("points") or []:
        points.append(
            {
                "key": row["key"],
                "label": row["label"],
                "cost": owner_rupee(row["cost"]),
                "cost_attr": num_attr(row["cost"]),
            }
        )
    changes = []
    for row in detail.get("changes") or []:
        changes.append(
            {
                "older": row["older"],
                "newer": row["newer"],
                "old_cost": owner_rupee(row["old_cost"]),
                "new_cost": owner_rupee(row["new_cost"]),
                "old_attr": num_attr(row["old_cost"]),
                "new_attr": num_attr(row["new_cost"]),
                "added": row["added"],
                "removed": row["removed"],
                "qty_changed": row["qty_changed"],
                "lines_missing": row["lines_missing"],
            }
        )
    return {
        "recipe_months": detail.get("months") or [],
        "recipe_note": detail.get("note") or "",
        "recipe_points": points,
        "recipe_changes": changes,
    }


def _read(root):
    months = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            match = _MONTH.match(child.name)
            if match is None:
                continue
            year, month = int(match.group(1)), int(match.group(2))
            if month < 1 or month > 12:
                continue
            cost_path = child / "menu_item_cost.csv"
            if not cost_path.is_file():
                continue
            lines_path = child / "menu_item_cost_lines.csv"
            months.append(
                {
                    "key": child.name,
                    "label": date(year, month, 1).strftime("%B %Y"),
                    "directory": child,
                    "costs": _read_costs(cost_path),
                    "has_lines": lines_path.is_file(),
                }
            )
    return {"root": root, "months": months}


def _read_costs(path):
    costs = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
                continue
            if str(raw.get("is_menu_item") or "").strip().casefold() not in {"true", "1", "yes"}:
                continue
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            outlet = (raw.get("outlet") or "").strip()
            if not name or not city or not outlet:
                continue
            costs[(city, outlet, name.casefold())] = {
                "item": name,
                "cost": parse_number(raw.get("cost_per_portion_avg")),
            }
    return costs


def _compare(older, newer, outlet, item):
    added = []
    removed = []
    qty_changed = []
    lines_missing = not older["has_lines"] or not newer["has_lines"]
    if not lines_missing:
        old_lines = _signature(recipe_lines({"lines_path": older["directory"] / "menu_item_cost_lines.csv"}, outlet, item))
        new_lines = _signature(recipe_lines({"lines_path": newer["directory"] / "menu_item_cost_lines.csv"}, outlet, item))
        for key, row in new_lines.items():
            if key not in old_lines:
                added.append(row["ingredient"])
                continue
            previous = old_lines[key]
            if previous["qty_key"] != row["qty_key"]:
                qty_changed.append(
                    {
                        "ingredient": row["ingredient"],
                        "old_qty": format_qty(previous["qty"]),
                        "old_unit": previous["unit"],
                        "new_qty": format_qty(row["qty"]),
                        "new_unit": row["unit"],
                    }
                )
        for key, row in old_lines.items():
            if key not in new_lines:
                removed.append(row["ingredient"])
        added.sort(key=str.casefold)
        removed.sort(key=str.casefold)
        qty_changed.sort(key=lambda row: row["ingredient"].casefold())
    return {
        "older": older["label"],
        "newer": newer["label"],
        "old_cost": older["cost"],
        "new_cost": newer["cost"],
        "added": added,
        "removed": removed,
        "qty_changed": qty_changed,
        "lines_missing": lines_missing,
    }


def _signature(lines):
    signed = {}
    for line in lines:
        name = line["ingredient"]
        qty = line["qty"]
        unit = line["unit"] or ""
        signed[name.casefold()] = {
            "ingredient": name,
            "qty": qty,
            "unit": unit,
            "qty_key": (None if qty is None else round(float(qty), 6), unit.casefold()),
        }
    return signed
