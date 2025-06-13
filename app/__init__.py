import os
from flask import Flask
from flask_mail import Mail
from flask_session import Session
from dotenv import load_dotenv
from .config import Config
from .extensions import db

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
    Session(app)

    # ✅ Ensure folders exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

    # ✅ Mail setup
    from .mail import configure_mail, mail
    configure_mail(app)
    mail.init_app(app)

     # ✅ Database setup
    db.init_app(app)
    from app.models import IngredientPrice
    with app.app_context():
        db.create_all()

    # ✅ Register blueprints last
    from .routes import register_routes
    register_routes(app)

    return app
