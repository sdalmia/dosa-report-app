"""Procurement tiles from data/procurement/.

The loader groups files by words in the filename and keeps the newest dated
drop. A later file with a later date in the name replaces the older one.
Numbers come only from a recognised column. A blank cell is not zero.
"""

import csv
import io
import os
import re
from datetime import date, datetime
from pathlib import Path

from app.store_health.contract import parse_number
from app.store_health.present import format_inr, format_count

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

TOPICS = (
    {
        "id": "bought_consumed",
        "title": "Bought vs consumed",
        "keywords": ("bought", "consumed"),
        "blurb": "By city, from the newest bought-versus-consumed drop.",
    },
    {
        "id": "warehouse",
        "title": "Warehouse stock",
        "keywords": ("warehouse", "stock_build", "stock-build"),
        "blurb": "Closing stock and the closing change.",
    },
    {
        "id": "overstock",
        "title": "Overstock",
        "keywords": ("overstock", "days_of_cover", "days-of-cover"),
        "blurb": "Days of cover, and the rupee value beyond 10 days.",
    },
    {
        "id": "no_purchase",
        "title": "Used with no purchase",
        "keywords": ("no_purchase", "no-purchase", "negative"),
        "blurb": "Items used with no purchase, or with negative stock.",
    },
    {
        "id": "packaging",
        "title": "Packaging cover",
        "keywords": ("packaging",),
        "blurb": "Cover days for packaging.",
    },
    {
        "id": "wastage",
        "title": "Wastage",
        "keywords": ("wastage", "waste"),
        "blurb": "Wastage from the newest waste drop.",
    },
    {
        "id": "hershey",
        "title": "Hershey's IN-1854",
        "keywords": ("hershey", "in-1854", "in_1854", "in1854"),
        "blurb": "Data-entry error flag for indent IN-1854.",
    },
    {
        "id": "purchase_summary",
        "title": "Base kitchen purchases",
        "keywords": ("purchase_summary", "purchase-summary", "itemwise", "item-wise", "base_kitchen", "base-kitchen"),
        "blurb": "Item-wise purchase summary for the base kitchen.",
    },
)


def procurement_directory():
    override = os.getenv("PROCUREMENT_DATA_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "data" / "procurement"


def _norm(name):
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def dates_in_name(name):
    found = []
    for match in re.finditer(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})", name):
        try:
            found.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    for match in re.finditer(r"(\d{1,2})[-_. ]*([A-Za-z]{3,9})[-_. ]*(20\d{2})?", name):
        month = MONTHS.get(match.group(2).lower())
        if not month:
            continue
        year = int(match.group(3)) if match.group(3) else None
        if year is None:
            continue
        try:
            found.append(date(year, month, int(match.group(1))))
        except ValueError:
            continue
    return found


def _period_label(days):
    if not days:
        return ""
    start, end = min(days), max(days)
    if start == end:
        return f"{start.day} {start.strftime('%b %Y')}"
    if start.year == end.year:
        return f"{start.day} {start.strftime('%b')}–{end.day} {end.strftime('%b %Y')}"
    return f"{start.day} {start.strftime('%b %Y')}–{end.day} {end.strftime('%b %Y')}"


def _score_topic(filename, topic):
    stem = _norm(filename)
    score = 0
    for word in topic["keywords"]:
        if _norm(word) and _norm(word) in stem:
            score += len(_norm(word))
    return score


def _newest(paths):
    """Prefer a date in the filename. An undated file loses to a dated one."""

    def key(path):
        days = dates_in_name(path.name)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        if days:
            return (1, max(days).toordinal(), mtime)
        return (0, 0, mtime)

    return max(paths, key=key)


def _read_table(path):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            return []
        try:
            reader = csv.DictReader(io.StringIO(text))
        except csv.Error:
            return []
        return [dict(row) for row in reader if row]
    if suffix not in {".xlsx", ".xls"}:
        return []
    try:
        import pandas as pd
    except ImportError:
        return []
    try:
        frame = pd.read_excel(path)
    except Exception:
        return []
    frame = frame.where(frame.notna(), "")
    return frame.to_dict(orient="records")


def _columns(rows):
    if not rows:
        return {}
    mapping = {}
    for name in rows[0].keys():
        mapping[_norm(name)] = name
    return mapping


def _pick(mapping, *candidates):
    for candidate in candidates:
        token = _norm(candidate)
        if token in mapping:
            return mapping[token]
    for candidate in candidates:
        token = _norm(candidate)
        for key, original in mapping.items():
            if token and token in key:
                return original
    return None


def _num(row, column):
    if not column:
        return None
    return parse_number(row.get(column))


def _text(row, column):
    if not column:
        return ""
    value = row.get(column)
    if value is None:
        return ""
    return str(value).strip()


def _money(value):
    if value is None:
        return ""
    return format_inr(value)


def _hershey_hits(rows):
    hits = []
    for row in rows:
        blob = " ".join(str(value) for value in row.values() if value is not None)
        if re.search(r"IN[-\s]?1854", blob, re.IGNORECASE) or re.search(r"hershey", blob, re.IGNORECASE):
            item = ""
            for key, value in row.items():
                if value and _norm(key) in {"item", "item_name", "sku", "name", "description"}:
                    item = str(value).strip()
                    break
            hits.append(item or blob[:180])
    return hits


