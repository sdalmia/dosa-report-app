import logging
import os
from flask import Flask, request
from flask_compress import Compress
from flask_mail import Mail
from flask_session import Session
from dotenv import load_dotenv
from .config import Config
from .extensions import db

# Libraries that log OAuth tokens, auth codes, and Authorization headers at DEBUG.
_QUIET_LOGGERS = (
    "requests_oauthlib",
    "oauthlib",
    "urllib3",
    "flask_dance",
    "asyncio",
)


def configure_logging(app):
    """INFO in production. DEBUG only when the app itself is in debug mode."""
    debug = bool(app.debug or app.config.get("DEBUG"))
    level = logging.DEBUG if debug else logging.INFO
    logging.getLogger().setLevel(level)
    app.logger.setLevel(level)
    if not debug:
        for name in _QUIET_LOGGERS:
            logging.getLogger(name).setLevel(logging.INFO)
        # oauthlib logs the Authorization header when this is set.
        os.environ.pop("OAUTHLIB_DEBUG", None)


def create_app():
    load_dotenv()

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))  # This is the folder where __init__.py lives

    app = Flask(__name__, static_folder="../static")
    app.config.from_object(Config)

    # ✅ Add upload/output folder configs with absolute paths
    # app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "..", "uploads")
    # app.config["OUTPUT_FOLDER"] = os.path.join(BASE_DIR, "..", "outputs")

    # Upload/output folder setup via .env
    app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, os.getenv("UPLOAD_FOLDER", "uploads"))
    app.config["OUTPUT_FOLDER"] = os.path.join(BASE_DIR, os.getenv("OUTPUT_FOLDER", "outputs"))

    # ✅ Secret & Session setup
    app.config["SECRET_KEY"] = app.config["SECRET_KEY"] or "fallback"
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_PERMANENT"] = False
    app.config["COMPRESS_ALGORITHM"] = ["br", "gzip"]
    app.config["COMPRESS_MIN_SIZE"] = 500
    Session(app)
    Compress(app)

    # ✅ Ensure folders exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

    # ✅ Mail setup
    from .mail import configure_mail, mail
    configure_mail(app)
    mail.init_app(app)

     # ✅ Database setup
    db.init_app(app)
    from app.models import IngredientPrice, LocationModelApproval
    from app.menu_costing.models import MenuItemPrice, MenuVersion
    with app.app_context():
        db.create_all()

    # ✅ Register blueprints last
    from .routes import register_routes
    register_routes(app)

    @app.context_processor
    def inject_access():
        from app.access import is_owner
        from app.fragments import with_qs

        return {"is_owner": is_owner, "with_qs": with_qs}

    @app.after_request
    def cache_static(response):
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    configure_logging(app)
    return app
