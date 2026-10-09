"""Owner pages. These routes never send mail."""

from flask import jsonify, render_template, request, Response

from app.access import owner_required
from app.routes.main import login_required
from app.store_health.contract import load_feeds
from app.store_master import get_index, human_notes, store_gaps
from app.view_filters import city_region, remember_filters, resolve_bounds, store_options, visible_stores

from . import owner_bp
from .metrics import build_brief, build_goals, build_labour, build_scorecard, festive_available, resolve_month
from .sources import load_goals, load_wastage, scan_famepilot, scan_procurement
from .text import render_brief_text


def _feeds():
    return load_feeds()


def _brief_payload():
    feeds = _feeds()
    attention = scan_famepilot(feeds.get("directory"))
    return build_brief(feeds, attention, scan_procurement())


def _festive_choice(raw, available):
    text = (raw or "").strip().lower()
    if text in {"0", "off", "false", "no"}:
        return False
    if text in {"1", "on", "true", "yes"}:
        return True
    return available


@owner_bp.route("/brief")
@login_required
def brief():
    return render_template("owner/brief.html", brief=_brief_payload(), active="brief")


@owner_bp.route("/brief.json")
@login_required
def brief_json():
    return jsonify(_brief_payload())


@owner_bp.route("/brief.txt")
@login_required
def brief_text():
    body = render_brief_text(_brief_payload())
    return Response(body, mimetype="text/plain; charset=utf-8")


@owner_bp.route("/brief/email")
@login_required
def brief_email():
    """HTML the external emailer can copy. This view does not send it."""
    return render_template("owner/email.html", brief=_brief_payload())


@owner_bp.route("/scorecard")
@login_required
def scorecard():
    filters = remember_filters()
    feeds = _feeds()
    wastage = load_wastage(feeds.get("directory"))
    month = (request.args.get("month") or "").strip()
    if not month and filters.get("cc_range"):
        from app.store_health.present import _window_bounds

        _start, end = resolve_bounds(filters, *_window_bounds(feeds))
        if end is not None:
            month = f"{end.year:04d}-{end.month:02d}"
    payload = build_scorecard(feeds, wastage, month)
    region = city_region(filters)
    wanted = filters.get("cc_store") or ""
    rows = payload.get("stores") or []
    if region:
        rows = [row for row in rows if row.get("region") == region]
    if wanted:
        rows = [row for row in rows if row.get("id") == wanted]
    payload["stores"] = rows
    options = visible_stores(store_options(), filters)
    return render_template(
        "owner/scorecard.html",
        scorecard=payload,
        active="scorecard",
        filters=filters,
        filter_stores=options,
    )


@owner_bp.route("/labour")
@login_required
def labour():
    return render_template("owner/labour.html", labour=build_labour(_feeds()), active="labour")


@owner_bp.route("/goals")
@login_required
def goals():
    feeds = _feeds()
    requested = (request.args.get("month") or "").strip()
    selected, _available = resolve_month(feeds, requested)
    festive = _festive_choice(request.args.get("festive"), festive_available(feeds, selected))
    payload = build_goals(feeds, load_goals(), selected, festive)
    return render_template("owner/goals.html", goals=payload, active="goals")


GAP_FILTERS = (
    ("", "All"),
    ("google", "No Google listing"),
    ("reelo", "Not on Reelo"),
    ("delivery", "No Swiggy or Zomato"),
    ("unverified", "Unverified listing"),
    ("duplicate", "Duplicate listing"),
    ("name", "Name mismatch"),
)


@owner_bp.route("/data-gaps")
@login_required
@owner_required
def data_gaps():
    selected = (request.args.get("gap") or "").strip()
    if selected not in {key for key, _label in GAP_FILTERS}:
        selected = ""
    cards = []
    counts = {key: 0 for key, _label in GAP_FILTERS if key}
    for row in get_index().rows:
        gaps = store_gaps(row)
        for gap in gaps:
            counts[gap["kind"]] = counts.get(gap["kind"], 0) + 1
        shown = [gap for gap in gaps if not selected or gap["kind"] == selected]
        if not shown:
            continue
        note = human_notes(row.get("notes"))
        if any(gap["detail"] == note for gap in shown):
            note = ""
        place = " · ".join(part for part in (row.get("city"), row.get("format")) if part)
        cards.append(
            {
                "store_id": row.get("store_id"),
                "name": row.get("display_name") or row.get("posist_name"),
                "place": place,
                "note": note,
                "gaps": shown,
            }
        )
    cards.sort(key=lambda card: card["name"].casefold())
    return render_template(
        "owner/data_gaps.html",
        cards=cards,
        filters=GAP_FILTERS,
        counts=counts,
        selected=selected,
        active="data-gaps",
    )
