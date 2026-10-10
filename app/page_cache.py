"""Remember a computed page aggregate until the data files change.

The signature is the mtime and size of data files, including directories
named in the environment (tests point those at a temp folder). Callers
must not mutate the returned object.
"""

import os
from pathlib import Path
from threading import Lock

_LOCK = Lock()
_STORE = {}
_MAX = 64
_EXTS = {".csv", ".xlsx", ".xls", ".json", ".md"}
_ENV_DIRS = (
    "FLAGS_DATA_DIR",
    "STORE_HEALTH_DATA_DIR",
    "PROCUREMENT_DATA_DIR",
    "OWNER_PROCUREMENT_DIR",
    "OWNER_GOALS_FILE",
)


def _stamp(path):
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _walk(root, parts):
    if not root.exists():
        return
    if root.is_file():
        stamp = _stamp(root)
        if stamp:
            parts.append(stamp)
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in _EXTS:
            stamp = _stamp(path)
            if stamp:
                parts.append(stamp)


def data_signature():
    """Tuple that changes when a source file changes."""
    try:
        from flask import g, has_request_context
    except ImportError:
        g = None
        has_request_context = lambda: False
    if has_request_context() and getattr(g, "_data_signature", None) is not None:
        return g._data_signature
    parts = []
    root = Path(__file__).resolve().parent.parent / "data"
    _walk(root, parts)
    for name in _ENV_DIRS:
        value = os.environ.get(name) or ""
        parts.append(("env", name, value))
        if value:
            _walk(Path(value), parts)
    signature = tuple(parts)
    if has_request_context():
        g._data_signature = signature
    return signature


def remember(key, builder):
    """Return the cached builder result for this data signature."""
    signature = data_signature()
    cache_key = key if isinstance(key, tuple) else (key,)
    with _LOCK:
        hit = _STORE.get(cache_key)
        if hit and hit[0] == signature:
            return hit[1]
    value = builder()
    with _LOCK:
        hit = _STORE.get(cache_key)
        if hit and hit[0] == signature:
            return hit[1]
        if len(_STORE) >= _MAX:
            _STORE.pop(next(iter(_STORE)))
        _STORE[cache_key] = (signature, value)
    return value


def clear():
    with _LOCK:
        _STORE.clear()


def freeze(value):
    """Make dicts and lists usable inside a cache key."""
    if isinstance(value, dict):
        return tuple(sorted((str(key), freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
