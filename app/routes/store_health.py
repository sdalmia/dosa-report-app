import logging
from io import BytesIO

from flask import Blueprint, redirect, render_template, request, send_file, url_for

from app.fragments import html_fragment
from app.page_cache import freeze, remember
from app.routes.main import login_required
from app.store_health.context_slots import build_context_slots
from app.store_health.contract import load_feeds
from app.store_health.insights import build_insights
from app.store_health.pdf_report import render_store_pdf
from app.store_health.present import (
    _window_bounds,
    build_view,
    business_today,
    calendar_bounds,
    format_date,
    grouped_stores,
    list_stores,
    parse_range,
    resolve_store,
)
from app.view_filters import city_region, remember_filters, resolve_bounds, store_options, visible_stores

store_health_bp = Blueprint("store_health", __name__)
log = logging.getLogger(__name__)


def _cached_feeds():
    from app.store_health.contract import data_directory

    directory = str(data_directory())
    return remember(("feeds", directory), load_feeds)


def _assemble(token, args, filters=None):
    today = business_today()
    key = (
        "store-health",
        token or "",
        today.isoformat(),
        freeze(dict(args or {})),
        freeze(filters or {}),
    )

    def build():
        return _assemble_now(token, args, filters, today)

    return remember(key, build)


def _assemble_now(token, args, filters, today):
    feeds = _cached_feeds()
    selection = parse_range(args, today, default_span=calendar_bounds(feeds))
    stores = list_stores(feeds)
    store = resolve_store(stores, token)
    start, end = _window_bounds(feeds)
    window = resolve_bounds(filters or {}, start, end)
    menu_window = window if window[0] and window[1] else None
    posist_bounds = menu_window if (filters or {}).get("cc_range") else None
    view = build_view(feeds, store, selection, today, menu_window=menu_window, posist_bounds=posist_bounds)
    insights = build_insights(feeds, store)
    context_slots = build_context_slots(store, today)
    for warning in feeds.get("warnings") or []:
        log.warning("%s", warning)
    return {
        "today": today,
        "selection": selection,
        "feeds": feeds,
        "stores": stores,
        "token": token,
        "store": store,
        "view": view,
        "insights": insights,
        "context_slots": context_slots,
    }


@store_health_bp.route("/store-health")
@store_health_bp.route("/store-health/<store_id>")
@login_required
def page(store_id=None):
    filters = remember_filters()
    if "cc_store" in request.args:
        wanted = filters.get("cc_store") or ""
        current = (store_id or "").strip()
        if wanted != current:
            target = url_for("store_health.page", store_id=wanted) if wanted else url_for("store_health.page")
            return redirect(target)
    return render_template("store_health/page.html", **_view_context(store_id, filters))


def _view_context(store_id, filters):
    token = (store_id or request.args.get("store") or filters.get("cc_store") or "").strip()
    packed = _assemble(token, request.args, filters)
    options = visible_stores(store_options(), filters)
    region = city_region(filters)
    groups = grouped_stores(packed["stores"])
    if region:
        groups = [(name, items) for name, items in groups if name == region]
    store = packed["store"]
    selection = packed["selection"]
    return {
        "store": store,
        "unknown_store": bool(packed["token"]) and store is None,
        "unknown_token": packed["token"] if packed["token"] and store is None else "",
        "groups": groups,
        "filters": filters,
        "filter_stores": options,
        "selection": selection,
        "day_label": format_date(selection["day"]) if selection["day"] else "",
        "match_keys": sorted(store.match_keys(), key=str.lower) if store else [],
        "insights": packed["insights"],
        "context_slots": packed["context_slots"],
        **packed["view"],
    }


_FRAGMENTS = {
    "menu": "store_health/_menu_mix.html",
    "delivery": "store_health/_delivery_mix.html",
    "calendar": "store_health/_calendar.html",
}


@store_health_bp.route("/store-health/fragment/<name>")
@store_health_bp.route("/store-health/<store_id>/fragment/<name>")
@login_required
def fragment(name, store_id=None):
    template = _FRAGMENTS.get(name)
    if template is None:
        return ("Unknown section", 404)
    filters = remember_filters()
    body = render_template(template, **_view_context(store_id, filters))
    return html_fragment(body)


@store_health_bp.route("/store-health/<store_id>/print")
@login_required
def print_pdf(store_id):
    filters = remember_filters()
    token = (store_id or "").strip()
    packed = _assemble(token, request.args, filters)
    store = packed["store"]
    if store is None:
        return "No store matches that name.", 404
    pdf = render_store_pdf(
        store,
        packed["selection"],
        packed["view"],
        packed["insights"],
        packed["context_slots"],
    )
    filename = f"store-health-{store.id}.pdf"
    response = send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
