"""Load menu, channel, and recipe files.

The sales file is the newest CSV whose name contains a date (YYYY-MM or
YYYY-MM-DD). A file with no date is used only when nothing dated covers
that store. Categorywise Torqus exports are a category list, not the sales
source: Sold Qty is quantity, and the file on disk has no date in its name.

Blank cells stay None. Zero is kept only when the file contains 0.
"""

import csv
import os
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from app.store_health.contract import parse_date, parse_number
from app.store_health.stores import label_words, match_menu_store

MENU_MIX_COLUMNS = (
    "store",
    "item",
    "total_sales",
    "total_orders",
    "contribution_pct",
    "period_start",
    "period_end",
)
MENU_ANALYSIS_COLUMNS = ("item", "total sales", "total orders", "% contribution")
CHANNEL_SALES_COLUMNS = ("date", "period_from", "period_to", "store", "channel", "gross", "orders")
CHANNEL_RATING_COLUMNS = (
    "store",
    "zomato_delivery",
    "zomato_dining",
    "google",
    "swiggy",
    "as_of",
)

_DATE_IN_NAME = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)")
_MENU_ANALYSIS = re.compile(r"^menu_analysis_(?P<body>.+)$", re.IGNORECASE)

# First matching alias wins when several columns could map to one field.
_FIELD_ALIASES = (
    ("store", ("store", "outlet", "site")),
    ("item", ("item", "dish name", "item name", "dish")),
    ("gross", ("total sales", "total sale", "gross sale", "gross", "sales")),
    ("orders", ("total orders", "orders", "order", "qty")),
    ("contribution_pct", ("contribution pct", "pct contribution", "contribution")),
    ("period_start", ("period start", "start date")),
    ("period_end", ("period end", "end date")),
    ("period", ("period",)),
    ("date", ("date",)),
    ("quantity", ("sold qty", "quantity", "qty")),
    ("channel", ("channel", "order type", "source")),
    ("status", ("status",)),
    ("recipe_cost", ("recipe cost", "recipe_cost", "food cost", "unit cost", "cost")),
    ("category", ("category",)),
    ("period_from", ("period from",)),
    ("period_to", ("period to",)),
    ("items_gross", ("items gross",)),
    ("channel_gross", ("channel gross",)),
    ("gap", ("gap",)),
    ("gap_pct", ("gap pct",)),
    ("flag", ("flag",)),
)


def repo_root():
    return Path(__file__).resolve().parents[2]


def menu_directory():
    override = os.getenv("MENU_OPS_MENU_DIR")
    if override:
        return Path(override)
    return repo_root() / "data" / "menu"


def famepilot_directory():
    override = os.getenv("MENU_OPS_FAMEPILOT_DIR")
    if override:
        return Path(override)
    return repo_root() / "data" / "famepilot"


def channels_directory():
    override = os.getenv("MENU_OPS_CHANNELS_DIR")
    if override:
        return Path(override)
    return repo_root() / "data" / "channels"


def procurement_directory():
    override = os.getenv("MENU_OPS_PROCUREMENT_DIR")
    if override:
        return Path(override)
    return repo_root() / "data" / "procurement"


def posist_path():
    override = os.getenv("STORE_HEALTH_DATA_DIR")
    if override:
        return Path(override) / "posist_daily.csv"
    return repo_root() / "data" / "store_health" / "posist_daily.csv"


def _parsed_name_date(match):
    year, month = int(match.group(1)), int(match.group(2))
    day = match.group(3)
    try:
        if day:
            return date(year, month, int(day)), "day"
        return date(year, month, 1), "month"
    except ValueError:
        return None


def filename_dates(name):
    """Every (date, 'day'|'month') in a filename, in order."""
    found = []
    for match in _DATE_IN_NAME.finditer(name or ""):
        parsed = _parsed_name_date(match)
        if parsed:
            found.append(parsed)
    return found


def filename_date(name):
    """Latest (date, 'day'|'month') in a filename, or None.

    A day beats a month when both fall on the same calendar date.
    """
    found = filename_dates(name)
    if not found:
        return None
    return max(found, key=lambda item: (item[0], 1 if item[1] == "day" else 0))


def file_stamp(path):
    """Dated files sort ahead of undated ones. The latest date in the name wins."""
    found = filename_date(path.name)
    if not found:
        return (0, date.min, 0, path.name)
    day, precision = found
    return (1, day, 1 if precision == "day" else 0, path.name)


