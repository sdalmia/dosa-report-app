"""Follow lazy sections and Show more links so a test sees the full page."""

from html import escape, unescape


def _needles(marker, url):
    forms = [url, escape(url, quote=True)]
    return [f'{marker}="{form}"' for form in forms]


def _swap_section(html, url, body):
    index = -1
    for needle in _needles("data-src", url):
        index = html.find(needle)
        if index >= 0:
            break
    if index < 0:
        return html, False
    start = html.rfind("<section", 0, index)
    end = html.find("</section>", index)
    if start < 0 or end < 0:
        return html, False
    return html[:start] + body + html[end + len("</section>") :], True


def _swap_button(html, url, body):
    index = -1
    for needle in _needles("data-more", url):
        index = html.find(needle)
        if index >= 0:
            break
    if index < 0:
        return html, False
    start = html.rfind("<button", 0, index)
    end = html.find("</button>", index)
    if start < 0 or end < 0:
        return html, False
    end += len("</button>")
    # A Show more control inside a table row is the whole row. Replacing the
    # button alone would leave that <tr> behind and inflate row counts.
    row = html.rfind("<tr", 0, start)
    if row >= 0 and "</tr>" not in html[row:start]:
        row_end = html.find("</tr>", end)
        if row_end >= 0 and "<tr" not in html[end:row_end]:
            start = row
            end = row_end + len("</tr>")
    return html[:start] + body + html[end:], True


def _next_url(html, marker):
    token = marker + '="'
    index = html.find(token)
    if index < 0:
        return None
    start = index + len(token)
    end = html.find('"', start)
    if end < 0:
        return None
    return unescape(html[start:end])


def stitch(client, html, limit=80):
    """Replace each lazy section, then each Show more button, with its fragment."""
    seen = set()
    for _ in range(limit):
        url = _next_url(html, "data-src")
        if url and ("src", url) not in seen:
            seen.add(("src", url))
            response = client.get(url)
            if response.status_code != 200:
                break
            html, _changed = _swap_section(html, url, response.get_data(as_text=True))
            continue
        url = _next_url(html, "data-more")
        if not url or ("more", url) in seen:
            break
        seen.add(("more", url))
        response = client.get(url)
        if response.status_code != 200:
            break
        html, _changed = _swap_button(html, url, response.get_data(as_text=True))
    return html


def page(client, path, **kwargs):
    response = client.get(path, **kwargs)
    html = response.get_data(as_text=True)
    if response.status_code == 200 and ("data-src=" in html or "data-more=" in html):
        html = stitch(client, html)
    return html
