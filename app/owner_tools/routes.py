"""Owner pages. These routes never send mail."""

from flask import jsonify, redirect, render_template, request, Response, session, url_for

from app.access import is_owner, owner_required, signed_in_email
from app.fragments import html_fragment
from app.page_cache import freeze, remember
from app.dbstatus import database_health
from app.gaps import filter_gaps, gap_counts, group_gaps_by_owner, load_gap_board
from app.routes.main import login_required
from app.store_health.contract import load_feeds
from app.store_master import get_index
from app.view_filters import city_region, remember_filters, resolve_bounds, store_options, visible_stores

from . import owner_bp
from .metrics import build_brief, build_goals, build_labour, build_scorecard, festive_available, resolve_month
from .sources import load_goals, load_wastage, scan_famepilot, scan_procurement
from .text import render_brief_text


def _feeds():
    from app.store_health.contract import data_directory

    directory = str(data_directory())
    return remember(("feeds", directory), load_feeds)


def _brief_payload():
    def build():
        feeds = _feeds()
        attention = scan_famepilot(feeds.get("directory"))
        return build_brief(feeds, attention, scan_procurement())

    return remember(("brief",), build)


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


@owner_bp.route("/brief/fragment/rest")
@login_required
def brief_rest():
    return html_fragment(render_template("owner/_brief_rest.html", brief=_brief_payload()))


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


def _scorecard_payload(filters):
    feeds = _feeds()
    wastage = load_wastage(feeds.get("directory"))
    month = (request.args.get("month") or "").strip()
    if not month and filters.get("cc_range"):
        from app.store_health.present import _window_bounds

        _start, end = resolve_bounds(filters, *_window_bounds(feeds))
        if end is not None:
            month = f"{end.year:04d}-{end.month:02d}"
    payload = remember(
        ("scorecard", month, freeze(filters)),
        lambda: build_scorecard(feeds, wastage, month),
    )
    payload = dict(payload)
    region = city_region(filters)
    wanted = filters.get("cc_store") or ""
    rows = list(payload.get("stores") or [])
    if region:
        rows = [row for row in rows if row.get("region") == region]
    if wanted:
        rows = [row for row in rows if row.get("id") == wanted]
    payload["stores"] = rows
    return payload


@owner_bp.route("/scorecard")
@login_required
def scorecard():
    filters = remember_filters()
    options = visible_stores(store_options(), filters)
    return render_template(
        "owner/scorecard.html",
        scorecard=_scorecard_payload(filters),
        active="scorecard",
        filters=filters,
        filter_stores=options,
    )


@owner_bp.route("/scorecard/fragment/rest")
@login_required
def scorecard_rest():
    filters = remember_filters()
    return html_fragment(render_template("owner/_scorecard_stores.html", scorecard=_scorecard_payload(filters)))


@owner_bp.route("/labour")
@login_required
def labour():
    labour_view = remember(("labour",), lambda: build_labour(_feeds()))
    return render_template("owner/labour.html", labour=labour_view, active="labour")


@owner_bp.route("/labour/fragment/rest")
@login_required
def labour_rest():
    labour_view = remember(("labour",), lambda: build_labour(_feeds()))
    return html_fragment(render_template("owner/_labour_stores.html", labour=labour_view))


@owner_bp.route("/goals")
@login_required
def goals():
    feeds = _feeds()
    requested = (request.args.get("month") or "").strip()
    selected, _available = resolve_month(feeds, requested)
    festive = _festive_choice(request.args.get("festive"), festive_available(feeds, selected))
    payload = remember(
        ("goals", selected, festive),
        lambda: build_goals(feeds, load_goals(), selected, festive),
    )
    return render_template("owner/goals.html", goals=payload, active="goals")


@owner_bp.route("/goals/fragment/rest")
@login_required
def goals_rest():
    feeds = _feeds()
    requested = (request.args.get("month") or "").strip()
    selected, _available = resolve_month(feeds, requested)
    festive = _festive_choice(request.args.get("festive"), festive_available(feeds, selected))
    payload = remember(
        ("goals", selected, festive),
        lambda: build_goals(feeds, load_goals(), selected, festive),
    )
    return html_fragment(render_template("owner/_goal_stores.html", goals=payload))


