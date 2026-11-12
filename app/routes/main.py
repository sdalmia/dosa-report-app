from flask import Blueprint, Response, jsonify, render_template, request, session, stream_with_context

from app.fragments import html_fragment, query_offset, slice_rows
from app.page_cache import freeze, remember
from functools import wraps
from flask import redirect, url_for

from app.access import is_owner, owner_required, signed_in_email
from app.frontlyne import load_summary
from app.dbstatus import database_health
from app.flags import (
    flag_files_present,
    flag_public_dict,
    group_flags,
    load_flag_rows,
    visible_flags,
)
from app.owner_dashboard import build_owner_dashboard
from app.search_index import search_index
from app.store_health.contract import data_directory, load_feeds
from app.store_health.present import business_today, list_stores
from app.targets import build_board
from app.view_filters import narrow_tiles, remember_filters, store_options, visible_stores

main_bp = Blueprint('main', __name__)

# def login_required(f):
#     @wraps(f)
#     def decorated(*args, **kwargs):
#         if 'user' not in session:
#             return redirect(url_for('google.login'))
#         return f(*args, **kwargs)
#     return decorated

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            print("🚫 'user' not in session — redirecting to Google login")
            return redirect(url_for('google.login'))
        print("✅ 'user' found in session")
        return f(*args, **kwargs)
    return decorated

    
@main_bp.route('/')
def home():
    return render_template('home.html')


@main_bp.route("/healthz/db")
def healthz_db():
    """Public. Dialect and whether approvals survive a deploy. Never the URL."""
    return jsonify(database_health())

def _flag_view():
    email = signed_in_email()
    loaded = flag_files_present()
    visible = visible_flags(load_flag_rows(), email) if loaded else []
    if not loaded:
        state = "missing"
    elif visible:
        state = "ready"
    else:
        state = "empty"
    return visible, state


def _filter_context():
    filters = remember_filters()
    return filters, visible_stores(store_options(), filters)


def _dashboard_view():
    filters, _stores = _filter_context()
    region = (request.args.get("region") or "").strip()
    if region not in {"", "East", "North"}:
        region = ""
    if filters.get("cc_city"):
        region = ""
    low_only = (request.args.get("low") or "").strip() == "1"
    key = ("dashboard", region, low_only, freeze(filters))
    view = remember(
        key,
        lambda: build_owner_dashboard(region=region, low_only=low_only, view_filters=filters),
    )
    return view, region, low_only


def _board_response():
    user_info = session.get('user') or {}
    view, _region, _low_only = _dashboard_view()
    filters, filter_stores = _filter_context()
    flags, flag_state = _flag_view()
    return render_template(
        'dashboard.html',
        user_name=user_info.get('name') or "",
        flags=flags[:5],
        flag_count=len(flags),
        flag_state=flag_state,
        filters=filters,
        filter_stores=filter_stores,
        **{**view, "procurement": narrow_tiles(view.get("procurement"), filters)},
    )


@main_bp.route('/dashboard')
@login_required
def dashboard():
    from app.chat.answer import configured
    from app.chat.snapshot import view_for
    from app.chat.suggestions import chips

    email = signed_in_email()
    data = view_for(email)
    owner = is_owner(email)
    pack = data.get("procurement") or {}
    shown = chips(
        owner,
        sales=bool(data.get("sales_loaded")),
        finance=bool(data.get("finance")),
        procurement=bool(pack.get("above_average") or pack.get("monthly_prices")),
        reelo=bool(data.get("reelo_loaded")),
        audit=bool(data.get("october_audit")),
    )
    summary = data.get("summary") or {}
    north = ((summary.get("regional_mtd") or {}).get("North") or {}).get("pace_pct")
    if north is not None:
        shown = [f"Why is North pace at {north}%?"] + [item for item in shown if "North pace" not in item]
    audit_q = "Which stores scored lowest in the October mystery audit?"
    if data.get("october_audit") and audit_q not in shown[:2]:
        shown = shown[:1] + [audit_q] + [item for item in shown if item != audit_q]
    shown = shown[:4]
    return render_template("chat.html", chips=shown, connected=configured())


@main_bp.route("/board")
@login_required
def board():
    """Previous home figures. Not linked from the nav."""
    return _board_response()


@main_bp.route("/dashboard/ask", methods=["POST"])
@login_required
def dashboard_ask():
    from app.chat.answer import iter_answer

    payload = request.get_json(silent=True) or {}
    question = payload.get("question") or ""
    return Response(
        stream_with_context(iter_answer(question, signed_in_email())),
        mimetype="text/event-stream",
    )


@main_bp.route("/api/ask", methods=["POST"])
def api_ask():
    import logging

    from app.chat.answer import produce_answer
    from app.chat.bots import authenticate
    from app.chat.facts import actions_from_data
    from app.chat.limit import allow
    from app.chat.snapshot import view_for

    bot = authenticate(request.headers.get("Authorization", ""))
    if bot is None:
        return jsonify({"error": "Unauthorised"}), 401
    if not allow("bot:" + bot["name"]):
        return jsonify({"error": "Too many questions just now."}), 429
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question") or "")
    mode = str(payload.get("mode") or "answer")
    logging.getLogger(__name__).info(
        "bot ask name=%s role=%s mode=%s question_chars=%s",
        bot["name"],
        bot["role"],
        mode,
        len(question),
    )
    data = view_for(role=bot["role"])
    owner = bot["role"] in {"owner", "finance"}
    result = produce_answer(question, data, owner, when_offline="local")
    from app.chat.memory import record_ask, record_gap

    ask_id = record_ask(
        question,
        result.get("topic") or "",
        result.get("as_of") or "",
        bot["role"],
        "bot",
        bot["name"],
    )
    record_gap(
        question,
        result.get("topic") or "",
        result.get("text") or "",
        result.get("as_of") or "",
        bot["role"],
        "bot",
        bot["name"],
    )
    actions = result.get("actions") or []
    if mode == "action_plan":
        actions = actions_from_data(data, owner)
        if actions and not result.get("actions"):
            result = dict(result)
            result["text"] = f"{actions[0]['what']} {actions[0]['why']}"
    return jsonify({
        "answer": result.get("text") or "",
        "data_as_of": result.get("as_of") or "",
        "table": result.get("table"),
        "chart": result.get("chart"),
        "actions": actions,
        "ask_id": ask_id,
        "topic": result.get("topic") or "",
    })


