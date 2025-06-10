import os
from flask import Blueprint, redirect, url_for, session
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer.storage.session import SessionStorage
from dotenv import load_dotenv
import logging

# Logging and .env setup
logging.basicConfig(level=logging.DEBUG)
load_dotenv()

# ✅ Flask-Dance Google Blueprint
google_bp = make_google_blueprint(
    client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile"
    ],
    redirect_to="auth.google_callback",
    storage=SessionStorage(key="google_oauth_token")
)

# ✅ Custom Auth Blueprint
auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/google/callback")
def google_callback():
    print("✅ Entered google_callback")

    if not google.authorized:
        print("❌ Google not authorized")
        return redirect(url_for("google.login"))

    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        print("❌ Failed to fetch user info from Google")
        return "Failed to fetch user info", 500

    user_info = resp.json()
    print("✅ User Info:", user_info)

    # ✅ Store user data in session
    session["user_email"] = user_info["email"]
    session["user_name"] = user_info.get("given_name", "User")

    session["user"] = {
        "email": user_info.get("email"),
        "name": user_info.get("name")
    }

    print("✅ Session user set:", session["user"])
    return redirect(url_for("main.dashboard"))

@auth_bp.route("/logout")
def logout():
    session.clear()
    print("✅ User logged out")
    return redirect(url_for("main.home"))
