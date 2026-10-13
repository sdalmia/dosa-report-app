"""Owner training figures, read from the precomputed summary."""

import json
import os
from pathlib import Path

_CACHE = None


def _path():
    override = os.environ.get("FRONTLYNE_DATA_DIR")
    root = Path(override) if override else Path(__file__).resolve().parents[1] / "data" / "frontlyne"
    return root / "summary.json"


def load_summary():
    global _CACHE
    path = _path()
    try:
        stat = path.stat()
        stamp = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    if _CACHE and _CACHE[0] == stamp:
        return _CACHE[1]
    payload = None
    if stamp is not None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
    if not isinstance(payload, dict) or not payload.get("headline"):
        payload = None
    _CACHE = (stamp, payload)
    return payload


def headline():
    """The threat and the totals. Store lists stay off the first paint."""
    payload = load_summary()
    if not payload:
        return None
    return {
        "headline": payload.get("headline") or "",
        "totals": payload.get("totals") or "",
        "outside": payload.get("outside") or "",
    }
