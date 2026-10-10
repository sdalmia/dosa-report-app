"""Recipe costs from menu_item_cost.csv and ingredient lines.

A blank cost stays blank. Each outlet is compared with its own city's median.
"""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

from app.procurement.numbers import parse_number, percent

_CACHE = {}
_LINE_CACHE = {}
# Slim rows for one outlet in one cost-line file. Keyed by path mtime. A few outlets only.
_LINE_INDEX = {}

INCOMPLETE_STATUSES = frozenset({"partial_unpriced_ingredients", "no_priced_ingredients"})
STALE_GAP = 10
_KIND = {"fully_priced": "full", "estimated": "estimated", "incomplete": "incomplete"}
_PACKAGING = ("container", "glass", "bottle", "napkin", "straw", "stirrer", "cup", "lid")
_BASELINE = {
    "row_cost_incomplete": "The dish cost is incomplete, so it is left out of the city comparison.",
    "no_cost": "This dish has no cost, so there is no comparison.",
    "no_fully_priced_outlet_in_city": "No outlet in this city has a full cost, so there is no median.",
    "fewer_than_3_fully_priced_outlets": "Fewer than 3 outlets have a full cost, so there is no city median.",
    "median_implausibly_low_below_Rs1": "The city median is under ₹1, so the comparison is left blank.",
    "median_below_Rs1_stub_recipe_or_addon": (
        "The city median is under ₹1. The recipe looks like a stub or an add-on, so the comparison is left blank."
    ),
    "channel_tab_not_compared_to_base": "This tab is not compared with the base recipe.",
}


def procurement_dir():
    return Path(__file__).resolve().parents[2] / "data" / "procurement"


def load_recipes(directory=None):
    directory = Path(directory) if directory else procurement_dir()
    key = str(directory.resolve()) if directory.exists() else str(directory)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    bundle = _read(directory)
    _CACHE[key] = bundle
    return bundle


def clear_caches():
    _CACHE.clear()
    _LINE_CACHE.clear()
    _LINE_INDEX.clear()


def _read(directory):
    estimated = directory / "menu_item_cost_estimated.csv"
    lines_path = directory / "menu_item_cost_lines.csv"
    price_gaps = []
    if estimated.is_file():
        items = _read_estimated_items(estimated)
        estimated_lines = directory / "menu_item_cost_lines_estimated.csv"
        if estimated_lines.is_file():
            lines_path = estimated_lines
            receipts, rates, labels, ingredients = _scan_estimated_lines(estimated_lines)
            _attach_receipts(items, receipts)
            _attach_ingredients(items, ingredients)
            price_gaps = _price_gaps(directory / "supplier_item_rates.csv", rates, labels)
    else:
        items = _read_items(directory / "menu_item_cost.csv")
    by_outlet = {}
    outlets = {}
    for row in items:
        if row["tab"] != "base" or not row["menu"]:
            continue
        by_outlet[(row["city"], row["outlet"], row["key"])] = row
        outlets.setdefault(row["city"], set()).add(row["outlet"])
    by_city = _index_cities(by_outlet, _read_spreads(directory / "menu_item_cost_summary.csv"))
    cities = sorted(set(outlets) | {row["city"] for row in by_city.values()}, key=_city_rank)
    return {
        "directory": directory,
        "by_outlet": by_outlet,
        "by_city": by_city,
        "outlets": {city: sorted(names) for city, names in outlets.items()},
        "cities": cities,
        "lines_path": lines_path,
        "price_gaps": price_gaps,
    }


def _city_rank(city):
    key = (city or "").casefold()
    if "kolkata" in key:
        return (0, key)
    if "delhi" in key:
        return (1, key)
    return (9, key)


def _truthy(value):
    return str(value or "").strip().casefold() in {"true", "1", "yes"}


def is_ro_water(name):
    text = " ".join((name or "").casefold().replace(".", " ").split())
    return text in {"ro water", "r o water"}


def split_names(value):
    names = []
    for part in str(value or "").split(";"):
        name = part.strip()
        if name:
            names.append(name)
    return names


def dish_incomplete(excl_count, status):
    if excl_count is not None and excl_count > 0:
        return True
    return (status or "").strip() in INCOMPLETE_STATUSES


def summary_incomplete(compared, fully_priced, names):
    if any(name for name in names if not is_ro_water(name)):
        return True
    if compared is None or fully_priced is None:
        return False
    return fully_priced < compared