def _present_topic(topic, path):
    tile = {
        "id": topic["id"],
        "title": topic["title"],
        "blurb": topic["blurb"],
        "source": path.name,
        "period": _period_label(dates_in_name(path.name)),
        "status": "no-data",
        "note": "No data",
        "lines": [],
    }
    rows = _read_table(path)
    if not rows:
        tile["note"] = "No data. The file has no rows."
        return tile
    mapping = _columns(rows)
    topic_id = topic["id"]
    if topic_id == "hershey":
        hits = _hershey_hits(rows)
        if not hits:
            tile["note"] = "No data. IN-1854 is not in this file."
            return tile
        tile["status"] = "ready"
        tile["note"] = "Flagged because the file names IN-1854 or Hershey's."
        tile["lines"] = [{"label": hit, "value": ""} for hit in hits[:8]]
        return tile

    if topic_id == "bought_consumed":
        city = _pick(mapping, "city")
        bought = _pick(mapping, "bought", "purchased")
        consumed = _pick(mapping, "consumed", "consumption")
        if not city or not bought or not consumed:
            tile["note"] = f"No data. Columns in {path.name} were not recognised."
            return tile
        lines = []
        for row in rows:
            label = _text(row, city)
            bought_value = _num(row, bought)
            consumed_value = _num(row, consumed)
            if not label or (bought_value is None and consumed_value is None):
                continue
            lines.append({
                "label": label,
                "value": f"Bought {_money(bought_value) or 'no data'} · Consumed {_money(consumed_value) or 'no data'}",
            })
        if not lines:
            tile["note"] = "No data"
            return tile
        tile["status"] = "ready"
        tile["note"] = ""
        tile["lines"] = lines[:12]
        return tile

    specs = {
        "warehouse": (("item", "sku", "name"), ("closing", "closing_stock"), ("change", "closing_change", "delta")),
        "overstock": (("item", "sku", "name"), ("days_of_cover", "cover_days", "doc"), ("value_beyond_10", "beyond_10", "excess_value")),
        "no_purchase": (("item", "sku", "name"), ("stock", "closing", "qty"), ()),
        "packaging": (("item", "sku", "name"), ("cover_days", "days_of_cover", "doc"), ()),
        "wastage": (("item", "sku", "name"), ("wastage", "waste", "waste_value"), ()),
        "purchase_summary": (("item", "sku", "name"), ("amount", "value", "purchase", "qty"), ()),
    }
    label_keys, primary_keys, extra_keys = specs.get(topic_id, ((), (), ()))
    label_col = _pick(mapping, *label_keys) if label_keys else None
    primary_col = _pick(mapping, *primary_keys) if primary_keys else None
    extra_col = _pick(mapping, *extra_keys) if extra_keys else None
    if not label_col or not primary_col:
        tile["note"] = f"No data. Columns in {path.name} were not recognised."
        return tile
    lines = []
    for row in rows:
        label = _text(row, label_col)
        primary = _num(row, primary_col)
        extra = _num(row, extra_col) if extra_col else None
        if not label or primary is None:
            continue
        if topic_id in {"overstock", "packaging"}:
            value = f"{format_count(primary)} days"
            if extra is not None:
                value = f"{value} · {_money(extra)} beyond 10 days"
        elif topic_id == "warehouse":
            value = _money(primary) or format_count(primary)
            if extra is not None:
                value = f"Closing {value} · change {_money(extra)}"
            else:
                value = f"Closing {value}"
        elif topic_id == "no_purchase" and primary < 0:
            value = _money(primary) if abs(primary) >= 1 else format_count(primary)
        elif topic_id == "no_purchase":
            continue
        else:
            value = _money(primary) or format_count(primary)
        lines.append({"label": label, "value": value})
    if not lines:
        tile["note"] = "No data"
        return tile
    tile["status"] = "ready"
    tile["note"] = ""
    tile["lines"] = lines[:8]
    return tile


def _empty_tile(topic):
    return {
        "id": topic["id"],
        "title": topic["title"],
        "blurb": topic["blurb"],
        "source": "data/procurement/",
        "period": "",
        "status": "no-data",
        "note": "No data",
        "lines": [],
    }


def _headlines(directory):
    notes = [path for path in directory.glob("*.md") if path.name.lower() != "readme.md"]
    if not notes:
        return None
    path = _newest(notes)
    lines = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        elif line[:2] in {"- ", "* "}:
            line = line[2:].strip()
        else:
            continue
        if line:
            lines.append(line)
        if len(lines) == 5:
            break
    if not lines:
        return None
    return {
        "id": "headlines",
        "title": "Threat headlines",
        "blurb": "From the human summary. Not a calculated figure.",
        "source": path.name,
        "period": _period_label(dates_in_name(path.name)),
        "status": "ready",
        "note": "",
        "lines": [{"label": line, "value": ""} for line in lines],
    }


def procurement_tiles(directory=None):
    directory = Path(directory) if directory else procurement_directory()
    tiles = []
    if not directory.is_dir():
        return [_empty_tile(topic) for topic in TOPICS]
    files = [
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".csv", ".xlsx", ".xls"} and path.name.lower() != "readme.md"
    ]
    used = set()
    for topic in TOPICS:
        matched = [path for path in files if _score_topic(path.name, topic) > 0 and path not in used]
        if not matched:
            tiles.append(_empty_tile(topic))
            continue
        chosen = _newest(matched)
        used.add(chosen)
        tiles.append(_present_topic(topic, chosen))
    headlines = _headlines(directory)
    if headlines:
        tiles.insert(0, headlines)
    return tiles
