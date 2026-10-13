from flask import Blueprint

grand_economics_bp = Blueprint("grand_economics", __name__)

from . import routes  # noqa: E402,F401
