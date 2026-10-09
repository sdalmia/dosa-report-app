from flask import Blueprint, jsonify, render_template, request

from app.procurement.food_cost import build_food_cost
from app.procurement.loader import load_procurement
from app.procurement.recipe import recipe_costs
from app.procurement.vendors import build_vendors
from app.routes.main import login_required

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
    return render_template("food_cost.html", **build_food_cost(load_procurement()))


@procurement_bp.route("/food-cost/recipe-cost.json")
@login_required
def recipe_cost_json():
    """Recipe cost for the menu-engineering page. Margin is null until a selling price exists."""
    payload = recipe_costs(
        outlet=request.args.get("outlet") or None,
        menu_item=request.args.get("item") or None,
        include_lines=request.args.get("lines") == "1",
        include_non_menu=request.args.get("all") == "1",
    )
    return jsonify(payload)


@procurement_bp.route("/vendors")
@login_required
def vendors():
    selected = (request.args.get("item") or "").strip() or None
    return render_template("vendors.html", **build_vendors(load_procurement(), selected))
