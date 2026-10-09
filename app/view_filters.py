"""Session filters shared by Home, Store Health, Procurement, and Scorecard.

The choice sticks for the browser session. An empty range keeps each page on
its own window, so a first visit does not move the numbers.
"""

from datetime import date, timedelta

from flask import request, session

CITY_REGION = {"Kolkata": "East", "Delhi NCR": "North"}
CITY_LABEL = {"East": "Kolkata", "North": "Delhi NCR"}
PROCUREMENT_CITY = {"Kolkata": "Kolkata", "Delhi NCR": "Delhi"}
RANGES = {"", "7", "30", "custom"}
CITIES = {"", "Kolkata", "Delhi NCR"}
KEYS = ("cc_store", "cc_city", "cc_range", "cc_start", "cc_end")


def _clean(key, raw):
    text = (raw or "").strip()
    if key == "cc_city":
        return text if text in CITIES else ""
    if key == "cc_range":
        return text if text in RANGES else ""
    if key in {"cc_start", "cc_end"}:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return ""
    return text


def remember_filters():
    """Read the filter form into the session, then return the saved choice."""
    if any(key in request.args for key in KEYS):
        for key in KEYS:
            if key in request.args:
                session[key] = _clean(key, request.args.get(key))
    return current_filters()


def current_filters():
    return {key: session.get(key) or "" for key in KEYS}


def city_region(filters):
    return CITY_REGION.get((filters or {}).get("cc_city") or "", "")


def resolve_bounds(filters, start, end):
    """Apply last 7, last 30, or a custom range. Otherwise keep start and end."""
    if not filters or start is None or end is None:
        return start, end
    kind = filters.get("cc_range") or ""
    if kind == "7":
        return end - timedelta(days=6), end
    if kind == "30":
        return end - timedelta(days=29), end
    if kind == "custom":
        try:
            custom_start = date.fromisoformat(filters.get("cc_start") or "")
            custom_end = date.fromisoformat(filters.get("cc_end") or "")
        except ValueError:
            return start, end
        if custom_end < custom_start:
            return start, end
        return custom_start, custom_end
    return start, end


def store_options():
    from app.store_health.contract import load_feeds
    from app.store_health.present import list_stores

    stores = []
    for store in list_stores(load_feeds()):
        stores.append({"id": store.id, "label": store.label, "region": store.region or ""})
    return stores


def visible_stores(stores, filters):
    region = city_region(filters)
    if not region:
        return stores
    return [store for store in stores if store.get("region") == region]


def narrow_tiles(tiles, filters):
    city = PROCUREMENT_CITY.get((filters or {}).get("cc_city") or "")
    if not city:
        return tiles
    wanted = city.casefold()
    kept = []
    for tile in tiles or []:
        lines = []
        for line in tile.get("lines") or []:
            label = (line.get("label") or "").casefold()
            if ("kolkata" in label or "delhi" in label) and wanted not in label:
                continue
            lines.append(line)
        copy = dict(tile)
        copy["lines"] = lines
        kept.append(copy)
    return kept


def selected_label(stores, filters):
    wanted = (filters or {}).get("cc_store") or ""
    if not wanted:
        return ""
    for store in stores:
        if store.get("id") == wanted:
            return store.get("label") or ""
    return ""