@owner_bp.route("/data-gaps")
@login_required
@owner_required
def data_gaps():
    filters = remember_filters()
    index = get_index()
    email = signed_in_email()
    board = remember(("gap-board", email or ""), lambda: load_gap_board(index.rows, email=email))
    gaps = filter_gaps(board["gaps"], filters, index)
    return render_template(
        "owner/data_gaps.html",
        counts=gap_counts(gaps),
        groups=group_gaps_by_owner(gaps),
        active="data-gaps",
        filters=filters,
        filter_stores=visible_stores(store_options(), filters),
    )


@owner_bp.route("/data-gaps/fragment/rest")
@login_required
@owner_required
def data_gaps_rest():
    filters = remember_filters()
    index = get_index()
    board = remember(
        ("gap-board", signed_in_email() or ""),
        lambda: load_gap_board(index.rows, email=signed_in_email()),
    )
    gaps = filter_gaps(board["gaps"], filters, index)
    return html_fragment(
        render_template("owner/_gap_groups.html", groups=group_gaps_by_owner(gaps), filters=filters)
    )


def _location_model_payload(message):
    from app.location_model import approval_log, model_page

    # Approvals live in the database, so the file mtime alone would keep a stale log.
    log = approval_log()
    head = log[0] if log else {}
    token = (len(log), head.get("action"), head.get("version"), str(head.get("at")))
    payload = dict(remember(("location-model", token), model_page))
    payload["message"] = message
    payload["approvals_persistent"] = database_health()["persistent"]
    return payload


def _location_model_page(message):
    return render_template("owner/location_model.html", model=_location_model_payload(message), active="location-model")


@owner_bp.route("/location-model/fragment/rest")
def location_model_rest():
    if "user" not in session and not session.get("user_email"):
        return redirect(url_for("google.login"))
    if not is_owner():
        return redirect(url_for("main.dashboard"))
    return html_fragment(render_template("owner/_model_rest.html", model=_location_model_payload("")))


@owner_bp.route("/location-model", methods=["GET", "POST"])
def location_model():
    from app.location_model import approve_model, revert_model

    if request.method == "POST":
        if not is_owner():
            return ("Only an owner can change the live model.", 403)
        action = (request.form.get("action") or "approve").strip()
        confirmed = (request.form.get("confirm") or "").strip() == "yes"
        if not database_health()["persistent"]:
            # The page already shows this sentence. A blank message keeps it to one line.
            message = ""
            status = 400
        elif not confirmed:
            message = "Tick the confirm box first."
            status = 400
        elif action == "revert":
            result = revert_model(signed_in_email())
            if result is None:
                message = "There is no approved model to undo."
                status = 400
            elif result["live"] == "prior":
                message = "Reverted. Live scores use the prior weights."
                status = 200
            else:
                message = f"Reverted. Live scores use {result['live']}."
                status = 200
        else:
            version = (request.form.get("version") or "").strip()
            approved = approve_model(version, signed_in_email())
            message = "Approved." if approved else "That model is not on file."
            status = 200 if approved else 400
        return _location_model_page(message), status

    if "user" not in session and not session.get("user_email"):
        return redirect(url_for("google.login"))
    if not is_owner():
        return redirect(url_for("main.dashboard"))
    return _location_model_page("")


@owner_bp.route("/store-master")
@login_required
@owner_required
def store_master():
    filters = remember_filters()
    return render_template(
        "owner/store_master.html",
        stores=_store_master_rows(filters),
        active="store-master",
        filters=filters,
        filter_stores=visible_stores(store_options(), filters),
    )


def _store_master_rows(filters):
    rows = []
    wanted = (filters.get("cc_store") or "").strip()
    region = city_region(filters)
    for row in get_index().rows:
        if wanted and row.get("store_id") != wanted:
            continue
        if region and (row.get("region") or "") != region:
            continue
        name = row.get("display_name") or row.get("posist_name") or ""
        line = " · ".join(
            part for part in (row.get("city"), row.get("region"), row.get("format"), row.get("status")) if part
        )
        rows.append({"store_id": row.get("store_id") or "", "name": name, "line": line})
    rows.sort(key=lambda row: row["name"].casefold())
    return rows


@owner_bp.route("/store-master/fragment/rest")
@login_required
@owner_required
def store_master_rest():
    return html_fragment(render_template("owner/_store_cards.html", stores=_store_master_rows(remember_filters())))
