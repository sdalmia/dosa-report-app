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


@main_bp.route('/dashboard')
@login_required
def dashboard():
    user_info = session.get('user') or {}
    region = (request.args.get("region") or "").strip()
    if region not in {"", "East", "North"}:
        region = ""
    low_only = (request.args.get("low") or "").strip() == "1"
    view = build_owner_dashboard(region=region, low_only=low_only)
    flags, flag_state = _flag_view()
    return render_template(
        'dashboard.html',
        user_name=user_info.get('name') or "",
        flags=flags[:5],
        flag_count=len(flags),
        flag_state=flag_state,
        **view,
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


@main_bp.route("/flags.json")
@login_required
def flags_json():
    flags, _state = _flag_view()
    return jsonify({"flags": [flag_public_dict(row) for row in flags]})

