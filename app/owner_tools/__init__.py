from flask import Blueprint

owner_bp = Blueprint(
    "owner",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/owner-static",
)

from . import routes  # noqa: E402,F401
