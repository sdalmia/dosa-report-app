"""Join recipe cost to menu sales.

The rows come from recipe_costs(), the same helper as
/food-cost/recipe-cost.json. This module does not read the recipe CSVs.
It only indexes those rows for a margin: base cost at average price,
the city median beside that cost, and Ideal Plaza takeout and delivery
kept beside the item.
"""

from app.menu_ops.loader import item_key, procurement_directory
from app.procurement.recipe import recipe_costs
from app.store_health.contract import parse_date
from app.store_health.stores import match_menu_store

NO_PRICED = "no_priced_ingredients"


def load_menu_costs(directory=None):
    directory = directory or procurement_directory()
    payload = recipe_costs(directory=directory, include_non_menu=True)
    result = {
        "present": False,
        "found": False,
        "file": payload.get("source") or "",
        "as_of": None,
        "outlets": [],
        "outlet_region": {},
        "outlet_city": {},
        "by_outlet": {},
        "item_names": set(),
        "summary": {},
        "channels": {},
        "warnings": [],
    }
    if not payload.get("available"):
        result["warnings"].append(payload.get("margin_unavailable") or "Recipe cost is not on file.")
        return result
    result["found"] = True
    by_outlet = {}
    item_names = set()
    outlet_region = {}
    outlet_city = {}
    channels = {}
    as_of = None
    for row in payload.get("items") or []:
        outlet = (row.get("outlet") or "").strip()
        item = (row.get("menu_item") or "").strip()
        if not outlet or not item:
            continue
        tab = (row.get("recipe_tab") or "base").strip().casefold() or "base"
        key = item_key(item)
        cost = _usable_cost(row)
        partial = bool(row.get("partial")) and cost is not None
        stamped = parse_date(row.get("as_of"))
        if stamped is not None:
            as_of = stamped if as_of is None else max(as_of, stamped)
        if tab == "base":
            region = (row.get("region") or "").strip()
            city = (row.get("city") or "").strip()
            if region:
                outlet_region.setdefault(outlet, region)
            if city:
                outlet_city.setdefault(outlet, city)
            item_names.add(key)
            _keep_cost(
                by_outlet.setdefault(outlet, {}),
                key,
                {
                    "outlet": outlet,
                    "item": item,
                    "cost": cost,
                    "partial": partial,
                    "status": row.get("cost_status") or "",
                    "city": city,
                    "city_median": row.get("city_baseline_median"),
                },
            )
        elif tab in {"takeout", "delivery"} and item_key(outlet) == "ideal plaza":
            slot = channels.setdefault(key, {"takeout": None, "delivery": None, "status": row.get("cost_status") or ""})
            _keep_channel(slot, tab, cost)
    for row in payload.get("summary") or []:
        name = (row.get("item_name") or "").strip()
        if not name:
            continue
        key = item_key(name)
        city = (row.get("city") or "").strip()
        result["summary"].setdefault(
            (key, city.casefold()),
            {
                "city": city,
                "min": row.get("min_cost"),
                "median": row.get("median_cost"),
                "max": row.get("max_cost"),
                "spread": row.get("spread_pct"),
            },
        )
    result["by_outlet"] = by_outlet
    result["item_names"] = item_names
    result["outlets"] = sorted(by_outlet)
    result["outlet_region"] = outlet_region
    result["outlet_city"] = outlet_city
    result["channels"] = {key: value for key, value in channels.items() if value.get("takeout") is not None or value.get("delivery") is not None}
    result["as_of"] = as_of
    result["present"] = bool(by_outlet)
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


def _usable_cost(row):
    if (row.get("cost_status") or "").strip() == NO_PRICED:
        return None
    return row.get("cost_per_portion_avg")


def _keep_cost(slot, key, record):
    previous = slot.get(key)
    if previous is None:
        slot[key] = record
        return
    if previous["cost"] != record["cost"] or previous["partial"] != record["partial"]:
        slot[key] = {
            "outlet": record["outlet"],
            "item": record["item"],
            "cost": None,
            "partial": False,
            "status": record["status"],
            "city": record.get("city") or "",
            "city_median": None,
        }


def _keep_channel(slot, tab, cost):
    previous = slot.get(tab)
    if previous is None:
        slot[tab] = cost
    elif previous != cost:
        slot[tab] = None
