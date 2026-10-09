from flask import Blueprint, jsonify, render_template, request

from app.procurement.food_cost import build_food_cost
from app.procurement.loader import load_procurement
from app.procurement.recipe import recipe_costs
from app.procurement.vendors import build_vendors
from app.routes.main import login_required
from app.view_filters import (
    PROCUREMENT_CITY,
    remember_filters,
    selected_label,
    store_options,
    visible_stores,
)

procurement_bp = Blueprint(
    "procurement",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/procurement/static",
)


@procurement_bp.route("/food-cost")
@login_required
def food_cost():
    filters = remember_filters()
    payload = build_food_cost(load_procurement())
    city = PROCUREMENT_CITY.get(filters.get("cc_city") or "")
    if city:
        payload["cities"] = [row for row in payload.get("cities") or [] if row.get("city") == city]
        payload["stores"] = [row for row in payload.get("stores") or [] if row.get("city") == city]
    label = selected_label(store_options(), filters).casefold()
    if label:
        payload["stores"] = [
            row for row in payload.get("stores") or []
            if (row.get("name") or "").casefold() in label or label in (row.get("name") or "").casefold()
        ]
    options = visible_stores(store_options(), filters)
    return render_template("food_cost.html", filters=filters, filter_stores=options, **payload)


@procurement_bp.route("/food-cost/recipe-cost.json")
@login_required
def recipe_cost_json():
    """Recipe cost for the menu-engineering page. Margin is null until a selling price exists."""
    tab = (request.args.get("tab") or "").strip()
    payload = recipe_costs(
        outlet=request.args.get("outlet") or None,
        menu_item=request.args.get("item") or None,
        include_lines=request.args.get("lines") == "1",
        include_non_menu=request.args.get("all") == "1",
        recipe_tab=None if tab in {"", "all"} else tab,
    )
    return jsonify(payload)


@procurement_bp.route("/vendors")
@login_required
def vendors():
    filters = remember_filters()
    selected = (request.args.get("item") or "").strip() or None
    options = visible_stores(store_options(), filters)
    return render_template(
        "vendors.html",
        filters=filters,
        filter_stores=options,
        **build_vendors(load_procurement(), selected),
    )
