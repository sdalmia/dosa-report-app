from datetime import date
from pathlib import Path

from flask import Blueprint, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app.access import is_owner, owner_required
from app.menu_costing.catalog import (
    CHANNELS,
    build_item,
    build_page,
    diff_items,
    owner_count,
    owner_rupee,
    present_line,
    vs_own_city,
)
from app.menu_costing.history import dish_history, load_history, present_history
from app.menu_costing.parse_menu import parse_upload
from app.menu_costing.pnl import load_pnl
from app.menu_costing.recipes import load_recipes
from app.menu_costing.sales import load_sales
from app.menu_costing.versions import save_version, version_dicts
from app.procurement.numbers import format_pct
from app.routes.main import login_required

menu_bp = Blueprint(
    "menu_costing",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/menu-costing/static",
)

_UPLOAD_LIMIT = 15 * 1024 * 1024


@menu_bp.route("/menu")
@login_required
def menu_page():
    recipes = load_recipes()
    page = build_page(
        recipes,
        load_sales(),
        version_dicts(),
        city=(request.args.get("city") or "").strip(),
        channel=(request.args.get("channel") or "").strip(),
        store=(request.args.get("store") or "").strip(),
        query=(request.args.get("q") or "").strip(),
        today=date.today(),
    )
    page["is_owner"] = is_owner()
    return render_template("menu.html", **page)


@menu_bp.route("/menu/item")
@login_required
def item_page():
    recipes = load_recipes()
    detail = build_item(
        recipes,
        city=(request.args.get("city") or "").strip(),
        store=(request.args.get("store") or "").strip(),
        item=(request.args.get("item") or "").strip(),
    )
    chosen = detail["chosen"]
    detail["chosen_cost"] = owner_rupee(chosen["cost"]) if chosen else ""
    detail["chosen_vs"] = vs_own_city(chosen["vs_pct"], detail["city"]) if chosen else ""
    detail["median_text"] = ""
    summary = detail["summary"]
    if summary and summary.get("median") is not None:
        detail["median_text"] = owner_rupee(summary["median"])
        detail["spread_text"] = format_pct(summary.get("spread"))
    else:
        detail["spread_text"] = ""
    detail["store_cards"] = [
        {
            "outlet": row["outlet"],
            "cost": owner_rupee(row["cost"]),
            "vs": vs_own_city(row["vs_pct"], detail["city"]),
            "incomplete": bool(row.get("incomplete")),
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
    detail["is_owner"] = is_owner()
    return render_template("item.html", **detail)


@menu_bp.route("/menu/history")
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
    city = (request.args.get("city") or "").strip()
    if city not in recipes["cities"]:
        city = recipes["cities"][0] if recipes["cities"] else ""
    outlets = recipes["outlets"].get(city, [])
    store = (request.args.get("store") or "").strip()
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
        is_owner=is_owner(),
        cities=recipes["cities"],
        outlets=outlets,
        city=city,
        store=store,
        item=item,
        **recipe,
    )


@menu_bp.route("/menu/pl")
@owner_required
def pnl_page():
    report = load_pnl()
    return render_template("pnl.html", is_owner=True, **report)


@menu_bp.route("/menu/upload", methods=["GET", "POST"])
@owner_required
def upload_page():
    recipes = load_recipes()
    error = ""
    if request.method == "POST":
        error = _accept_upload(recipes)
        if not error:
            return redirect(url_for("menu_costing.history_page"))
    return render_template(
        "upload.html",
        cities=recipes["cities"],
        channels=CHANNELS,
        outlets=sorted({name for names in recipes["outlets"].values() for name in names}),
        error=error,
        is_owner=True,
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
