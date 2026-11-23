"""Who owns a move. The names live in data/chat/owners.json, not in the sentences."""

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CACHE = {}


def load_owners(path=None):
    file_path = Path(path) if path else _ROOT / "data" / "chat" / "owners.json"
    key = str(file_path)
    if key in _CACHE:
        return _CACHE[key]
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    _CACHE[key] = payload
    return payload


def _city_key(city):
    text = (city or "").casefold()
    if any(token in text for token in ("north", "ncr", "delhi")):
        return "north"
    if any(token in text for token in ("east", "kolkata", "calcutta")):
        return "east"
    return ""


def owner_for(scope, city=None, path=None):
    """One owner for a scope. A complaint uses the store's city lead."""
    cfg = load_owners(path)
    key = (scope or "").casefold().strip()
    if key in {"complaints", "famepilot", "ticket", "tickets", "store"}:
        key = _city_key(city) or "network"
    if key in {"east", "kolkata"}:
        key = "east"
    elif key in {"north", "ncr", "delhi"}:
        key = "north"
    if key in cfg and isinstance(cfg[key], str):
        return cfg[key]
    return cfg.get("network") or "not named in the file"


def owner_for_stores(regions, path=None):
    """One city lead when every store is in that city, otherwise the network owner."""
    keys = {_city_key(region) for region in regions if _city_key(region)}
    if keys == {"east"}:
        return owner_for("east", path=path)
    if keys == {"north"}:
        return owner_for("north", path=path)
    return owner_for("network", path=path)
