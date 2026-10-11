"""HTML fragments for below-the-fold sections.

A fragment uses the same login or owner check as the page that embeds it.
Responses carry a private cache header and an ETag.
"""

import hashlib

from flask import make_response, request

PAGE = 20


def slice_rows(rows, offset, limit=PAGE):
    """Return a page of rows, the next offset, and the full length."""
    rows = list(rows or [])
    try:
        start = max(0, int(offset or 0))
    except (TypeError, ValueError):
        start = 0
    chunk = rows[start : start + limit]
    next_offset = start + limit if start + limit < len(rows) else None
    return chunk, next_offset, len(rows)


def query_offset():
    try:
        return max(0, int(request.args.get("offset") or 0))
    except (TypeError, ValueError):
        return 0


def query_text():
    return (request.args.get("q") or "").strip()


def matches(row, query, fields):
    if not query:
        return True
    needle = query.casefold()
    blob = " ".join(str((row or {}).get(name) or "") for name in fields)
    return needle in blob.casefold()


def with_qs(url):
    """Keep the page's query string on a fragment URL."""
    raw = request.query_string.decode()
    if not raw:
        return url
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}{raw}"


def html_fragment(body):
    """Private, ETag-validated HTML. A matching If-None-Match returns 304."""
    raw = body if isinstance(body, str) else str(body)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    etag = f'W/"{digest}"'
    if request.headers.get("If-None-Match") == etag:
        response = make_response("", 304)
    else:
        response = make_response(raw)
        response.mimetype = "text/html"
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=60"
    vary = response.headers.get("Vary", "")
    parts = [part.strip() for part in vary.split(",") if part.strip()]
    if "Cookie" not in parts:
        parts.append("Cookie")
    response.headers["Vary"] = ", ".join(parts)
    return response
