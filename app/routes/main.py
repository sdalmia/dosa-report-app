from flask import Blueprint, jsonify, render_template, request, session

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


@main_bp.route('/dashboard')
@login_required
def dashboard():
    user_info = session.get('user') or {}
    view, _region, _low_only = _dashboard_view()
    filters, filter_stores = _filter_context()
    flags, flag_state = _flag_view()
    finance = None
    if is_owner():
        from app.grand_economics.loader import home_finance

        finance = home_finance()
    return render_template(
        'dashboard.html',
        user_name=user_info.get('name') or "",
        flags=flags[:5],
        flag_count=len(flags),
        flag_state=flag_state,
        filters=filters,
        filter_stores=filter_stores,
        finance=finance,
        **{**view, "procurement": narrow_tiles(view.get("procurement"), filters)},
    )


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