def _read_items(path):
    if not path.is_file():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            outlet = (raw.get("outlet") or "").strip()
            if not name or not city or not outlet:
                continue
            excl = parse_number(raw.get("unpriced_excl_ro_water_count"))
            status = (raw.get("cost_status") or "").strip()
            names = split_names(raw.get("unpriced_ingredients"))
            rows.append(
                {
                    "outlet": outlet,
                    "city": city,
                    "item": name,
                    "key": name.casefold(),
                    "tab": (raw.get("recipe_tab") or "base").strip() or "base",
                    "menu": _truthy(raw.get("is_menu_item")),
                    "cost": parse_number(raw.get("cost_per_portion_avg")),
                    "median": parse_number(raw.get("city_baseline_median_cost")),
                    "vs_pct": parse_number(raw.get("vs_city_baseline_pct")),
                    "baseline_outlets": parse_number(raw.get("city_baseline_outlets")),
                    "baseline_text": explain_baseline(
                        raw.get("baseline_note"), parse_number(raw.get("city_baseline_outlets"))
                    ),
                    "only_ingredient": "",
                    "packaging_only": False,
                    "partial": _truthy(raw.get("has_unpriced_ingredient")),
                    "unpriced_excl": excl,
                    "cost_status": status,
                    "unpriced_names": [name for name in names if not is_ro_water(name)],
                    "incomplete": dish_incomplete(excl, status),
                    "cost_kind": "incomplete" if dish_incomplete(excl, status) else "full",
                    "receipt_title": "",
                }
            )
    return rows


def _read_estimated_items(path):
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            outlet = (raw.get("outlet") or "").strip()
            if not name or not city or not outlet:
                continue
            excl = parse_number(raw.get("still_unpriced_excl_ro_water_count"))
            status = (raw.get("cost_status_estimated") or "").strip()
            kind = _cost_kind(status, excl)
            rows.append(
                {
                    "outlet": outlet,
                    "city": city,
                    "item": name,
                    "key": name.casefold(),
                    "tab": (raw.get("recipe_tab") or "base").strip() or "base",
                    "menu": _truthy(raw.get("is_menu_item")),
                    "cost": parse_number(raw.get("cost_per_portion_estimated")),
                    "median": parse_number(raw.get("city_baseline_median_cost_estimated")),
                    "vs_pct": parse_number(raw.get("vs_city_baseline_pct_estimated")),
                    "baseline_outlets": parse_number(raw.get("city_baseline_outlets_estimated")),
                    "baseline_text": explain_baseline(
                        raw.get("baseline_note_estimated"),
                        parse_number(raw.get("city_baseline_outlets_estimated")),
                    ),
                    "only_ingredient": "",
                    "packaging_only": False,
                    "partial": kind != "full",
                    "unpriced_excl": excl,
                    "cost_status": status,
                    "unpriced_names": [n for n in split_names(raw.get("still_unpriced_ingredients")) if not is_ro_water(n)],
                    "incomplete": kind == "incomplete",
                    "cost_kind": kind,
                    "receipt_title": "",
                }
            )
    return rows


def _cost_kind(status, excl):
    if excl is not None and excl > 0:
        return "incomplete"
    return _KIND.get((status or "").strip(), "incomplete")


def explain_baseline(note, outlets):
    """Owner sentence for a blank comparison. An ok note stays blank."""
    key = (note or "").strip()
    if not key or key == "ok":
        return ""
    text = _BASELINE.get(key) or key.replace("_", " ")
    if outlets is None:
        return text
    count = int(round(float(outlets)))
    noun = "outlet" if count == 1 else "outlets"
    return f"{text} The baseline has {count} {noun}."


def _first_present(rows, field):
    for row in rows:
        value = row.get(field)
        if value is not None and value != "":
            return value
    return None


def _index_cities(by_outlet, spreads):
    """One city row per dish. The median and the blank-note come from the cost file."""
    groups = defaultdict(list)
    for row in by_outlet.values():
        groups[(row["city"], row["key"])].append(row)
    by_city = {}
    for (city, key), rows in groups.items():
        median = _first_present(rows, "median")
        note = ""
        if median is None:
            note = next((row.get("baseline_text") or "" for row in rows if row.get("baseline_text")), "")
        by_city[(city, key)] = {
            "city": city,
            "item": rows[0]["item"],
            "key": key,
            "menu": True,
            "median": median,
            "spread": spreads.get((city, key)),
            "baseline_outlets": _first_present(rows, "baseline_outlets"),
            "baseline_text": note,
            "incomplete": False,
            "cost_kind": "",
        }
    return by_city


