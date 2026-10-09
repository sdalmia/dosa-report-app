"""Current menu, threats, and the diff between two saved menus.

Prices come only from an uploaded menu. Recipe cost comes from the cost file.
A missing price, cost, or sale stays blank.
"""

from app.menu_costing.recipes import recipe_lines
from app.menu_costing.sales import city_sale, lookup_sale
from app.procurement.numbers import format_pct, format_qty, num_attr, percent
from app.store_health.present import format_owner_rupee, group_indian

CHANNELS = ("Dine-in", "Swiggy", "Zomato", "Food court", "Kiosk")
ALL_STORES = "All stores"
CITY_NOTE = (
    "Delhi serves 3 chutneys with each dish. Kolkata serves 1. "
    "Compare a store with its own city, not with the other city."
)
THREAT_LIMIT = 8
LIST_LIMIT = 40


def owner_rupee(value):
    if value is None:
        return ""
    number = float(value)
    if number != 0 and abs(number) < 0.5:
        return "under ₹1"
    return format_owner_rupee(number)


def owner_count(value):
    if value is None:
        return ""
    return group_indian(str(int(round(float(value)))))


def vs_own_city(pct, city):
    if pct is None or not city:
        return ""
    if pct == 0:
        return f"Same as the {city} median"
    direction = "above" if pct > 0 else "below"
    return f"{format_pct(abs(pct))} {direction} the {city} median"


def food_cost_pct(cost, price):
    if cost is None or price is None or price == 0:
        return None
    return percent(cost, price)


def margin_amount(cost, price):
    if cost is None or price is None:
        return None
    return price - cost


def active_version(versions, city, channel, store, today):
    covering = [row for row in versions if _covers(row, city, channel, today)]
    specific = [row for row in covering if store and row["store_scope"] == store]
    pool = specific or [row for row in covering if row["store_scope"] == ALL_STORES]
    if not pool:
        return None
    pool.sort(key=lambda row: (row["effective_from"], row["id"]), reverse=True)
    return pool[0]


def version_pair(versions, city, channel, store):
    scopes = []
    if store:
        scopes.append(store)
    scopes.append(ALL_STORES)
    for scope in scopes:
        rows = [
            row
            for row in versions
            if row["city"] == city and row["channel"] == channel and row["store_scope"] == scope
        ]
        rows.sort(key=lambda row: (row["effective_from"], row["id"]), reverse=True)
        if len(rows) >= 2:
            return rows[0], rows[1]
    return None, None


def diff_items(older, newer):
    old_map = {_key(row): row for row in older}
    new_map = {_key(row): row for row in newer}
    added = []
    removed = []
    repriced = []
    for key, row in new_map.items():
        if key not in old_map:
            added.append(row)
            continue
        previous = old_map[key]
        if _price_changed(previous.get("price"), row.get("price")):
            repriced.append(
                {
                    "item": row["item"],
                    "category": row.get("category") or previous.get("category") or "",
                    "old_price": previous.get("price"),
                    "new_price": row.get("price"),
                }
            )
    for key, row in old_map.items():
        if key not in new_map:
            removed.append(row)
    added.sort(key=lambda row: row["item"].casefold())
    removed.sort(key=lambda row: row["item"].casefold())
    repriced.sort(key=lambda row: row["item"].casefold())
    return {"added": added, "removed": removed, "repriced": repriced}


