from flask import Blueprint, render_template, request

from app.menu_ops.channels import build_channels
from app.menu_ops.engineering import NO_CATEGORY, NO_REGION, QUADRANT_LABELS, build_menu
from app.menu_ops.tickets import build_tickets
from app.routes.main import login_required
from app.store_health.contract import load_feeds
from app.store_health.present import _window_bounds
from app.view_filters import city_region, remember_filters, resolve_bounds, store_options, visible_stores

menu_ops_bp = Blueprint(
    "menu_ops",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/menu-ops-static",
)


def _shared_filters():
    filters = remember_filters()
    feeds = load_feeds()
    start, end = _window_bounds(feeds)
    window = resolve_bounds(filters, start, end)
    options = visible_stores(store_options(), filters)
    return filters, window, options


def _filter_store(filters):
    wanted = (filters.get("cc_store") or "").strip()
    if not wanted:
        return ""
    for store in store_options():
        if store.get("id") == wanted:
            return store.get("label") or ""
    return ""


@menu_ops_bp.route("/menu")
@login_required
def menu():
    filters, window, options = _shared_filters()
    region = request.args.get("region", "").strip() or city_region(filters)
    store = request.args.get("store", "").strip() or _filter_store(filters)
    view = build_menu(
        category=request.args.get("category", "").strip(),
        region=region,
        store=store,
        quadrant=request.args.get("quadrant", "").strip(),
        window=window,
    )
    return render_template(
        "menu.html",
        view=view,
        quadrants=QUADRANT_LABELS,
        no_category=NO_CATEGORY,
        no_region=NO_REGION,
        filters=filters,
        filter_stores=options,
    )


@menu_ops_bp.route("/channels")
@login_required
def channels():
    filters, window, options = _shared_filters()
    store = request.args.get("store", "").strip() or _filter_store(filters)
    view = build_channels(store=store, region=city_region(filters), window=window)
    return render_template(
        "channels.html",
        view=view,
        filters=filters,
        filter_stores=options,
    )


@menu_ops_bp.route("/tickets")
@login_required
def tickets():
    view = build_tickets(
        store=request.args.get("store", "").strip(),
        keyword=request.args.get("keyword", "").strip(),
    )
    return render_template("tickets.html", view=view)
