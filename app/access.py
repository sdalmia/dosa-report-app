"""Who can see accounts and people.

OWNER_EMAILS is a comma-separated list of Google sign-in emails. When the
variable is missing or blank, the default owner addresses are used. Set it in
Render to replace that default. The check is the signed-in email, compared
without regard to case.

Accounts flags, people flags, and any future accounts or HR page must use
this module on the server. Hiding a block with CSS is not enough.
"""

import os
from functools import wraps

from flask import redirect, session, url_for

DEFAULT_OWNER_EMAILS = (
    "siddhant@dalgreenfoods.com",
    "dalmia.siddhant@gmail.com",
)

# These areas stay off every response for anyone who is not an owner.
RESTRICTED_AREAS = frozenset({"accounts", "people"})


def owner_emails():
    raw = os.environ.get("OWNER_EMAILS", "")
    if not str(raw).strip():
        raw = ",".join(DEFAULT_OWNER_EMAILS)
    return frozenset(
        part.strip().casefold() for part in str(raw).split(",") if part.strip()
    )


def signed_in_email():
    user = session.get("user")
    email = ""
    if isinstance(user, dict):
        email = user.get("email") or ""
    if not email:
        email = session.get("user_email") or ""
    return str(email).strip()


def is_owner(email=None):
    if email is None:
        email = signed_in_email()
    text = str(email or "").strip().casefold()
    if not text:
        return False
    return text in owner_emails()


def can_see_area(area, email=None):
    token = str(area or "").strip().casefold()
    if token in RESTRICTED_AREAS:
        return is_owner(email)
    return True


def owner_required(view):
    """Block a future accounts or HR page for every other signed-in user."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session and not session.get("user_email"):
            return redirect(url_for("google.login"))
        if not is_owner():
            return redirect(url_for("main.dashboard"))
        return view(*args, **kwargs)

    return wrapped
