from datetime import date
from pathlib import Path

from flask import Blueprint, redirect, render_template, request, url_for

from app.fragments import html_fragment, query_offset, slice_rows
from app.page_cache import freeze, remember
from markupsafe import escape
from werkzeug.utils import secure_filename

from app.access import owner_required
from app.menu_costing.catalog import (
    CHANNELS,
    build_item,
    build_page,
    diff_items,
    present_stubs,
    _stub_recipes,
    owner_count,
    owner_rupee,
    present_line,
    vs_own_city,
)
from app.menu_costing.history import dish_history, load_history, present_history
from app.menu_costing.parse_menu import parse_upload
from app.menu_costing.pnl import load_pnl
from app.menu_costing.batches import batch_page_context
from app.menu_costing.recipes import load_recipes
from app.menu_costing.sales import load_sales, sales_for_filters
from app.menu_costing.scope import filter_context, place_from_request
from app.view_filters import remember_filters
from app.menu_costing.versions import save_version, version_dicts
from app.procurement.numbers import format_pct
from app.routes.main import login_required

menu_bp = Blueprint(
    "menu_costing",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/menu-costing/static",
    url_prefix="/menu-costing",
)

_UPLOAD_LIMIT = 15 * 1024 * 1024


def _menu_context():
    recipes = load_recipes()
    filters, city, store = place_from_request(recipes)
    channel = (request.args.get("channel") or "").strip()
    query = (request.args.get("q") or "").strip()
    today = date.today()
    key = ("menu-page", city, store or "", channel, query, today.isoformat(), freeze(filters))

    def build():
        page = build_page(
            recipes,
            sales_for_filters(load_sales(), filters),
            version_dicts(),
            city=city,
            channel=channel,
            store=store,
            query=query,
            today=today,
        )
        page.update(filter_context(filters))
        page.update(
            batch_page_context(
                city=page["city"],
                store=page["store"],
                store_id=(filters.get("cc_store") or "").strip(),
                query=page["query"],
                filters=filters,
            )
        )
        return page

    return remember(key, build)


def _menu_rows_view(page, offset):
    view = dict(page)
    rows = list(page.get("rows") or [])
    chunk, nxt, total = slice_rows(rows, offset)
    view["rows"] = chunk
    view["menu_total"] = total
    view["menu_more"] = None
    if nxt is not None:
        view["menu_more"] = url_for(
            "menu_costing.menu_rows",
            city=page.get("city") or "",
            channel=page.get("channel") or "",
            store=page.get("store") or "",
            q=page.get("query") or None,
            offset=nxt,
        )
    return view


@menu_bp.route("/", strict_slashes=False)
@login_required
def menu_page():
    page = _menu_context()
    if page.get("query"):
        page = _menu_rows_view(page, 0)
    return render_template("costing_menu.html", **page)


@menu_bp.route("/fragment/rest")
@login_required
def menu_rest():
    page = _menu_rows_view(_menu_context(), query_offset())
    return html_fragment(render_template("costing_rest.html", **page))


@menu_bp.route("/fragment/rows")
@login_required
def menu_rows():
    page = _menu_rows_view(_menu_context(), query_offset())
    return html_fragment(render_template("_menu_rows.html", **page))


def _item_detail():
    recipes = load_recipes()
    filters, city, store = place_from_request(recipes)
    item = (request.args.get("item") or "").strip()
    key = ("menu-item", city, store or "", item, freeze(filters))

    def build():
        return _build_item_detail(recipes, filters, city, store, item)

    return remember(key, build)


def _build_item_detail(recipes, filters, city, store, item):
    recipes = load_recipes()
    filters, city, store = place_from_request(recipes)
    detail = build_item(
        recipes,
        city=city,
        store=store,
        item=item,
    )
    chosen = detail["chosen"]
    detail["chosen_cost"] = owner_rupee(chosen["cost"]) if chosen else ""
    detail["chosen_vs"] = vs_own_city(chosen["vs_pct"], detail["city"]) if chosen else ""
    detail["chosen_baseline"] = (chosen.get("baseline_text") or "") if chosen and chosen.get("vs_pct") is None else ""
    detail["median_text"] = ""
    summary = detail["summary"]
    if summary and summary.get("median") is not None:
        detail["median_text"] = owner_rupee(summary["median"])
        detail["spread_text"] = format_pct(summary.get("spread"))
        detail["blank_median_note"] = ""
    else:
        detail["spread_text"] = ""
        detail["blank_median_note"] = (summary.get("baseline_text") or "") if summary else ""
    stubs = present_stubs(_stub_recipes(recipes, load_sales(), detail["city"], detail["store"]))
    detail["stub_detail"] = next((row["detail"] for row in stubs if row["item"].casefold() == (detail["item"] or "").casefold()), "")
    detail["store_cards"] = [
        {
            "outlet": row["outlet"],
            "cost": owner_rupee(row["cost"]),
            "vs": vs_own_city(row["vs_pct"], detail["city"]),
            "incomplete": bool(row.get("incomplete")),
            "cost_kind": row.get("cost_kind") or "",
            "receipt_title": row.get("receipt_title") or "",
            "baseline_note": row.get("baseline_text") or "" if row.get("vs_pct") is None else "",
            "unpriced_count": (
                owner_count(row.get("unpriced_excl"))
                if row.get("incomplete") and row.get("unpriced_excl")
                else ""
            ),
        }
        for row in detail["stores"]
    ]
    detail["line_rows"] = [present_line(row) for row in detail["lines"]]
    detail["lines_total_text"] = owner_rupee(detail["lines_total"])
    detail["chosen_incomplete"] = bool(chosen and chosen.get("incomplete"))
    detail["chosen_unpriced"] = (
        owner_count(chosen.get("unpriced_excl"))
        if chosen and chosen.get("incomplete") and chosen.get("unpriced_excl")
        else ""
    )
    detail["median_incomplete"] = bool(summary and summary.get("incomplete"))
    detail.update(
        present_history(dish_history(load_history(), detail["city"], detail["store"], detail["item"]))
    )
    detail.update(filter_context(filters))
    detail["filter_hidden"] = f'<input type="hidden" name="item" value="{escape(detail["item"])}">'
    return detail