@main_bp.route("/dashboard/feedback", methods=["POST"])
@login_required
def dashboard_feedback():
    from app.chat.memory import record_rating

    payload = request.get_json(silent=True) or {}
    role = "owner" if is_owner(signed_in_email()) else "ops"
    record_rating(
        payload.get("ask_id"),
        payload.get("question"),
        payload.get("topic"),
        payload.get("data_as_of"),
        payload.get("rating"),
        payload.get("note"),
        role,
        "person",
        "",
    )
    return jsonify({"ok": True})


@main_bp.route("/api/chat/feedback", methods=["POST"])
def api_chat_feedback():
    import logging

    from app.chat.bots import authenticate
    from app.chat.memory import record_rating

    bot = authenticate(request.headers.get("Authorization", ""))
    if bot is None:
        return jsonify({"error": "Unauthorised"}), 401
    payload = request.get_json(silent=True) or {}
    logging.getLogger(__name__).info(
        "bot feedback name=%s role=%s rating=%s",
        bot["name"],
        bot["role"],
        str(payload.get("rating") or "")[:8],
    )
    record_rating(
        payload.get("ask_id"),
        payload.get("question"),
        payload.get("topic"),
        payload.get("data_as_of"),
        payload.get("rating"),
        payload.get("note"),
        bot["role"],
        "bot",
        bot["name"],
    )
    return jsonify({"ok": True})


@main_bp.route("/chat/insights")
@owner_required
def chat_insights():
    from app.chat.memory import window_summary

    return render_template(
        "chat_insights.html",
        week=window_summary(7),
        month=window_summary(30),
        sample=request.args.get("sample") == "1",
    )


@main_bp.route("/api/chat/insights")
def api_chat_insights():
    import logging

    from app.chat.bots import authenticate
    from app.chat.memory import window_summary

    bot = authenticate(request.headers.get("Authorization", ""))
    if bot is None:
        return jsonify({"error": "Unauthorised"}), 401
    if bot["role"] not in {"owner", "ops"}:
        return jsonify({"error": "Unauthorised"}), 403
    try:
        days = int(request.args.get("days") or 7)
    except (TypeError, ValueError):
        days = 7
    logging.getLogger(__name__).info("chat insights role=%s days=%s", bot["role"], days)
    return jsonify(window_summary(days))


@main_bp.route("/dashboard/targets")
@login_required
def dashboard_targets():
    filters = remember_filters()
    directory = str(data_directory())
    today = business_today()
    feeds = remember(("feeds", directory), load_feeds)
    store_label = ""
    wanted = (filters.get("cc_store") or "").strip()
    if wanted:
        for store in list_stores(feeds):
            if store.id == wanted:
                store_label = store.label
                break
    board = remember(
        ("targets", directory, today.isoformat(), freeze(filters)),
        lambda: build_board(
            feeds["posist"],
            today,
            store_label=store_label,
            city=(filters.get("cc_city") or "").strip(),
        ),
    )
    return html_fragment(render_template("_targets.html", board=board, frame="home"))


@main_bp.route("/dashboard/fragment/below")
@login_required
def dashboard_below():
    view, _region, _low_only = _dashboard_view()
    filters, _filter_stores = _filter_context()
    body = render_template(
        "dashboard_below.html",
        **{**view, "procurement": narrow_tiles(view.get("procurement"), filters)},
    )
    return html_fragment(body)


@main_bp.route("/dashboard/training")
@login_required
@owner_required
def dashboard_training():
    payload = load_summary() or {"cities": [], "course": []}
    return render_template("training.html", training=payload)


@main_bp.route("/stores")
@login_required
def stores_page():
    view, _region, _low_only = _dashboard_view()
    return render_template("stores.html", **view)


@main_bp.route("/attention")
@login_required
def attention_page():
    view, _region, _low_only = _dashboard_view()
    return render_template("attention.html", alerts=view["alerts"], window_subtitle=view["window_subtitle"])


@main_bp.route("/procurement")
@login_required
def procurement_page():
    view, _region, _low_only = _dashboard_view()
    filters, filter_stores = _filter_context()
    return render_template(
        "procurement.html",
        procurement=narrow_tiles(view["procurement"], filters),
        filters=filters,
        filter_stores=filter_stores,
    )


@main_bp.route("/flags")
@login_required
def flags_page():
    flags, flag_state = _flag_view()
    return render_template(
        "flags.html",
        groups=group_flags(flags),
        flag_state=flag_state,
    )


@main_bp.route("/search.json")
@login_required
def search_json():
    results = search_index()
    if not is_owner():
        results = [row for row in results if row.get("href") != "/grand-economics"]
    return jsonify({"results": results})


@main_bp.route("/flags.json")
@login_required
def flags_json():
    flags, _state = _flag_view()
    return jsonify({"flags": [flag_public_dict(row) for row in flags]})

