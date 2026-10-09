"""Posist item sales. September menu mix is on file. Later months are not."""

import csv
from pathlib import Path

from app.procurement.numbers import format_period, parse_number

_CACHE = {}


def sales_dir():
    return Path(__file__).resolve().parents[2] / "data" / "store_health"


def load_sales(directory=None):
    directory = Path(directory) if directory else sales_dir()
    key = str(directory)
    if key in _CACHE:
        return _CACHE[key]
    bundle = _read(directory / "menu_mix.csv")
    _CACHE[key] = bundle
    return bundle


def _store_key(label):
    return (label or "").split("(")[0].strip().casefold()


def _read(path):
    empty = {
        "available": False,
        "period_label": "",
        "by_store_item": {},
        "coming": "Item sales are not on file. Data coming.",
    }
    if not path.is_file():
        return empty
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            store = (raw.get("store") or "").strip()
            item = (raw.get("item") or "").strip()
            if not store or not item:
                continue
            rows.append(
                {
                    "store": store,
                    "store_key": _store_key(store),
                    "item": item,
                    "key": item.casefold(),
                    "orders": parse_number(raw.get("total_orders")),
                    "sales": parse_number(raw.get("total_sales")),
                    "start": (raw.get("period_start") or "").strip(),
                    "end": (raw.get("period_end") or "").strip(),
                }
            )
    if not rows:
        return empty
    latest = max(row["end"] for row in rows)
    kept = [row for row in rows if row["end"] == latest]
    start = min((row["start"] for row in kept if row["start"]), default="")
    index = {}
    for row in kept:
        index[(row["store_key"], row["key"])] = row
    period = ""
    if start and latest:
        from datetime import date

        try:
            period = format_period(date.fromisoformat(start), date.fromisoformat(latest))
        except ValueError:
            period = f"{start} to {latest}"
    return {
        "available": True,
        "period_label": period,
        "by_store_item": index,
        "coming": "Later months are not on file. Data coming.",
    }


def lookup_sale(sales, outlet, item):
    if not sales.get("available"):
        return None
    return sales["by_store_item"].get((_store_key(outlet), (item or "").casefold()))


def city_sale(sales, outlets, item):
    """Sum the stores that have a row. A store with no row is left out, not zeroed."""
    if not sales.get("available"):
        return None
    orders = []
    amounts = []
    for outlet in outlets:
        row = lookup_sale(sales, outlet, item)
        if row is None:
            continue
        if row["orders"] is not None:
            orders.append(row["orders"])
        if row["sales"] is not None:
            amounts.append(row["sales"])
    if not orders and not amounts:
        return None
    return {
        "orders": sum(orders) if orders else None,
        "sales": sum(amounts) if amounts else None,
    }
