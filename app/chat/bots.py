"""Server-to-server keys for the other assistants.

CHAT_BOT_KEYS is JSON. Each bot has a sha256 hash of its key and a role.
Roles: owner (accounts and HR), finance (accounts only), hr (HR only), ops.
"""

import hashlib
import json
import os

_ROLES = {"owner", "finance", "hr", "ops"}


def bot_directory():
    raw = os.environ.get("CHAT_BOT_KEYS", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    found = {}
    for name, row in payload.items():
        if not isinstance(row, dict):
            continue
        digest = str(row.get("hash") or "").strip().lower()
        role = str(row.get("role") or "ops").strip().lower()
        if not digest or role not in _ROLES:
            continue
        found[str(name)] = {"hash": digest, "role": role}
    return found


def authenticate(header):
    """Return {name, role} or None. The presented key is hashed before compare."""
    text = str(header or "").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    if not text:
        return None
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    for name, row in bot_directory().items():
        if digest == row["hash"]:
            return {"name": name, "role": row["role"]}
    return None
