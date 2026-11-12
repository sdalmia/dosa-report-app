"""A small in-memory cap so one person cannot hammer the model."""

import os
import time
from collections import defaultdict

_HITS = defaultdict(list)


def _settings():
    try:
        count = int(os.environ.get("CHAT_RATE_LIMIT", "20"))
    except ValueError:
        count = 20
    try:
        window = int(os.environ.get("CHAT_RATE_WINDOW", "600"))
    except ValueError:
        window = 600
    return max(count, 1), max(window, 1)


def allow(key, now=None):
    """True when this key is still inside the window. Records the attempt."""
    count, window = _settings()
    moment = time.time() if now is None else now
    bucket = [stamp for stamp in _HITS[key] if moment - stamp < window]
    if len(bucket) >= count:
        _HITS[key] = bucket
        return False
    bucket.append(moment)
    _HITS[key] = bucket
    return True


def reset():
    _HITS.clear()
