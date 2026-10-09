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
    pending = []
    for match in re.finditer(r"(\d{1,2})[-_. ]*([A-Za-z]{3,9})[-_. ]*(20\d{2})?", name):
        month = MONTHS.get(match.group(2).lower())
        if not month:
            continue
        day = int(match.group(1))
        if match.group(3):
            try:
                found.append(date(int(match.group(3)), month, day))
            except ValueError:
                continue
        else:
            pending.append((day, month))
    if pending and found:
        year = found[-1].year
        for day, month in pending:
            try:
                found.append(date(year, month, day))
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
        return f"{start.day} {start.strftime('%b')} to {end.day} {end.strftime('%b %Y')}"
    return f"{start.day} {start.strftime('%b %Y')} to {end.day} {end.strftime('%b %Y')}"


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
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    threats = []
    fallback = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        numbered = re.match(r"\d+\.\s+\*\*(.+?)\*\*", line)
        if numbered:
            threats.append(numbered.group(1).strip())
            continue
        if line.startswith("#"):
            fallback.append(line.lstrip("#").strip())
        elif line[:2] in {"- ", "* "}:
            fallback.append(line[2:].strip())
    lines = [line for line in (threats or fallback) if line][:5]
    if not lines:
        return None
    period = _period_label(dates_in_name(path.name))
    if re.search(r"1\s*[–-]\s*8\s+Oct\s+2026", text):
        period = "1 Oct 2026 to 8 Oct 2026"
    return {
        "id": "headlines",
        "title": "Threat headlines",
        "blurb": "From the human summary. Not a calculated figure.",
        "source": path.name,
        "period": period,
        "status": "ready",
        "note": "",
        "lines": [{"label": line, "value": ""} for line in lines],
    }


def _finite(value):
    number = parse_number(value)
    if number is None or number != number:
        return None
    return number


def _money(value):
    number = _finite(value)
    if number is None:
        return ""
    return format_inr(number)


def _topic_by_id(topic_id):
    for topic in TOPICS:
        if topic["id"] == topic_id:
            return topic
    return None


def _ready_tile(topic_id, source, period, lines):
    topic = _topic_by_id(topic_id)
    ready = bool(lines)
    return {
        "id": topic_id,
        "title": topic["title"],
        "blurb": topic["blurb"],
        "source": source,
        "period": period,
        "status": "ready" if ready else "no-data",
        "note": "" if ready else "No data",
        "lines": lines,
    }


def _is_consumption_book(path):
    if path.suffix.lower() != ".xlsx":
        return False
    try:
        import pandas as pd
        book = pd.ExcelFile(path)
    except Exception:
        return False
    names = {name.lower() for name in book.sheet_names}
    return "summary" in names and "flags" in names


def _city_pair(frame):
    metrics = {}
    for index in range(len(frame)):
        key = frame.iloc[index, 0]
        if not isinstance(key, str) or not key.strip():
            continue
        if key.startswith("By city"):
            break
        left = _finite(frame.iloc[index, 1])
        right = _finite(frame.iloc[index, 2])
        if left is None and right is None:
            continue
        metrics[key.strip()] = (left, right)
    return metrics


def _warehouse_rows(frame):
    rows = []
    for index in range(len(frame)):
        scope = frame.iloc[index, 0]
        level = frame.iloc[index, 2]
        if scope != "All categories" or level != "Warehouse":
            continue
        rows.append({
            "city": str(frame.iloc[index, 1] or "").strip(),
            "opening": _finite(frame.iloc[index, 3]),
            "closing": _finite(frame.iloc[index, 10]),
            "change": _finite(frame.iloc[index, 11]),
        })
    return rows


def _cover_days(detail):
    match = re.search(r"=\s*([\d,]+)\s*days", str(detail or ""))
    if not match:
        return ""
    return match.group(1).replace(",", "")


def _flag_frame(flags, prefix):
    text = flags["flag"].astype(str)
    subset = flags[text.str.startswith(prefix)].copy()
    subset["_amount"] = subset["amount_rs"].map(_finite)
    return subset


