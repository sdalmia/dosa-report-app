from flask import Blueprint, render_template, request

from app.menu_ops.channels import build_channels
from app.menu_ops.engineering import NO_CATEGORY, NO_REGION, QUADRANT_LABELS, build_menu
from app.menu_ops.tickets import build_tickets
from app.routes.main import login_required

menu_ops_bp = Blueprint(
    "menu_ops",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/menu-ops-static",
)


@menu_ops_bp.route("/menu")
@login_required
def menu():
    view = build_menu(
        category=request.args.get("category", "").strip(),
        region=request.args.get("region", "").strip(),
        store=request.args.get("store", "").strip(),
        quadrant=request.args.get("quadrant", "").strip(),
    )
    return render_template(
        "menu.html",
        view=view,
        quadrants=QUADRANT_LABELS,
        no_category=NO_CATEGORY,
        no_region=NO_REGION,
    )


@menu_ops_bp.route("/channels")
@login_required
def channels():
    view = build_channels(store=request.args.get("store", "").strip())
    return render_template("channels.html", view=view)


@menu_ops_bp.route("/tickets")
@login_required
def tickets():
    view = build_tickets(
        store=request.args.get("store", "").strip(),
        keyword=request.args.get("keyword", "").strip(),
    )
    return render_template("tickets.html", view=view)
