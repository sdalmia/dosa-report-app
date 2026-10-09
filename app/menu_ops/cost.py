"""Recipe cost per outlet from the Restroworks stock-recipe export.

Margin uses the base tab and cost_per_portion_avg. A blank cost stays empty.
no_priced_ingredients is empty as well, including every GK1 Cloud Kitchen and
FRA recipe. A real zero is kept. The unpriced-ingredient flag marks a cost as
partial; the number is still the cost. Item names match exactly. Outlet names
use the store matcher and are left unmatched when that matcher is unsure.
"""

import csv
from pathlib import Path

from app.menu_ops.loader import _blank, item_key, procurement_directory
from app.store_health.contract import parse_date, parse_number
from app.store_health.stores import match_menu_store

COST_FILE = "menu_item_cost.csv"
SUMMARY_FILE = "menu_item_cost_summary.csv"
CHANNEL_COST_FILE = "menu_item_cost_channels_ideal_plaza.csv"
NO_PRICED = "no_priced_ingredients"


def load_menu_costs(directory=None):
    directory = Path(directory) if directory else procurement_directory()
    path = directory / COST_FILE
    result = {
        "present": False,
        "found": False,
        "file": COST_FILE,
        "as_of": None,
        "outlets": [],
        "outlet_region": {},
        "by_outlet": {},
        "item_names": set(),
        "summary": {},
        "channels": {},
        "warnings": [],
    }
    if not path.exists():
        result["warnings"].append(f"{COST_FILE} is not on file.")
        return result
    result["found"] = True
    by_outlet, item_names, as_of, conflicts, outlet_region = _read_base_costs(path)
    result["by_outlet"] = by_outlet
    result["outlet_region"] = outlet_region
    result["item_names"] = item_names
    result["outlets"] = sorted(by_outlet)
    result["as_of"] = as_of
    result["present"] = bool(by_outlet)
    for key in conflicts:
        result["warnings"].append(
            f"{COST_FILE} has two different base costs for the same outlet and item, so that cost was left empty."
        )
    summary_path = directory / SUMMARY_FILE
    if summary_path.exists():
        result["summary"] = _read_summary(summary_path)
    channel_path = directory / CHANNEL_COST_FILE
    if channel_path.exists():
        result["channels"] = _read_channels(channel_path)
    return result


def match_outlet(store, outlets):
    """Exact name, otherwise the store matcher. Ambiguous names match nothing."""
    if not store or not outlets:
        return None
    folded = {}
    for name in outlets:
        folded.setdefault(item_key(name), name)
    exact = folded.get(item_key(store))
    if exact:
        return exact
    return match_menu_store(store, list(outlets))


def _read_base_costs(path):
    by_outlet = {}
    item_names = set()
    outlet_region = {}
    as_of = None
    conflicts = set()
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            tab = str(raw.get("recipe_tab") or "base").strip().casefold() or "base"
            if tab != "base":
                continue
            outlet = str(raw.get("outlet") or "").strip()
            item = str(raw.get("item_name") or raw.get("item") or "").strip()
            if not outlet or not item:
                continue
            key = item_key(item)
            item_names.add(key)
            status = str(raw.get("cost_status") or "").strip()
            cost = _portion_cost(raw.get("cost_per_portion_avg"), status)
            partial = _flag(raw.get("has_unpriced_ingredient")) and cost is not None
            region = str(raw.get("region") or "").strip()
            if region:
                outlet_region.setdefault(outlet, region)
            record = {
                "outlet": outlet,
                "item": item,
                "cost": cost,
                "partial": partial,
                "status": status,
                "region": region,
            }
            slot = by_outlet.setdefault(outlet, {})
            previous = slot.get(key)
            if previous is None:
                slot[key] = record
            elif previous["cost"] != record["cost"] or previous["partial"] != record["partial"]:
                conflicts.add((outlet, key))
                slot[key] = {
                    "outlet": outlet,
                    "item": item,
                    "cost": None,
                    "partial": False,
                    "status": status,
                }
            stamped = parse_date(raw.get("as_of"))
            if stamped is not None:
                as_of = stamped if as_of is None else max(as_of, stamped)
    return by_outlet, item_names, as_of, conflicts, outlet_region


def _portion_cost(value, status):
    if str(status or "").strip() == NO_PRICED:
        return None
    if _blank(value):
        return None
    return parse_number(value)


def _flag(value):
    return str(value or "").strip().casefold() in {"true", "1", "yes", "y"}


def _read_summary(path):
    summary = {}
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            item = str(raw.get("item_name") or "").strip()
            if not item:
                continue
            key = item_key(item)
            if key in summary:
                continue
            summary[key] = {
                "min": parse_number(raw.get("min_cost_avg")),
                "median": parse_number(raw.get("median_cost_avg")),
                "max": parse_number(raw.get("max_cost_avg")),
                "median_east": parse_number(raw.get("median_cost_east")),
                "median_north": parse_number(raw.get("median_cost_north")),
            }
    return summary


def _read_channels(path):
    channels = {}
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            item = str(raw.get("item_name") or "").strip()
            if not item:
                continue
            key = item_key(item)
            status = str(raw.get("cost_status") or "").strip()
            channels[key] = {
                "base": _portion_cost(raw.get("cost_base"), status),
                "takeout": _portion_cost(raw.get("cost_takeout"), status),
                "delivery": _portion_cost(raw.get("cost_delivery"), status),
                "status": status,
            }
    return channels
