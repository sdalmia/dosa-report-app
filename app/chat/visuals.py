"""Tables and charts the page may draw. Every number is checked first."""


def _numbers(value, found):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        found.append(float(value))
        return
    if isinstance(value, str):
        text = value.replace("₹", "").replace("%", "").replace(",", "").replace("−", "-").strip()
        if not text or any(ch.isalpha() for ch in text):
            return
        try:
            found.append(float(text))
        except ValueError:
            return
        return
    if isinstance(value, dict):
        for item in value.values():
            _numbers(item, found)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _numbers(item, found)


def allowed_numbers(source):
    found = []
    _numbers(source, found)
    return found


def _close(candidate, allowed):
    # Display rounding can move a rupee by less than one.
    return any(abs(candidate - item) <= 0.51 for item in allowed)


def verify_block(block, allowed):
    """Reject a table or chart if any number is not in the source figures."""
    if not block:
        return None
    found = []
    _numbers(block, found)
    if not found:
        return None
    if any(not _close(number, allowed) for number in found):
        return None
    return block


def table_block(columns, rows, title):
    """At most 10 data rows. The page shows 5 until Show all."""
    kept = []
    for row in rows[:10]:
        if isinstance(row, dict):
            kept.append([row.get(column, "") for column in columns])
        else:
            kept.append(list(row))
    if not kept:
        return None
    return {"title": title, "columns": list(columns), "rows": kept}


def chart_block(title, series, unit=""):
    cleaned = []
    for item in series[:8]:
        try:
            value = float(item["value"])
        except (KeyError, TypeError, ValueError):
            continue
        cleaned.append({"label": str(item.get("label") or ""), "value": value})
    if not cleaned:
        return None
    return {"type": "bar", "title": title, "unit": unit, "series": cleaned}
