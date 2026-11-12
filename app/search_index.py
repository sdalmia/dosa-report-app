"""Pages, stores, and menu items for the header and drawer search."""

from app.store_health.contract import load_feeds
from app.store_health.present import list_stores
from app.store_health.stores import match_menu_store
from app.store_master import resolve_store_label

PAGES = (
    {"kind": "Page", "label": "Home", "href": "/dashboard"},
    {"kind": "Page", "label": "Upload prices", "href": "/ingredient-tracker/upload"},
)


def search_index():
    feeds = load_feeds()
    rows = list(PAGES)
    stores = list_stores(feeds)
    by_label = {store.label: store for store in stores}
    labels = list(by_label)
    for store in stores:
        rows.append({
            "kind": "Store",
            "label": store.label,
            "href": f"/store-health/{store.id}",
        })
    resolved = {}

    def store_for(name):
        if name not in resolved:
            matched = resolve_store_label(name, labels) if name else None
            if matched is None and name:
                matched = match_menu_store(name, labels)
            resolved[name] = by_label.get(matched) if matched else None
        return resolved[name]

    best = {}
    for source in (feeds.get("item_sales") or [], feeds.get("menu_mix") or []):
        for row in source:
            item = (row.get("item") or "").strip()
            store_name = (row.get("store") or "").strip()
            if not item:
                continue
            sales = row.get("total_sales")
            current = best.get(item)
            if current is None or (sales or 0) > (current[0] or 0):
                best[item] = (sales, store_name)
    for item, (_sales, store_name) in sorted(best.items(), key=lambda pair: pair[0].casefold()):
        store = store_for(store_name)
        href = f"/store-health/{store.id}#menu-mix" if store else "/store-health#menu-mix"
        shown = store.label if store else store_name
        rows.append({"kind": "Menu item", "label": item, "href": href, "store": shown})
    return rows
