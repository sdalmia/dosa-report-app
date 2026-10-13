"""Owner page for city and store economics. The figures are already computed."""

import re

from flask import render_template

from app.access import owner_required
from app.fragments import html_fragment
from app.routes.main import login_required

from . import grand_economics_bp
from .loader import detail, ledger_for, stores, summary

_ANCHOR = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@grand_economics_bp.route("/grand-economics")
@login_required
@owner_required
def page():
    return render_template("grand_economics/page.html", summary=summary())


@grand_economics_bp.route("/grand-economics/stores")
@login_required
@owner_required
def stores_section():
    return html_fragment(render_template("grand_economics/_stores.html", stores=stores()))


@grand_economics_bp.route("/grand-economics/detail/<anchor>")
@login_required
@owner_required
def detail_section(anchor):
    if not _ANCHOR.match(anchor or ""):
        response = html_fragment(render_template("grand_economics/_missing.html"))
        response.status_code = 404
        return response
    panel = detail(anchor)
    if panel is None:
        response = html_fragment(render_template("grand_economics/_missing.html"))
        response.status_code = 404
        return response
    rows = ledger_for(panel.get("city"), panel.get("store"), panel.get("month_key"))
    body = render_template("grand_economics/_detail.html", detail=panel, ledger=rows)
    return html_fragment(body)