def build_page(recipes, sales, versions, *, city, channel, store, query, today):
    city = city if city in recipes["cities"] else (recipes["cities"][0] if recipes["cities"] else "")
    channel = channel if channel in CHANNELS else CHANNELS[0]
    outlets = recipes["outlets"].get(city, [])
    if store not in outlets:
        store = ""
    query_key = (query or "").strip().casefold()
    version = active_version(versions, city, channel, store, today)
    newer, older = version_pair(versions, city, channel, store)
    rows = _menu_rows(recipes, sales, city, store, version, query_key)
    shown = rows[:LIST_LIMIT]
    costs = {row["key"]: row["cost"] for row in _menu_rows(recipes, sales, city, store, None, "")}
    return {
        "city": city,
        "channel": channel,
        "store": store,
        "query": (query or "").strip(),
        "cities": recipes["cities"],
        "channels": CHANNELS,
        "outlets": outlets,
        "city_note": CITY_NOTE,
        "has_prices": version is not None,
        "price_gap": (
            ""
            if version is not None
            else f"No {channel} prices on file for {city}. Price, food cost, and margin stay blank."
        ),
        "version": version,
        "threats_above": [present_threat(row) for row in _above(recipes, city, store, query_key)],
        "above_count": _above_count(recipes, city, store, query_key),
        "priced_below": [present_below(row) for row in _priced_below(rows)] if version is not None else [],
        "priced_below_gap": (
            ""
            if version is not None
            else "No menu prices on file, so items priced below cost cannot be listed."
        ),
        "margin_hurts": [present_hurt(row) for row in _margin_hurts(newer, older, costs)] if newer and older else [],
        "margin_gap": (
            ""
            if newer and older
            else "No earlier menu to compare, so price changes that hurt margin cannot be listed."
        ),
        "rows": [_present_row(row) for row in shown],
        "row_count": len(rows),
        "shown_count": len(shown),
        "sales_available": bool(sales.get("available")),
        "sales_period": sales.get("period_label") or "",
        "sales_coming": sales.get("coming") or "Data coming.",
        "sellers": _sellers(recipes, sales, city, store, version),
    }


def build_item(recipes, *, city, store, item):
    city = city if city in recipes["cities"] else ""
    outlets = recipes["outlets"].get(city, [])
    if store not in outlets:
        store = ""
    key = (item or "").strip().casefold()
    display = (item or "").strip()
    stores = []
    for outlet in outlets:
        row = recipes["by_outlet"].get((city, outlet, key))
        if row is None:
            continue
        if not display:
            display = row["item"]
        stores.append(row)
    summary = recipes["by_city"].get((city, key))
    lines = recipe_lines(recipes, store, display) if store and display else []
    priced = [line["line_cost"] for line in lines if line["line_cost"] is not None]
    return {
        "city": city,
        "store": store,
        "item": display,
        "city_note": CITY_NOTE,
        "outlets": outlets,
        "summary": summary,
        "stores": stores,
        "chosen": recipes["by_outlet"].get((city, store, key)) if store else None,
        "lines": lines,
        "lines_total": sum(priced) if priced else None,
        "missing_lines": "Ingredient lines are not on file for this store." if store and not lines else "",
        "pick_store": "Pick a store to see this item's ingredients." if not store else "",
    }


def _covers(row, city, channel, today):
    if row["city"] != city or row["channel"] != channel:
        return False
    if row["effective_from"] > today:
        return False
    end = row.get("effective_to")
    return end is None or end >= today


def _key(row):
    return (row.get("item") or "").casefold()


def _price_changed(old, new):
    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    return abs(float(old) - float(new)) > 0.009


def _menu_rows(recipes, sales, city, store, version, query_key):
    prices = {}
    if version is not None:
        for row in version.get("items") or []:
            prices[row["item"].casefold()] = row
    rows = []
    if version is not None:
        source = list(version.get("items") or [])
        for price_row in source:
            if query_key and query_key not in price_row["item"].casefold():
                continue
            cost_row = _cost_row(recipes, city, store, price_row["item"])
            rows.append(_join(price_row["item"], price_row, cost_row, sales, city, store, recipes))
    elif store:
        for (row_city, outlet, _item_key), row in recipes["by_outlet"].items():
            if row_city != city or outlet != store:
                continue
            if query_key and query_key not in row["item"].casefold():
                continue
            rows.append(_join(row["item"], None, row, sales, city, store, recipes))
    else:
        for (row_city, _item_key), row in recipes["by_city"].items():
            if row_city != city:
                continue
            if query_key and query_key not in row["item"].casefold():
                continue
            rows.append(_join(row["item"], None, None, sales, city, store, recipes, summary=row))
    rows.sort(key=lambda row: row["item"].casefold())
    return rows


