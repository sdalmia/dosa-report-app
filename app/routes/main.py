from flask import Blueprint, jsonify, render_template, request, session
from functools import wraps
from flask import redirect, url_for

from app.access import signed_in_email
from app.flags import (
    flag_files_present,
    flag_public_dict,
    group_flags,
    load_flag_rows,
    visible_flags,
)
from app.owner_dashboard import build_owner_dashboard
from app.search_index import search_index
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
    return build_owner_dashboard(region=region, low_only=low_only, view_filters=filters), region, low_only


@main_bp.route('/dashboard')
@login_required
def dashboard():
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
    return jsonify({"results": search_index()})


@main_bp.route("/flags.json")
@login_required
def flags_json():
    flags, _state = _flag_view()
    return jsonify({"flags": [flag_public_dict(row) for row in flags]})