def _tiles_from_consumption(path):
    import pandas as pd
    summary = pd.read_excel(path, sheet_name="summary", header=None)
    flags = pd.read_excel(path, sheet_name="flags")
    metrics = _city_pair(summary)
    period = "1 Oct 2026 to 8 Oct 2026"
    source = path.name
    tiles = {}

    bought_lines = []
    for city, column in (("Kolkata", 0), ("Delhi", 1)):
        raw = metrics.get("grn_value_raw")
        used = metrics.get("consumption_raw_total")
        gap = metrics.get("purchase_minus_consumption_raw")
        if not raw or raw[column] is None:
            continue
        bought = _money(raw[column])
        consumed = _money(used[column]) if used and used[column] is not None else ""
        difference = _money(gap[column]) if gap and gap[column] is not None else ""
        bought_lines.append({
            "label": f"{city} raw bought {bought}",
            "value": f"consumed {consumed}" + (f" · difference {difference}" if difference else ""),
        })
    if bought_lines:
        tiles["bought_consumed"] = _ready_tile("bought_consumed", source, period, bought_lines)

    stock_lines = []
    for row in _warehouse_rows(summary):
        if row["closing"] is None:
            continue
        change = _money(row["change"]) if row["change"] is not None else ""
        opening = _money(row["opening"]) if row["opening"] is not None else ""
        stock_lines.append({
            "label": f"{row['city']} all categories",
            "value": f"{opening} to {_money(row['closing'])}" + (f" · change {change}" if change else ""),
        })
    if stock_lines:
        tiles["warehouse"] = _ready_tile("warehouse", source, period, stock_lines)

    over = _flag_frame(flags, "1 Bought far above")
    over = over.sort_values("_amount", ascending=False)
    over_lines = []
    for _, row in over.head(6).iterrows():
        days = _cover_days(row.get("detail"))
        amount = _money(row.get("amount_rs"))
        if not amount:
            continue
        value = f"{days} days · {amount} beyond 10 days" if days else f"{amount} beyond 10 days"
        over_lines.append({
            "label": f"{row.get('city')} · {row.get('item_or_store')}",
            "value": value,
        })
    if over_lines:
        tiles["overstock"] = _ready_tile("overstock", source, period, over_lines)

    unused = _flag_frame(flags, "2 Used with")
    unused = unused.sort_values("_amount", ascending=False)
    unused_lines = []
    for _, row in unused.head(6).iterrows():
        amount = _money(row.get("amount_rs"))
        if not amount:
            continue
        unused_lines.append({
            "label": f"{row.get('city')} · {row.get('item_or_store')}",
            "value": amount,
        })
    if unused_lines:
        tiles["no_purchase"] = _ready_tile("no_purchase", source, period, unused_lines)

    packaging = _flag_frame(flags, "1b ")
    packaging = packaging.sort_values("_amount", ascending=False)
    pack_lines = []
    for _, row in packaging.head(6).iterrows():
        days = _cover_days(row.get("detail"))
        amount = _money(row.get("amount_rs"))
        if not amount:
            continue
        value = f"{days} days · {amount} beyond 30 days" if days else f"{amount} beyond 30 days"
        pack_lines.append({
            "label": f"{row.get('city')} · {row.get('item_or_store')}",
            "value": value,
        })
    if pack_lines:
        tiles["packaging"] = _ready_tile("packaging", source, period, pack_lines)

    waste_lines = []
    wastage = metrics.get("wastage_raw")
    if wastage:
        if wastage[0] is not None:
            waste_lines.append({"label": "Kolkata raw", "value": _money(wastage[0])})
        if wastage[1] is not None:
            waste_lines.append({"label": "Delhi raw", "value": _money(wastage[1])})
    biggest = _flag_frame(flags, "4 Biggest")
    biggest = biggest.sort_values("_amount", ascending=False)
    for _, row in biggest.head(4).iterrows():
        amount = _money(row.get("amount_rs"))
        if not amount:
            continue
        waste_lines.append({
            "label": f"{row.get('city')} · {row.get('item_or_store')}",
            "value": amount,
        })
    if waste_lines:
        tiles["wastage"] = _ready_tile("wastage", source, period, waste_lines)

    hershey = _flag_frame(flags, "5 ")
    hershey_lines = []
    for _, row in hershey.iterrows():
        amount = _money(row.get("amount_rs"))
        detail = str(row.get("detail") or "").strip()
        sentence = detail.split(". ")[0].strip()
        hershey_lines.append({
            "label": sentence or f"{row.get('city')} · {row.get('item_or_store')}",
            "value": amount,
        })
    if hershey_lines:
        tiles["hershey"] = _ready_tile("hershey", source, period, hershey_lines[:3])
    return tiles