def _read_spreads(path):
    if not path.is_file():
        return {}
    spreads = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            if not name or not city:
                continue
            spreads[(city, name.casefold())] = parse_number(raw.get("spread_within_city_pct"))
    return spreads


def _attach_receipts(items, receipts):
    for row in items:
        titles = receipts.get((row["outlet"].casefold(), row["key"])) or []
        row["receipt_title"] = " · ".join(titles)


def _scan_estimated_lines(path):
    receipts = defaultdict(list)
    seen = defaultdict(set)
    rates = defaultdict(lambda: defaultdict(list))
    labels = {}
    ingredients = defaultdict(set)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
                continue
            outlet = (raw.get("outlet") or "").strip()
            item = (raw.get("item_name") or "").strip()
            ingredient = (raw.get("ingredient_name") or "").strip()
            if not outlet or not ingredient:
                continue
            if item:
                ingredients[(outlet.casefold(), item.casefold())].add(ingredient)
            source = (raw.get("price_source") or "").strip().casefold()
            if source == "grn_estimate" and item:
                title = _receipt_title(raw.get("receipt_ref"), ingredient)
                key = (outlet.casefold(), item.casefold())
                if title and title not in seen[key]:
                    seen[key].add(title)
                    receipts[key].append(title)
            if source == "restroworks":
                qty = parse_number(raw.get("ingredient_qty"))
                cost = parse_number(raw.get("ingredient_cost_avg"))
                unit = (raw.get("ingredient_unit") or "").strip()
                city = (raw.get("city") or "").strip()
                if city and qty not in (None, 0) and cost is not None:
                    rate_key = (city, ingredient.casefold(), unit.casefold())
                    labels[rate_key] = ingredient
                    rates[rate_key][outlet].append(cost / qty)
    return receipts, rates, labels, ingredients


def _attach_ingredients(items, ingredients):
    for row in items:
        names = ingredients.get((row["outlet"].casefold(), row["key"])) or set()
        if len(names) != 1:
            continue
        only = next(iter(names))
        row["only_ingredient"] = only
        row["packaging_only"] = _packaging_only(row["item"], only)


def _packaging_only(item, ingredient):
    """A food dish whose only line is a container, cup, or similar."""
    text = (ingredient or "").casefold()
    if not any(word in text for word in _PACKAGING):
        return False
    item_text = (item or "").casefold()
    return not any(word in item_text for word in _PACKAGING)


def _receipt_title(ref, ingredient):
    kept = []
    for part in str(ref or "").split(";"):
        text = part.strip()
        low = text.casefold()
        if not text or ".csv" in low or ".xls" in low or "lines," in low:
            continue
        kept.append(text)
    if not kept:
        return ingredient
    return ingredient + " — " + ", ".join(kept)


def _price_gaps(path, rates, labels):
    if not path.is_file():
        return []
    receipts = _receipt_rates(path)
    gaps = []
    for (city, name_key, unit_key), outlets in rates.items():
        outlet_rates = [statistics.median(values) for values in outlets.values() if values]
        if not outlet_rates:
            continue
        recipe_rate = statistics.median(outlet_rates)
        receipt = receipts.get((_receipt_city(city), name_key, unit_key))
        if receipt is None or recipe_rate in (None, 0):
            continue
        gap = percent(receipt["rate"] - recipe_rate, recipe_rate)
        if gap is None or abs(gap) <= STALE_GAP:
            continue
        gaps.append(
            {
                "city": city,
                "item": labels.get((city, name_key, unit_key), name_key),
                "unit": receipt["unit"] or unit_key,
                "recipe_rate": recipe_rate,
                "receipt_rate": receipt["rate"],
                "gap": gap,
            }
        )
    gaps.sort(key=lambda row: (-abs(row["gap"]), row["item"].casefold()))
    return gaps


def _receipt_city(city):
    key = (city or "").casefold()
    if "delhi" in key:
        return "delhi"
    if "kolkata" in key:
        return "kolkata"
    return key


def _receipt_rates(path):
    totals = defaultdict(lambda: [0.0, 0.0, ""])
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            unit = (raw.get("unit") or "").strip()
            rate = parse_number(raw.get("wavg_rate"))
            qty = parse_number(raw.get("qty"))
            if not name or not city or rate is None or qty in (None, 0):
                continue
            bucket = totals[(city.casefold(), name.casefold(), unit.casefold())]
            bucket[0] += qty * rate
            bucket[1] += qty
            bucket[2] = unit
    rates = {}
    for key, (amount, qty, unit) in totals.items():
        if qty:
            rates[key] = {"rate": amount / qty, "unit": unit}
    return rates