def _cost_row(recipes, city, store, item):
    key = item.casefold()
    if store:
        return recipes["by_outlet"].get((city, store, key))
    summary = recipes["by_city"].get((city, key))
    if summary is None:
        return None
    return {"item": summary["item"], "cost": summary["median"], "median": summary["median"], "vs_pct": None, "partial": False}


def _join(item, price_row, cost_row, sales, city, store, recipes, summary=None):
    cost = None
    median = None
    vs_pct = None
    partial = False
    if cost_row is not None:
        cost = cost_row.get("cost")
        median = cost_row.get("median")
        vs_pct = cost_row.get("vs_pct")
        partial = bool(cost_row.get("partial"))
    elif summary is not None:
        cost = summary.get("median")
        median = summary.get("median")
    price = None if price_row is None else price_row.get("price")
    category = "" if price_row is None else (price_row.get("category") or "")
    if store:
        sale = lookup_sale(sales, store, item)
        orders = None if sale is None else sale.get("orders")
        sold = None if sale is None else sale.get("sales")
    else:
        rolled = city_sale(sales, recipes["outlets"].get(city, []), item)
        orders = None if rolled is None else rolled.get("orders")
        sold = None if rolled is None else rolled.get("sales")
    return {
        "item": item,
        "key": item.casefold(),
        "city": city,
        "category": category,
        "price": price,
        "cost": cost,
        "median": median,
        "vs_pct": vs_pct,
        "partial": partial,
        "basis": "store" if store else "median",
        "food_pct": food_cost_pct(cost, price),
        "margin": margin_amount(cost, price),
        "orders": orders,
        "sold": sold,
    }


def _above(recipes, city, store, query_key):
    rows = []
    for (row_city, outlet, _item_key), row in recipes["by_outlet"].items():
        if row_city != city:
            continue
        if store and outlet != store:
            continue
        if query_key and query_key not in row["item"].casefold():
            continue
        if row["vs_pct"] is None or row["vs_pct"] <= 0 or row["cost"] is None:
            continue
        rows.append(row)
    rows.sort(key=lambda row: (-row["vs_pct"], row["item"].casefold(), row["outlet"].casefold()))
    return rows[:THREAT_LIMIT]


def _above_count(recipes, city, store, query_key):
    count = 0
    for (row_city, outlet, _item_key), row in recipes["by_outlet"].items():
        if row_city != city:
            continue
        if store and outlet != store:
            continue
        if query_key and query_key not in row["item"].casefold():
            continue
        if row["vs_pct"] is not None and row["vs_pct"] > 0 and row["cost"] is not None:
            count += 1
    return count


def _priced_below(rows):
    found = []
    for row in rows:
        if row["price"] is None or row["cost"] is None:
            continue
        if row["price"] < row["cost"]:
            found.append(row)
    found.sort(key=lambda row: (row["price"] - row["cost"], row["item"].casefold()))
    return found[:THREAT_LIMIT]


def _margin_hurts(newer, older, costs):
    changes = diff_items(older.get("items") or [], newer.get("items") or [])
    hurts = []
    for row in changes["repriced"]:
        cost = costs.get(row["item"].casefold())
        old_margin = margin_amount(cost, row["old_price"])
        new_margin = margin_amount(cost, row["new_price"])
        if old_margin is None or new_margin is None:
            continue
        if new_margin < old_margin - 0.009:
            hurts.append(
                {
                    "item": row["item"],
                    "old_price": row["old_price"],
                    "new_price": row["new_price"],
                    "old_margin": old_margin,
                    "new_margin": new_margin,
                }
            )
    hurts.sort(key=lambda row: row["new_margin"] - row["old_margin"])
    return hurts[:THREAT_LIMIT]