class _HtmlRows:
    def __init__(self):
        from html.parser import HTMLParser

        parser = self

        class Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows = []
                self.row = None
                self.cell = None
                self.capture = False

            def handle_starttag(self, tag, attrs):
                if tag == "tr":
                    self.row = []
                elif tag in {"td", "th"} and self.row is not None:
                    self.cell = ""
                    self.capture = True

            def handle_endtag(self, tag):
                if tag in {"td", "th"} and self.capture:
                    self.row.append((self.cell or "").strip())
                    self.cell = None
                    self.capture = False
                elif tag == "tr" and self.row is not None:
                    if any(self.row):
                        self.rows.append(self.row)
                    self.row = None

            def handle_data(self, data):
                if self.capture:
                    self.cell = (self.cell or "") + data

        self.parser = Parser()

    def feed(self, text):
        self.parser.feed(text)
        return self.parser.rows


def _looks_like_html(path):
    try:
        with path.open("rb") as handle:
            sample = handle.read(200).lstrip().lower()
    except OSError:
        return False
    return sample.startswith(b"<") or sample.startswith(b"<b") or b"<table" in sample or b"<html" in sample


def _present_purchase_html(topic, path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        rows = _HtmlRows().feed(text)
    except OSError:
        return _empty_tile(topic)
    data = []
    total = ""
    for row in rows:
        if not row:
            continue
        head = row[0]
        if head.startswith("Total"):
            amount = _money(row[-1])
            if amount:
                total = amount
            continue
        if len(row) < 11 or head in {"Item Code", "CGST"}:
            continue
        name = row[1].strip()
        subtotal = _finite(row[10])
        if not name or subtotal is None:
            continue
        qty = row[7].strip() if len(row) > 8 else ""
        unit = row[8].strip() if len(row) > 8 else ""
        label = name
        if qty and unit:
            label = f"{name}, {qty} {unit}"
        data.append((subtotal, label))
    data.sort(key=lambda item: item[0], reverse=True)
    lines = []
    if total:
        lines.append({"label": "Grand total", "value": total})
    for _amount, label in data[:6]:
        lines.append({"label": label, "value": _money(_amount)})
    tile = _empty_tile(topic)
    if not lines:
        return tile
    tile["status"] = "ready"
    tile["note"] = ""
    tile["source"] = path.name
    tile["period"] = _period_label(dates_in_name(path.name)) or "8 Sep 2026 to 8 Oct 2026"
    tile["lines"] = lines
    return tile


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
    filled = {}
    books = [path for path in files if _is_consumption_book(path)]
    if books:
        pack = _newest(books)
        try:
            filled = _tiles_from_consumption(pack)
        except Exception:
            filled = {}
        if filled:
            used.add(pack)
    for topic in TOPICS:
        if topic["id"] in filled:
            tiles.append(filled[topic["id"]])
            continue
        matched = [path for path in files if _score_topic(path.name, topic) > 0 and path not in used]
        if not matched:
            tiles.append(_empty_tile(topic))
            continue
        chosen = _newest(matched)
        used.add(chosen)
        if topic["id"] == "purchase_summary" and _looks_like_html(chosen):
            tiles.append(_present_purchase_html(topic, chosen))
            continue
        tiles.append(_present_topic(topic, chosen))
    headlines = _headlines(directory)
    if headlines:
        tiles.insert(0, headlines)
    return tiles
