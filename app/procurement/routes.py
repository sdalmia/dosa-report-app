from flask import Blueprint, jsonify, render_template, request, url_for

from app.fragments import html_fragment, matches, query_offset, query_text, slice_rows
from app.page_cache import remember
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


_RECIPE_FIELDS = ("menu_item", "city", "deployment", "outlet_min", "outlet_max", "unit")
_CONSUMED_FIELDS = ("menu_item",)


def _food_base():
    return remember(("food-cost",), lambda: build_food_cost(load_procurement()))


def _food_view():
    filters = remember_filters()
    base = _food_base()
    payload = dict(base)
    cities = list(base.get("cities") or [])
    stores = list(base.get("stores") or [])
    city = PROCUREMENT_CITY.get(filters.get("cc_city") or "")
    if city:
        cities = [row for row in cities if row.get("city") == city]
        stores = [row for row in stores if row.get("city") == city]
    label = selected_label(store_options(), filters).casefold()
    if label:
        stores = [
            row for row in stores
            if (row.get("name") or "").casefold() in label or label in (row.get("name") or "").casefold()
        ]
    payload["cities"] = cities
    payload["stores"] = stores
    return payload, filters


def _recipe_page(kind):
    payload, _filters = _food_view()
    recipe = payload.get("recipe") or {}
    query = query_text()
    source = recipe.get("consumption_rows") if kind == "consumed" else recipe.get("rows")
    fields = _CONSUMED_FIELDS if kind == "consumed" else _RECIPE_FIELDS
    rows = [row for row in source or [] if matches(row, query, fields)]
    chunk, nxt, total = slice_rows(rows, query_offset())
    more = None
    if nxt is not None:
        more = url_for("procurement.food_cost_rows", kind=kind, offset=nxt, q=query or None)
    return recipe, chunk, nxt, total, more


@procurement_bp.route("/food-cost")
@login_required
def food_cost():
    payload, filters = _food_view()
    options = visible_stores(store_options(), filters)
    return render_template("food_cost.html", filters=filters, filter_stores=options, **payload)


@procurement_bp.route("/food-cost/fragment/recipe")
@login_required
def food_cost_recipe():
    recipe, rows, _nxt, total, more = _recipe_page("rows")
    _recipe, consumed, _cnxt, ctotal, cmore = _recipe_page("consumed")
    body = render_template(
        "_recipe.html",
        recipe=recipe,
        recipe_rows=rows,
        recipe_total=total,
        recipe_more=more,
        consumption_rows=consumed,
        consumption_total=ctotal,
        consumption_more=cmore,
    )
    return html_fragment(body)


@procurement_bp.route("/food-cost/fragment/rows/<kind>")
@login_required
def food_cost_rows(kind):
    if kind not in {"rows", "consumed"}:
        return ("Unknown list", 404)
    recipe, rows, _nxt, total, more = _recipe_page(kind)
    body = render_template(
        "_recipe_rows.html",
        kind=kind,
        recipe=recipe,
        rows=rows,
        total=total,
        more=more,
    )
    return html_fragment(body)


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


def _vendors_payload(selected):
    return remember(("vendors", selected or ""), lambda: build_vendors(load_procurement(), selected))


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
        **_vendors_payload(selected),
    )


@procurement_bp.route("/vendors/fragment/rest")
@login_required
def vendors_rest():
    filters = remember_filters()
    selected = (request.args.get("item") or "").strip() or None
    return html_fragment(render_template("_vendors_body.html", **_vendors_payload(selected)))
