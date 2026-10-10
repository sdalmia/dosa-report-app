import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret")
    
    # File folders
    UPLOAD_FOLDER = 'uploads'
    OUTPUT_FOLDER = 'outputs'

    # Database
    _db_url = os.getenv("DATABASE_URL", "sqlite:///app.db")
    # Pin the psycopg2 driver explicitly (newer SQLAlchemy defaults to psycopg 3).
    for _prefix in ("postgres://", "postgresql://", "postgresql+psycopg://"):
        if _db_url.startswith(_prefix):
            _db_url = "postgresql+psycopg2://" + _db_url[len(_prefix):]
            break
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True} if _db_url.startswith("postgresql") else {}
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Mail Settings
    # MAIL_SERVER = os.getenv('MAIL_SERVER')
    # MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    # MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    # MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    # MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    # MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')

    # Google OAuth (if you want to reference here too)
    GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