def _blank(value):
    return value is None or str(value).strip() == ""


def normalise_header(name):
    text = (name or "").replace("\n", " ").replace("%", " pct ")
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return text


def item_key(name):
    return re.sub(r"\s+", " ", str(name or "").strip()).casefold()


def _read_csv(path):
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        return list(csv.reader(handle))


def _header_map(fieldnames):
    """Map a field name to the first alias that is actually present."""
    normalised = {normalise_header(name): name for name in fieldnames if name}
    chosen = {}
    for field, aliases in _FIELD_ALIASES:
        for alias in aliases:
            if alias in normalised:
                chosen[field] = normalised[alias]
                break
    return chosen


def _dict_rows(path):
    rows = _read_csv(path)
    header_index = None
    for index, row in enumerate(rows[:12]):
        headers = [normalise_header(cell) for cell in row]
        if "item" in headers or "dish name" in headers or "store" in headers:
            header_index = index
            break
    if header_index is None:
        return [], []
    fieldnames = rows[header_index]
    mapping = _header_map(fieldnames)
    parsed = []
    for raw in rows[header_index + 1 :]:
        if not raw or all(_blank(cell) for cell in raw):
            continue
        padded = list(raw) + [""] * (len(fieldnames) - len(raw))
        record = {}
        for field, original in mapping.items():
            column = fieldnames.index(original)
            record[field] = padded[column] if column < len(padded) else ""
        record["_columns"] = [normalise_header(name) for name in fieldnames if not _blank(name)]
        parsed.append(record)
    columns = [normalise_header(name) for name in fieldnames if not _blank(name)]
    return parsed, columns


def _month_span(day):
    from datetime import timedelta

    if day.month == 12:
        end = date(day.year + 1, 1, 1)
    else:
        end = date(day.year, day.month + 1, 1)
    return day, end - timedelta(days=1)


def _period_from_name(path):
    found = filename_dates(path.name)
    if not found:
        return None, None
    starts = []
    ends = []
    for day, precision in found:
        if precision == "day":
            starts.append(day)
            ends.append(day)
        else:
            start, end = _month_span(day)
            starts.append(start)
            ends.append(end)
    return min(starts), max(ends)


def _store_from_analysis_name(path):
    match = _MENU_ANALYSIS.match(path.stem)
    if not match:
        return ""
    body = match.group("body")
    body = re.sub(r"(?:[_\-\s]+\d{4}-\d{2}(?:-\d{2})?)+$", "", body)
    return re.sub(r"\s+", " ", body.replace("_", " ")).strip()


def _row_numbers(raw):
    gross = parse_number(raw.get("gross")) if "gross" in raw else None
    orders = parse_number(raw.get("orders")) if "orders" in raw else None
    contribution = parse_number(raw.get("contribution_pct")) if "contribution_pct" in raw else None
    if "gross" in raw and gross is None and not _blank(raw.get("gross")):
        gross = None
    return gross, orders, contribution


def _sales_row(raw, store, path):
    start = parse_date(raw.get("period_start"))
    end = parse_date(raw.get("period_end"))
    if start is None or end is None:
        named_start, named_end = _period_from_name(path)
        start = start or named_start
        end = end or named_end
    gross, orders, contribution = _row_numbers(raw)
    if "category" in raw:
        category_from_sales = str(raw.get("category") or "").strip()
    else:
        category_from_sales = None
    return {
        "store": store,
        "item": str(raw.get("item") or "").strip(),
        "gross": gross,
        "orders": orders,
        "contribution_pct": contribution,
        "period_start": start,
        "period_end": end,
        "source": path.name,
        "quantity": parse_number(raw.get("quantity")) if "quantity" in raw else None,
        "category_from_sales": category_from_sales,
    }


def sniff_menu_kind(path):
    """Return 'network', 'analysis', 'torqus', or ''."""
    try:
        rows = _read_csv(path)
    except OSError:
        return ""
    blob = " ".join(normalise_header(cell) for row in rows[:15] for cell in row)
    if "dish name" in blob and "gross sale" in blob:
        return "torqus"
    parsed, columns = _dict_rows(path)
    if not parsed and not columns:
        return ""
    names = set(columns)
    has_item = "item" in names or "dish name" in names
    has_orders = "total orders" in names or "orders" in names or "qty" in names
    has_sales = "total sales" in names or "gross" in names or "sales" in names
    if path.name.lower().startswith("menu_analysis_") and has_item and has_sales:
        return "analysis"
    # Tony's processed item file. It wins over a menu mix built from raw folders.
    if "store" in names and has_item and "qty" in names and "gross" in names and "total sales" not in names:
        return "items"
    if "store" in names and has_item and has_sales and has_orders:
        return "network"
    if path.name.lower().startswith("menu_mix") and has_item and has_sales:
        return "network"
    return ""


