from .main import main_bp
from .uploader import uploader_bp
from .ingredient_tracker import ingredient_bp
from auth import auth_bp, google_bp

def register_routes(app):
    app.register_blueprint(google_bp, url_prefix="/login")  # ✅ Register this first
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(uploader_bp)
    app.register_blueprint(ingredient_bp)