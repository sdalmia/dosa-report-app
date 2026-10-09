from .main import main_bp
from .uploader import uploader_bp
from .ingredient_tracker import ingredient_bp
from .location_finder import location_finder_bp
from .store_health import store_health_bp
from app.owner_tools import owner_bp
from app.procurement.routes import procurement_bp
from app.menu_costing.routes import menu_bp
from auth import auth_bp, google_bp



def register_routes(app):
    from app.menu_ops.routes import menu_ops_bp
    app.register_blueprint(google_bp, url_prefix="/login")  # ✅ Register this first
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(uploader_bp)
    app.register_blueprint(ingredient_bp)
    app.register_blueprint(location_finder_bp)
    app.register_blueprint(store_health_bp)
    app.register_blueprint(owner_bp)
    app.register_blueprint(procurement_bp)
    app.register_blueprint(menu_ops_bp)
    app.register_blueprint(menu_bp)