@menu_bp.route("/item")
@login_required
def item_page():
    return render_template("item.html", **_item_detail())


@menu_bp.route("/item/fragment/rest")
@login_required
def item_rest():
    return html_fragment(render_template("item_rest.html", **_item_detail()))


@menu_bp.route("/history")
@login_required
def history_page():
    versions = version_dicts()
    left_id = _int_arg("left")
    right_id = _int_arg("right")
    by_id = {row["id"]: row for row in versions}
    diff = None
    if left_id in by_id and right_id in by_id and left_id != right_id:
        older, newer = by_id[left_id], by_id[right_id]
        if (older["effective_from"], older["id"]) > (newer["effective_from"], newer["id"]):
            older, newer = newer, older
        diff = diff_items(older["items"], newer["items"])
        diff["older"] = older
        diff["newer"] = newer
        for row in diff["repriced"]:
            row["old_text"] = owner_rupee(row["old_price"])
            row["new_text"] = owner_rupee(row["new_price"])
        for row in diff["added"] + diff["removed"]:
            row["price_text"] = owner_rupee(row.get("price"))
    recipes = load_recipes()
    filters, city, store = place_from_request(recipes)
    if city not in recipes["cities"]:
        city = recipes["cities"][0] if recipes["cities"] else ""
    outlets = recipes["outlets"].get(city, [])
    if store not in outlets:
        store = ""
    item = (request.args.get("item") or "").strip()
    recipe = present_history(dish_history(load_history(), city, store, item))
    return render_template(
        "history.html",
        versions=versions,
        diff=diff,
        left_id=left_id,
        right_id=right_id,
        cities=recipes["cities"],
        outlets=outlets,
        city=city,
        store=store,
        item=item,
        **filter_context(filters),
        **recipe,
    )


@menu_bp.route("/pl")
@owner_required
def pnl_page():
    filters = remember_filters()
    report = load_pnl()
    city = filters.get("cc_city") or ""
    if city == "Kolkata":
        report["companies"] = [row for row in report["companies"] if row["name"] == "Kolkata"]
    elif city == "Delhi NCR":
        report["companies"] = [row for row in report["companies"] if row["name"] == "Delhi"]
    return render_template("pnl.html", **filter_context(filters), **report)


@menu_bp.route("/upload", methods=["GET", "POST"])
@owner_required
def upload_page():
    recipes = load_recipes()
    error = ""
    if request.method == "POST":
        error = _accept_upload(recipes)
        if not error:
            return redirect(url_for("menu_costing.history_page"))
    filters, _city, _store = place_from_request(recipes)
    return render_template(
        "upload.html",
        cities=recipes["cities"],
        channels=CHANNELS,
        outlets=sorted({name for names in recipes["outlets"].values() for name in names}),
        error=error,
        **filter_context(filters),
    )


def _accept_upload(recipes):
    city = (request.form.get("city") or "").strip()
    channel = (request.form.get("channel") or "").strip()
    scope = (request.form.get("store_scope") or "").strip()
    raw_date = (request.form.get("effective_from") or "").strip()
    upload = request.files.get("menu_file")
    if city not in recipes["cities"]:
        return "Choose a city."
    if channel not in CHANNELS:
        return "Choose a channel."
    try:
        effective = date.fromisoformat(raw_date)
    except ValueError:
        return "Choose the date this menu took effect."
    if upload is None or not upload.filename:
        return "Choose a menu file."
    payload = upload.read(_UPLOAD_LIMIT + 1)
    if len(payload) > _UPLOAD_LIMIT:
        return "That file is too large."
    parsed = parse_upload(upload.filename, payload)
    if parsed["error"]:
        return parsed["error"]
    version = save_version(
        city=city,
        channel=channel,
        store_scope=scope,
        effective_from=effective,
        source=Path(upload.filename).name,
        items=parsed["items"],
    )
    folder = Path(__file__).resolve().parents[2] / "data" / "menu_history"
    folder.mkdir(parents=True, exist_ok=True)
    safe = secure_filename(upload.filename) or "menu"
    (folder / f"{version.id}-{safe}").write_bytes(payload)
    return ""


def _int_arg(name):
    try:
        return int(request.args.get(name) or 0)
    except ValueError:
        return 0