def _load_network(path):
    parsed, columns = _dict_rows(path)
    rows = []
    for raw in parsed:
        store = str(raw.get("store") or "").strip()
        item = str(raw.get("item") or "").strip()
        if not store or not item:
            continue
        rows.append(_sales_row(raw, store, path))
    return rows, columns


def _load_analysis(path):
    parsed, columns = _dict_rows(path)
    filename_store = _store_from_analysis_name(path)
    rows = []
    for raw in parsed:
        store = str(raw.get("store") or "").strip() or filename_store
        item = str(raw.get("item") or "").strip()
        if not store or not item:
            continue
        rows.append(_sales_row(raw, store, path))
    return rows, columns


def _same_store(left, right, labels):
    if item_key(left) == item_key(right):
        return True
    if match_menu_store(left, [right]) == right:
        return True
    if match_menu_store(right, [left]) == left:
        return True
    pool = [label for label in labels if label]
    left_match = match_menu_store(left, pool)
    right_match = match_menu_store(right, pool)
    return bool(left_match and right_match and left_match == right_match)


def _csv_signature(directory):
    """Name, mtime and size. A changed drop-in file misses the cache."""
    parts = []
    if directory.exists():
        for path in sorted(directory.glob("*.csv")):
            stat = path.stat()
            parts.append((path.name, stat.st_mtime_ns, stat.st_size))
    return tuple(parts)


_SALES_CACHE = {}


def load_sales(directory=None, posist_labels=None):
    """Item rows from the newest dated menu file for each store.

    menu_mix files cover every store in the file. menu_analysis_<store>
    files cover one store and replace an older network row for that store.
    Orders stay orders. A quantity column is ignored for popularity.
    """
    directory = Path(directory) if directory else menu_directory()
    labels = tuple(posist_labels or [])
    cache_key = (str(directory), _csv_signature(directory), labels)
    cached = _SALES_CACHE.get(cache_key)
    if cached is not None:
        chosen, warnings, sources = cached
        return [dict(row) for row in chosen], list(warnings), [dict(source) for source in sources]
    warnings = []
    if not directory.exists():
        warnings.append(f"{directory} is not on file, so menu sales are blank.")
        return [], warnings, []
    files = _read_sales_files(directory)
    if not files:
        warnings.append(
            "No menu_mix or menu_analysis CSV is on file in data/menu. "
            "Expected menu_mix_<date>.csv (store, item, total_sales, total_orders, contribution_pct) "
            "or menu_analysis_<store>_<date>.csv (item, total sales, total orders, % contribution)."
        )
        return [], warnings, []

    item_files = [entry for entry in files if entry["kind"] == "items"]
    if item_files:
        newest = max(entry["stamp"] for entry in item_files)
        files = [entry for entry in item_files if entry["stamp"] == newest]
        for entry in files:
            entry["kind"] = "network"
    else:
        files = _period_files(files)
    names = sorted({row["store"] for entry in files for row in entry["rows"]})
    network_names = {row["store"] for entry in files if entry["kind"] == "network" for row in entry["rows"]}
    rows_by_store = defaultdict(list)
    for entry in files:
        for row in entry["rows"]:
            rows_by_store[row["store"]].append((entry, row))
    chosen = []
    used = {}
    for cluster in _store_clusters(names, list(labels)):
        canonical = _canonical_store(cluster, network_names)
        buckets = {}
        for name in cluster:
            for entry, row in rows_by_store.get(name, ()):
                bucket = buckets.get(entry["path"].name)
                if bucket is None:
                    kept = []
                    buckets[entry["path"].name] = (entry["stamp"], entry, kept)
                else:
                    kept = bucket[2]
                kept.append(row)
        if not buckets:
            continue
        _stamp, entry, rows = max(buckets.values(), key=lambda item: item[0])
        for row in rows:
            copied = dict(row)
            copied["store"] = canonical
            chosen.append(copied)
        used[entry["path"].name] = {"name": entry["path"].name, "columns": entry["columns"], "kind": entry["kind"]}
    sources = [used[name] for name in sorted(used)]
    _SALES_CACHE[cache_key] = (chosen, warnings, sources)
    return [dict(row) for row in chosen], list(warnings), [dict(source) for source in sources]