def _read_summary(path):
    if not path.is_file():
        return []
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = (raw.get("city") or "").strip()
            if not name or not city:
                continue
            compared = parse_number(raw.get("outlets_compared"))
            fully = parse_number(raw.get("outlets_fully_priced"))
            names = split_names(raw.get("common_unpriced_ingredients"))
            rows.append(
                {
                    "city": city,
                    "item": name,
                    "key": name.casefold(),
                    "menu": _truthy(raw.get("is_menu_item")),
                    "median": parse_number(raw.get("city_baseline_median_cost")),
                    "spread": parse_number(raw.get("spread_within_city_pct")),
                    "low": parse_number(raw.get("min_cost_avg")),
                    "high": parse_number(raw.get("max_cost_avg")),
                    "outlet_min": (raw.get("outlet_min") or "").strip(),
                    "outlet_max": (raw.get("outlet_max") or "").strip(),
                    "compared": compared,
                    "fully_priced": fully,
                    "common_unpriced": names,
                    "with_recipe": parse_number(raw.get("outlets_with_recipe")),
                    "incomplete": summary_incomplete(compared, fully, names),
                }
            )
    return rows


def _file_token(path):
    st = Path(path).stat()
    return (str(Path(path).resolve()), st.st_mtime_ns, st.st_size)


def _line_from_raw(raw):
    """One ingredient row as a tuple. Blank line costs stay blank.

    Tuples stay in the cache. Dicts are built only for the dish on screen.
    """
    ingredient = (raw.get("ingredient_name") or "").strip()
    if not ingredient:
        return None
    qty = parse_number(raw.get("ingredient_qty"))
    source = (raw.get("price_source") or "").strip().casefold()
    if source:
        line = parse_number(raw.get("ingredient_cost_estimated_per_portion"))
        if line is None and source == "restroworks":
            line = parse_number(raw.get("ingredient_cost_avg_per_portion"))
        blank = source == "none" or line is None
    else:
        line = parse_number(raw.get("ingredient_cost_avg_per_portion"))
        if line is None:
            line = parse_number(raw.get("ingredient_cost_avg"))
        blank = _truthy(raw.get("unpriced")) or line is None
    unit_cost = parse_number(raw.get("est_rate")) if source == "grn_estimate" else None
    if unit_cost is None and line is not None and qty not in (None, 0) and not blank:
        unit_cost = line / qty
    return (
        ingredient,
        qty,
        (raw.get("ingredient_unit") or "").strip(),
        None if blank else unit_cost,
        None if blank else line,
        blank,
        source == "grn_estimate" and not blank,
        _receipt_title(raw.get("receipt_ref"), ingredient) if source == "grn_estimate" and not blank else "",
        _truthy(raw.get("is_inactive_ingredient")),
    )


def _line_dict(row):
    return {
        "ingredient": row[0],
        "qty": row[1],
        "unit": row[2],
        "unit_cost": row[3],
        "line_cost": row[4],
        "unpriced": row[5],
        "estimated": row[6],
        "receipt": row[7],
        "inactive": row[8],
    }


def _outlet_lines(path, outlet):
    """Base-tab lines for one outlet, grouped by item.

    Other outlets are skipped while the file is read, so a dish page does not
    keep all 75,800 rows. A changed mtime rebuilds that outlet.
    """
    wanted = (outlet or "").casefold()
    token = (_file_token(path), wanted)
    cached = _LINE_INDEX.get(token)
    if cached is not None:
        return cached
    grouped = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
                continue
            if (raw.get("outlet") or "").strip().casefold() != wanted:
                continue
            name = (raw.get("item_name") or raw.get("recipe_name") or "").strip()
            if not name:
                continue
            row = _line_from_raw(raw)
            if row is None:
                continue
            grouped.setdefault(name.casefold(), []).append(row)
    if len(_LINE_INDEX) >= 4:
        _LINE_INDEX.clear()
        _LINE_CACHE.clear()
    _LINE_INDEX[token] = grouped
    return grouped


def recipe_lines(bundle, outlet, item):
    """Ingredient rows for one store and item. Blank line costs stay blank."""
    path = bundle.get("lines_path")
    if path is None or not Path(path).is_file():
        return []
    cache_key = (str(path), (outlet or "").casefold(), (item or "").casefold())
    if cache_key in _LINE_CACHE:
        return _LINE_CACHE[cache_key]
    grouped = _outlet_lines(path, outlet)
    rows = [_line_dict(row) for row in grouped.get((item or "").casefold(), ())]
    _LINE_CACHE[cache_key] = rows
    return rows
