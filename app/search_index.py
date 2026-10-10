"""Pages, stores, and menu items for the header and drawer search."""

from app.store_health.contract import load_feeds
from app.store_health.present import list_stores
from app.store_health.stores import match_menu_store
from app.store_master import resolve_store_label

PAGES = (
    {"kind": "Page", "label": "Home", "href": "/dashboard"},
    {"kind": "Page", "label": "Morning brief", "href": "/brief"},
    {"kind": "Page", "label": "Scorecard", "href": "/scorecard"},
    {"kind": "Page", "label": "Labour", "href": "/labour"},
    {"kind": "Page", "label": "Goals", "href": "/goals"},
    {"kind": "Page", "label": "Procurement", "href": "/procurement"},
    {"kind": "Page", "label": "Food cost", "href": "/food-cost"},
    {"kind": "Page", "label": "Vendors", "href": "/vendors"},
    {"kind": "Page", "label": "Store Health", "href": "/store-health"},
    {"kind": "Page", "label": "Store Master", "href": "/store-master"},
    {"kind": "Page", "label": "Data gaps", "href": "/data-gaps"},
    {"kind": "Page", "label": "Menu engineering", "href": "/menu"},
    {"kind": "Page", "label": "Menu & Costing", "href": "/menu-costing"},
    {"kind": "Page", "label": "Things we make", "href": "/menu-costing#things-we-make"},
    {"kind": "Page", "label": "Delivery vs dine-in", "href": "/channels"},
    {"kind": "Page", "label": "Tickets", "href": "/tickets"},
    {"kind": "Page", "label": "Red flags", "href": "/flags"},
    {"kind": "Page", "label": "Needs attention", "href": "/attention"},
    {"kind": "Page", "label": "Stores", "href": "/stores"},
    {"kind": "Menu", "label": "Ingredient Price Tracker", "href": "/ingredient-tracker/"},
    {"kind": "Menu", "label": "Zomato Settlement Uploader", "href": "/upload"},
    {"kind": "Menu", "label": "Location Finder", "href": "/location-finder"},
    {"kind": "Menu", "label": "Location model", "href": "/location-model"},
    {"kind": "Menu", "label": "Trello", "href": "https://trello.com/"},
    {"kind": "Menu", "label": "Buzzready", "href": "https://www.buzzready.app/"},
    {"kind": "Menu", "label": "Keka", "href": "https://www.keka.com/"},
    {"kind": "Menu", "label": "Insights", "href": "https://insights.posist.co/login"},
    {"kind": "Menu", "label": "Posist", "href": "https://dosacoffee.posist.biz/login"},
    {"kind": "Menu", "label": "Fame Pilot", "href": "https://famepilot.com/"},
    {"kind": "Menu", "label": "Reelo", "href": "https://app.reelo.io/"},
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