def _read_sales_files(directory):
    files = []
    for path in sorted(directory.glob("*.csv")):
        kind = sniff_menu_kind(path)
        if kind in {"network", "items"}:
            rows, columns = _load_network(path)
            files.append({"path": path, "kind": kind, "rows": rows, "columns": columns, "stamp": file_stamp(path)})
        elif kind == "analysis":
            rows, columns = _load_analysis(path)
            files.append({"path": path, "kind": "analysis", "rows": rows, "columns": columns, "stamp": file_stamp(path)})
    return files


def _period_files(files):
    """The newest network file is the period. Older network files do not fill gaps."""
    network = [entry for entry in files if entry["kind"] == "network"]
    if not network:
        return files
    newest = max(entry["stamp"] for entry in network)
    kept = []
    for entry in files:
        if entry["kind"] == "network" and entry["stamp"] != newest:
            continue
        if entry["kind"] == "analysis" and entry["stamp"] < newest:
            continue
        kept.append(entry)
    return kept


def coming_stores(sales_names, regions):
    """Posist stores with no sales row. Missing is not zero."""
    labels = list(regions or [])
    if not labels or not sales_names:
        return []
    coming = []
    for label in labels:
        if not any(_same_store(label, name, labels) for name in sales_names):
            coming.append(label)
    return sorted(coming, key=str.casefold)


def _store_clusters(names, labels):
    clusters = []
    for name in names:
        placed = False
        for cluster in clusters:
            if any(_same_store(name, other, labels) for other in cluster):
                cluster.append(name)
                placed = True
                break
        if not placed:
            clusters.append([name])
    return clusters


def _canonical_store(cluster, network_names):
    """Keep the menu-mix label when a per-store file is the same outlet."""
    for name in cluster:
        if name in network_names:
            return name
    return max(cluster, key=lambda text: (len(text), text))


def load_categories(directory=None):
    """Dish categories from Torqus categorywise exports. Not used as sales."""
    directory = Path(directory) if directory else menu_directory()
    catalogue = {
        "present": False,
        "file": "",
        "site": "",
        "period": "",
        "by_item": {},
        "columns": [],
    }
    if not directory.exists():
        return catalogue
    candidates = []
    for path in sorted(directory.glob("*.csv")):
        if sniff_menu_kind(path) == "torqus":
            candidates.append(path)
    if not candidates:
        return catalogue
    # A dated filename would win. None of the Torqus files need to be sales.
    path = max(candidates, key=file_stamp)
    rows = _read_csv(path)
    columns = []
    period = ""
    site = ""
    for row in rows[:8]:
        first = (row[0] if row else "").strip()
        lowered = first.lower()
        if lowered.startswith("from"):
            period = re.sub(r"\s+", " ", first)
        if lowered.startswith("site name"):
            site = first.split(":", 1)[-1].strip()
        if any(normalise_header(cell) == "dish name" for cell in row):
            columns = [re.sub(r"\s+", " ", cell.replace("\n", " ")).strip() for cell in row if cell.strip()]
    by_item = {}
    conflicts = set()
    category = None
    for row in rows:
        cells = [cell.strip() for cell in row if cell.strip()]
        first = (row[0] if row else "").strip()
        if len(cells) == 1 and first.endswith(":"):
            category = first[:-1].strip()
            continue
        if not first.isdigit() or len(row) < 2 or not category:
            continue
        name = row[1].strip()
        if not name:
            continue
        key = item_key(name)
        previous = by_item.get(key)
        if previous and previous != category:
            conflicts.add(key)
        else:
            by_item[key] = category
    for key in conflicts:
        by_item.pop(key, None)
    catalogue.update(
        {
            "present": True,
            "file": path.name,
            "site": site,
            "period": period,
            "by_item": by_item,
            "columns": columns,
            "dated_name": filename_date(path.name) is not None,
        }
    )
    return catalogue


def load_regions(path=None):
    """Posist store label -> region. A blank region stays None."""
    path = Path(path) if path else posist_path()
    regions = {}
    warnings = []
    if not path.exists():
        warnings.append(f"{path.name} is not on file, so region is blank.")
        return regions, warnings
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [normalise_header(name) for name in (reader.fieldnames or [])]
        if "region" not in fieldnames:
            warnings.append(f"{path.name} has no region column, so region is blank.")
            return regions, warnings
        for raw in reader:
            normalised = {normalise_header(key): value for key, value in raw.items()}
            store = str(normalised.get("store") or "").strip()
            if not store:
                continue
            region = str(normalised.get("region") or "").strip()
            current = regions.get(store, region or None)
            if store in regions and (current or "") != (region or ""):
                regions[store] = None
            else:
                regions[store] = region or None
    return regions, warnings


