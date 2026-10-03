from flask import Blueprint, render_template, request, send_file
from io import BytesIO

from app.routes.main import login_required
from app.store_health.context_slots import build_context_slots
from app.store_health.contract import load_feeds
from app.store_health.insights import build_insights
from app.store_health.pdf_report import render_store_pdf
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


def _assemble(token, args):
    today = business_today()
    selection = parse_range(args, today)
    feeds = load_feeds()
    stores = list_stores(feeds)
    store = resolve_store(stores, token)
    view = build_view(feeds, store, selection, today)
    insights = build_insights(feeds, store)
    context_slots = build_context_slots(store, today)
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
    token = (store_id or request.args.get("store") or "").strip()
    packed = _assemble(token, request.args)
    store = packed["store"]
    selection = packed["selection"]
    return render_template(
        "store_health/page.html",
        store=store,
        unknown_store=bool(packed["token"]) and store is None,
        unknown_token=packed["token"] if packed["token"] and store is None else "",
        groups=grouped_stores(packed["stores"]),
        selection=selection,
        warnings=packed["feeds"]["warnings"],
        day_label=format_date(selection["day"]) if selection["day"] else "",
        match_keys=sorted(store.match_keys(), key=str.lower) if store else [],
        insights=packed["insights"],
        context_slots=packed["context_slots"],
        **packed["view"],
    )


@store_health_bp.route("/store-health/<store_id>/print")
@login_required
def print_pdf(store_id):
    token = (store_id or "").strip()
    packed = _assemble(token, request.args)
    store = packed["store"]
    if store is None:
        return "No store matches that name.", 404
    pdf = render_store_pdf(
        store,
        packed["selection"],
        packed["view"],
        packed["insights"],
        packed["context_slots"],
        packed["feeds"]["warnings"],
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
