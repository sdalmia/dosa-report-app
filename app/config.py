import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def resolve_database_uri(url=None):
    """Read the database URL when the app is created, not only at import."""
    raw = url if url is not None else os.getenv("DATABASE_URL", "sqlite:///app.db")
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg://"):
        if raw.startswith(prefix):
            raw = "postgresql+psycopg2://" + raw[len(prefix):]
            break
    return raw


class Config:
    # Production stays off Flask debug. OAuth libraries log tokens at DEBUG.
    DEBUG = False
    SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret")
    
    # File folders
    UPLOAD_FOLDER = 'uploads'
    OUTPUT_FOLDER = 'outputs'

    # Database. create_app reads this again so a test database set later is the one used.
    SQLALCHEMY_DATABASE_URI = resolve_database_uri()
    SQLALCHEMY_ENGINE_OPTIONS = (
        {"pool_pre_ping": True} if str(SQLALCHEMY_DATABASE_URI).startswith("postgresql") else {}
    )
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