def region_for_store(store, regions):
    """Return (posist label or '', region or None)."""
    if not store:
        return "", None
    labels = list(regions)
    matched = match_menu_store(store, labels)
    if matched is None:
        if store in regions:
            return store, regions[store]
        return "", None
    return matched, regions.get(matched)


def is_ideal_plaza(store):
    words = label_words(store)
    return "ideal" in words and "plaza" in words


def load_channel_ratings(directory=None):
    directory = Path(directory) if directory else famepilot_directory()
    path = directory / "channel_ratings_current.csv"
    result = {"present": False, "file": path.name, "columns": [], "rows": [], "warnings": []}
    if not path.exists():
        result["warnings"].append(
            "data/famepilot/channel_ratings_current.csv is not on file, so channel ratings are blank. "
            f"Expected columns: {', '.join(CHANNEL_RATING_COLUMNS)}."
        )
        return result
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        result["columns"] = [normalise_header(name) for name in fieldnames]
        normalised_names = set(result["columns"])
        required = {"store", "zomato delivery", "zomato dining", "google", "swiggy", "as of"}
        # normalise_header turns zomato_delivery into "zomato delivery"
        missing = sorted(required - normalised_names)
        if missing:
            result["warnings"].append(
                f"{path.name} is missing {', '.join(missing)}, so channel ratings were not loaded."
            )
            return result
        for raw in reader:
            normalised = {normalise_header(key): value for key, value in raw.items() if key}
            store = str(normalised.get("store") or "").strip()
            if not store:
                continue
            result["rows"].append(
                {
                    "store": store,
                    "zomato_delivery": _rating(normalised.get("zomato delivery")),
                    "zomato_dining": _rating(normalised.get("zomato dining")),
                    "google": _rating(normalised.get("google")),
                    "swiggy": _rating(normalised.get("swiggy")),
                    "as_of": str(normalised.get("as of") or "").strip(),
                }
            )
    result["present"] = bool(result["rows"])
    if not result["rows"]:
        result["warnings"].append(f"{path.name} has no store rows.")
    return result


def _rating(value):
    if _blank(value):
        return None
    number = parse_number(value)
    if number is None:
        return None
    return {"value": number, "text": str(value).strip()}


def _channel_row(raw, store, channel, date_text, kind, not_shown):
    period_from = parse_date(raw.get("period_from")) if raw.get("period_from") else None
    if period_from is None and raw.get("period_start"):
        period_from = parse_date(raw.get("period_start"))
    period_to = parse_date(raw.get("period_to")) if raw.get("period_to") else None
    if period_to is None and raw.get("period_end"):
        period_to = parse_date(raw.get("period_end"))
    return {
        "store": store,
        "channel": canonical_channel(channel),
        "gross": None if not_shown else (parse_number(raw.get("gross")) if "gross" in raw else None),
        "orders": None if not_shown else (parse_number(raw.get("orders")) if "orders" in raw else None),
        "when": date_text,
        "kind": kind,
        "period_from": period_from,
        "period_to": period_to,
        "status": "not shown" if not_shown else "shown",
        "gross_blank": bool(not_shown) or ("gross" in raw and _blank(raw.get("gross"))),
        "orders_blank": bool(not_shown) or ("orders" not in raw or _blank(raw.get("orders"))),
    }


def _load_processed_channels(directory, range_path, result):
    """Range file is the period. Daily file stays daily, including not-shown days."""
    parsed, columns = _dict_rows(range_path)
    rows = []
    for raw in parsed:
        store = str(raw.get("store") or "").strip()
        channel = str(raw.get("channel") or "").strip()
        if not store or not channel:
            continue
        rows.append(_channel_row(raw, store, channel, "", "total", False))
    dailies = sorted(directory.glob("channel_sales_daily_*.csv"), key=lambda path: (file_stamp(path), path.name))
    if dailies:
        for raw in _dict_rows(dailies[-1])[0]:
            store = str(raw.get("store") or "").strip()
            channel = str(raw.get("channel") or "").strip()
            status = str(raw.get("status") or "").strip().casefold()
            not_shown = status == "not shown"
            if not store or (not channel and not not_shown):
                continue
            date_text = str(raw.get("date") or "").strip()
            rows.append(_channel_row(raw, store, channel, date_text, "daily", not_shown))
    result["file"] = range_path.name
    result["columns"] = columns
    result["rows"] = rows
    result["present"] = bool(rows)
    return result


