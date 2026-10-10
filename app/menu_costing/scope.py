"""Shared store, city, and date filters for Menu & Costing.

A request that names city or store directly still wins, so a dish link
opens that dish. The header filters win when they are the request, and
when the page is opened with neither city nor store.
"""

from flask import request

from app.view_filters import remember_filters, store_options, visible_stores

_SHARED = ("cc_city", "cc_store", "cc_range", "cc_start", "cc_end")


def filter_context(filters):
    return {
        "filters": filters,
        "filter_stores": visible_stores(store_options(), filters),
    }


def place_from_request(recipes):
    filters = remember_filters()
    explicit_city = (request.args.get("city") or "").strip()
    explicit_store = (request.args.get("store") or "").strip()
    shared = any(key in request.args for key in _SHARED)
    if shared or (not explicit_city and not explicit_store):
        city, store = _from_filters(filters, recipes)
        if not city:
            city = explicit_city
        if not store:
            store = explicit_store
    else:
        city, store = explicit_city, explicit_store
    return filters, city, store


def _from_filters(filters, recipes):
    city = (filters.get("cc_city") or "").strip()
    if city and city not in (recipes.get("cities") or []):
        city = ""
    store = ""
    store_id = (filters.get("cc_store") or "").strip()
    if store_id:
        names = _outlet_names(store_id)
        outlets = {
            name.casefold(): name
            for group in (recipes.get("outlets") or {}).values()
            for name in group
        }
        for candidate in names:
            store = outlets.get(candidate.casefold(), "")
            if store:
                break
            short = candidate.split("(")[0].strip()
            short = short.replace("Dosa Coffee - ", "").strip()
            store = outlets.get(short.casefold(), "")
            if store:
                break
    return city, store


def _outlet_names(store_id):
    from app.store_master import get_index

    names = []
    for row in get_index().rows:
        if row.get("store_id") != store_id:
            continue
        for label in (row.get("display_name"), row.get("posist_name")):
            if label and label not in names:
                names.append(label)
    if not names:
        for option in store_options():
            if option.get("id") == store_id and option.get("label"):
                names.append(option["label"])
    return names
