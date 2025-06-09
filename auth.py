import os
from flask import Blueprint, redirect, url_for, session
from flask_dance.contrib.google import make_google_blueprint, google
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

# Create Google OAuth blueprint
google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
    scope=[
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile"
    ],
    redirect_to="auth.google_login"  # Route name defined below
)

# Create separate blueprint for auth-related routes
auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/google-login")
def google_login():
    if not google.authorized:
        return redirect(url_for("google.login"))

    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        return f"❌ Error fetching user info: {resp.text}"

    user_info = resp.json()
    session['user_email'] = user_info.get("email")
    session['user_name'] = user_info.get("name")

    # ✅ Redirect straight to upload page after login
    return redirect(url_for("upload_index"))
    

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))