def load_recon(directory=None):
    """Item gross against channel gross. The gap is not a dish."""
    directory = Path(directory) if directory else menu_directory()
    paths = sorted(directory.glob("item_vs_channel_recon*.csv"))
    rows = []
    if not paths:
        return rows
    parsed, _columns = _dict_rows(paths[-1])
    for raw in parsed:
        store = str(raw.get("store") or "").strip()
        if not store:
            continue
        flag = str(raw.get("flag") or "").strip().casefold()
        rows.append(
            {
                "store": store,
                "items_gross": parse_number(raw.get("items_gross")),
                "channel_gross": parse_number(raw.get("channel_gross")),
                "gap": parse_number(raw.get("gap")),
                "gap_pct": parse_number(raw.get("gap_pct")),
                "flag": flag in {"true", "1", "yes"},
            }
        )
    return rows


def load_channel_sales(directory=None):
    """Channel gross for the period, plus daily rows that are not added in.

    Tony's processed range and daily files win when they are on disk.
    A single channel_sales file from load_posist_raw.py is the fallback.
    A blank date is a period total. A date is a daily row. Status "not shown"
    stays blank, not zero.
    """
    directory = Path(directory) if directory else channels_directory()
    result = {
        "present": False,
        "file": "",
        "columns": [],
        "rows": [],
        "warnings": [],
        "expected": CHANNEL_SALES_COLUMNS,
    }
    if not directory.exists():
        result["warnings"].append(_missing_channel_sales())
        return result
    ranges = sorted(directory.glob("channel_sales_range_*.csv"), key=lambda path: (file_stamp(path), path.name))
    if ranges:
        return _load_processed_channels(directory, ranges[-1], result)
    paths = [
        path for path in directory.glob("channel_sales_*.csv")
        if not path.name.startswith("channel_sales_range_") and not path.name.startswith("channel_sales_daily_")
    ]
    paths = sorted(paths, key=lambda path: (file_stamp(path), path.name))
    if not paths:
        result["warnings"].append(_missing_channel_sales())
        return result
    dated = [path for path in paths if filename_date(path.name)]
    path = dated[-1] if dated else paths[-1]
    parsed, columns = _dict_rows(path)
    result["file"] = path.name
    result["columns"] = columns
    names = set(columns)
    if "store" not in names or "channel" not in names or "gross" not in names:
        result["warnings"].append(
            f"{path.name} columns ({', '.join(columns) or 'none'}) do not include store, channel, and gross, "
            "so the sales mix is blank."
        )
        return result
    rows = []
    for raw in parsed:
        store = str(raw.get("store") or "").strip()
        channel = str(raw.get("channel") or "").strip()
        if not store:
            continue
        date_text = str(raw.get("date") or "").strip() if "date" in raw else ""
        status = str(raw.get("status") or "").strip().casefold()
        not_shown = status == "not shown"
        if not channel and not not_shown:
            continue
        kind = "daily" if date_text else "total"
        rows.append(_channel_row(raw, store, channel, date_text, kind, not_shown))
    result["rows"] = rows
    result["present"] = True
    return result


def store_coverage(store_names, regions):
    """How many Posist stores are named by this set of file labels."""
    labels = list(regions or [])
    if not labels:
        return None
    hit = 0
    for label in labels:
        if any(_same_store(label, name, labels) for name in store_names):
            hit += 1
    return hit, len(labels)


def canonical_channel(value):
    key = re.sub(r"[\s\-]+", " ", str(value or "").strip()).casefold()
    if not key:
        return ""
    return {
        "pos": "POS",
        "swiggy": "Swiggy",
        "zomato": "Zomato",
        "swiggy bolt urgent": "Swiggy-Bolt Urgent",
        "magicpin ordering": "MagicPin-Ordering",
        "rapido": "Rapido",
        "swiggy toing": "Swiggy-Toing",
    }.get(key, str(value).strip())


def _missing_channel_sales():
    return (
        "Channel sales are not on file. Posist Insights splits Gross and orders into POS, Swiggy, and Zomato. "
        "Expected columns date, period_from, period_to, store, channel, gross, orders."
    )