def _sellers(recipes, sales, city, store, version):
    if not sales.get("available"):
        return []
    outlets = [store] if store else recipes["outlets"].get(city, [])
    totals = {}
    for outlet in outlets:
        for (store_key, item_key), sale in sales["by_store_item"].items():
            if store_key != outlet.casefold():
                continue
            bucket = totals.setdefault(item_key, {"item": sale["item"], "orders": [], "sales": []})
            if sale["orders"] is not None:
                bucket["orders"].append(sale["orders"])
            if sale["sales"] is not None:
                bucket["sales"].append(sale["sales"])
    ranked = []
    for item_key, bucket in totals.items():
        orders = sum(bucket["orders"]) if bucket["orders"] else None
        sold = sum(bucket["sales"]) if bucket["sales"] else None
        cost_row = _cost_row(recipes, city, store, bucket["item"])
        price = None
        if version is not None:
            for row in version.get("items") or []:
                if row["item"].casefold() == item_key:
                    price = row.get("price")
                    break
        cost = None if cost_row is None else cost_row.get("cost")
        ranked.append(
            {
                "item": bucket["item"],
                "orders": orders,
                "sold": sold,
                "cost": cost,
                "price": price,
                "food_pct": food_cost_pct(cost, price),
            }
        )
    ranked.sort(key=lambda row: (-(row["orders"] or -1), row["item"].casefold()))
    return [_present_seller(row) for row in ranked[:THREAT_LIMIT]]


def _present_row(row):
    return {
        "item": row["item"],
        "category": row["category"],
        "price": owner_rupee(row["price"]),
        "price_attr": num_attr(row["price"]),
        "cost": owner_rupee(row["cost"]),
        "cost_attr": num_attr(row["cost"]),
        "vs": vs_own_city(row["vs_pct"], row.get("city") or ""),
        "vs_attr": num_attr(row["vs_pct"]),
        "food_pct": format_pct(row["food_pct"]),
        "food_attr": num_attr(row["food_pct"]),
        "margin": owner_rupee(row["margin"]),
        "margin_attr": num_attr(row["margin"]),
        "orders": owner_count(row["orders"]),
        "orders_attr": num_attr(row["orders"]),
        "sold": owner_rupee(row["sold"]),
        "sold_attr": num_attr(row["sold"]),
        "partial": row["partial"],
        "basis": row.get("basis") or "store",
        "city_vs": row["vs_pct"],
    }


def present_threat(row):
    return {
        "item": row["item"],
        "outlet": row["outlet"],
        "city": row["city"],
        "cost": owner_rupee(row["cost"]),
        "vs": vs_own_city(row["vs_pct"], row["city"]),
        "vs_attr": num_attr(row["vs_pct"]),
    }


def present_below(row):
    return {
        "item": row["item"],
        "price": owner_rupee(row["price"]),
        "cost": owner_rupee(row["cost"]),
        "gap": owner_rupee(row["price"] - row["cost"]),
    }


def present_hurt(row):
    return {
        "item": row["item"],
        "old_price": owner_rupee(row["old_price"]),
        "new_price": owner_rupee(row["new_price"]),
        "old_margin": owner_rupee(row["old_margin"]),
        "new_margin": owner_rupee(row["new_margin"]),
    }


def _present_seller(row):
    return {
        "item": row["item"],
        "orders": owner_count(row["orders"]),
        "orders_attr": num_attr(row["orders"]),
        "sold": owner_rupee(row["sold"]),
        "sold_attr": num_attr(row["sold"]),
        "cost": owner_rupee(row["cost"]),
        "price": owner_rupee(row["price"]),
        "food_pct": format_pct(row["food_pct"]),
    }


def present_line(row):
    return {
        "ingredient": row["ingredient"],
        "qty": format_qty(row["qty"]),
        "unit": row["unit"],
        "unit_cost": "" if row["unpriced"] else owner_rupee(row["unit_cost"]),
        "line_cost": "" if row["unpriced"] else owner_rupee(row["line_cost"]),
        "line_attr": "" if row["unpriced"] else num_attr(row["line_cost"]),
        "unpriced": row["unpriced"],
        "inactive": row["inactive"],
    }
