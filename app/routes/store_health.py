from flask import Blueprint, render_template, request

from app.routes.main import login_required
from app.store_health.contract import load_feeds
from app.store_health.present import (
    build_view,
    business_today,
    format_date,
    grouped_stores,
    list_stores,
    parse_range,
    resolve_store,
)

store_health_bp = Blueprint("store_health", __name__)


@store_health_bp.route("/store-health")
@store_health_bp.route("/store-health/<store_id>")
@login_required
def page(store_id=None):
    today = business_today()
    selection = parse_range(request.args, today)
    feeds = load_feeds()
    stores = list_stores(feeds)
    token = (store_id or request.args.get("store") or "").strip()
    store = resolve_store(stores, token)
    view = build_view(feeds, store, selection, today)
    return render_template(
        "store_health/page.html",
        store=store,
        unknown_store=bool(token) and store is None,
        unknown_token=token if token and store is None else "",
        groups=grouped_stores(stores),
        selection=selection,
        warnings=feeds["warnings"],
        day_label=format_date(selection["day"]) if selection["day"] else "",
        match_keys=sorted(store.match_keys(), key=str.lower) if store else [],
        **view,
    )
