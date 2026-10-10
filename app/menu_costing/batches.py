"""Semi-processed goods: batch recipes, dish costs, and use versus actual.

A blank stays blank. A missing file is data coming, never zero.
Only a batch item with a real unit cost changes a dish.
"""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

from app.procurement.numbers import (
    format_pct,
    format_period,
    format_qty,
    num_attr,
    parse_date,
    parse_number,
    parse_period,
    percent,
)

_CACHE = {}
THREAT_PCT = 5
USE_LIMIT = 40
COMING = "Data coming"

# Names as they appear on the Restroworks export. Inactive lines and retail kits
# are not the same item, so they are not listed here.
CATALOG = (
    ("Dosa Batter Mix", "Kg", "Batter"),
    ("Idli Batter", "Kg", "Batter"),
    ("Appam Batter", "Kg", "Batter"),
    ("Medu Vada Batter", "Kg", "Batter"),
    ("Beetroot Chutney Bucket", "Kg", "Chutney"),
    ("Dhaniya Chutney Bucket", "Kg", "Chutney"),
    ("Garlic Chutney Bucket", "Kg", "Chutney"),
    ("Mysore Chutney Bucket", "Kg", "Chutney"),
    ("Onion Chutney Bucket", "Kg", "Chutney"),
    ("Raw Mango Chutney Bucket", "Kg", "Chutney"),
    ("Regular White Chutney Bucket", "Kg", "Chutney"),
    ("Regular White Chutney Bucket Outlet", "Kg", "Chutney"),
    ("Special White Coconut Chutney Bucket", "Kg", "Chutney"),
    ("Spicy Coconut Chutney Bucket", "Kg", "Chutney"),
    ("Tomato Onion Chutney Bucket", "Kg", "Chutney"),
    ("Special Daal Bucket", "Kg", "Special daal"),
    ("Sambar Bucket", "Ltr", "Sambar"),
    ("Sambar Bucket - Delhi", "Ltr", "Sambar"),
    ("Jain Sambar Bucket", "Ltr", "Sambar"),
    ("Jain Sambar - Delhi", "Ltr", "Sambar"),
    ("Potato Masala Bucket", "Kg", "Potato masala"),
    ("Potato Masala Bucket Outlet", "Kg", "Potato masala"),
    ("Coconut Shredded", "Kg", "Shredded coconut"),
    ("Imli Water", "Ltr", "Imli water"),
)
_GROUP_ORDER = {name: index for index, name in enumerate(dict.fromkeys(row[2] for row in CATALOG))}
_CATALOG_BY_KEY = {name.casefold(): (name, unit, group) for name, unit, group in CATALOG}

_KG = {"kg", "kgs", "kilogram", "kilograms"}
_GM = {"g", "gm", "gms", "gram", "grams"}
_LTR = {"ltr", "l", "lt", "litre", "liter", "litres", "liters"}
_ML = {"ml", "millilitre", "milliliter", "millilitres", "milliliters"}


def procurement_dir():
    return Path(__file__).resolve().parents[2] / "data" / "procurement"


def posist_dir():
    return Path(__file__).resolve().parents[2] / "data" / "posist"


def clear_batch_cache():
    _CACHE.clear()


def load_batches(directory=None):
    directory = Path(directory) if directory else procurement_dir()
    key = str(directory.resolve()) if directory.exists() else str(directory)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    board = _build(directory)
    _CACHE[key] = board
    return board


def missing_recipe_rows(directory=None):
    board = load_batches(directory)
    return [row for row in board["cards"] if not row["has_recipe"]]


def batch_line_cost(city, ingredient, qty, unit, directory=None):
    """Rupees for one unpriced dish line, or None when this batch has no cost."""
    if qty is None or _is_ro(ingredient):
        return None
    known = load_batches(directory)["costs"].get((_canon_city(city), (ingredient or "").strip().casefold()))
    if not known or known.get("cost") is None:
        return None
    converted = convert_qty(qty, unit, known["unit"])
    if converted is None:
        return None
    return converted * known["cost"]


def apply_batch_costs(rows, directory):
    """Add a known batch cost onto dishes that use it. A blank dish cost stays blank."""
    board = load_batches(directory)
    costs = board["costs"]
    if not costs:
        return
    fills = _dish_fills(directory, costs)
    if not fills:
        return
    for row in rows:
        fill = fills.get(((row.get("outlet") or "").casefold(), (row.get("key") or "").casefold()))
        if not fill or not fill["amount"]:
            continue
        names = [name for name in (row.get("unpriced_names") or []) if name.casefold() not in fill["names"]]
        remaining = bool(names)
        amount = fill["amount"]
        if remaining:
            if row.get("cost") is not None:
                row["cost"] = row["cost"] + amount
            row["unpriced_names"] = names
            row["unpriced_excl"] = len(names)
            row["incomplete"] = True
            row["cost_kind"] = "incomplete"
            row["partial"] = True
            continue
        if row.get("cost") is not None:
            new_cost = row["cost"] + amount
        elif fill["other_priced"]:
            new_cost = None
        else:
            new_cost = amount
        if new_cost is None:
            continue
        row["cost"] = new_cost
        row["unpriced_names"] = []
        row["unpriced_excl"] = 0
        row["incomplete"] = False
        row["partial"] = False
        if fill["estimated"] or row.get("receipt_title") or (row.get("cost_status") or "") == "estimated":
            row["cost_kind"] = "estimated"
        else:
            row["cost_kind"] = "full"
        note = row.get("baseline_text") or ""
        if note.startswith("The dish cost is incomplete"):
            row["baseline_text"] = (
                "The city comparison was built before this batch cost, so the % stays blank."
            )


def batch_page_context(*, city, store, store_id, query, filters, procurement=None, posist=None, recipes=None):
    board = load_batches(recipes or procurement)
    query_key = (query or "").strip().casefold()
    cards = []
    for row in board["cards"]:
        if city and row["city"] != city:
            continue
        if query_key and query_key not in row["item"].casefold():
            continue
        cards.append(_present_card(row))
    cards.sort(key=lambda row: (1 if row["coming"] else 0, row["group_order"], row["item"].casefold()))
    use = load_batch_use(procurement, posist)
    use = use_for_filters(use, filters)
    rows = _present_use(use, city=city, store=store, store_id=store_id, costs=board["costs"])
    note = ""
    ready = bool(use.get("available"))
    if not ready:
        note = use.get("coming") or COMING
    elif not rows:
        note = "No batch use is on file for this view."
    threats = [row for row in rows if row["threat"]][:8]
    return {
        "batch_cards": cards,
        "batch_threats": threats,
        "batch_use_rows": rows[:USE_LIMIT],
        "batch_use_note": note,
        "batch_use_ready": ready and bool(rows),
        "batch_store_note": (
            "Recipes are for the city. The use lines are for this store." if store else ""
        ),
    }


def load_batch_use(procurement=None, posist=None):
    procurement = Path(procurement) if procurement else procurement_dir()
    posist = Path(posist) if posist else posist_dir()
    expected_path = posist / "batch_theoretical_use.csv"
    actual_path = procurement / "batch_actual_use.csv"
    if not expected_path.is_file() or not actual_path.is_file():
        return {"available": False, "rows": [], "coming": COMING}
    expected = _read_expected(expected_path)
    actual = _read_actual(actual_path)
    if expected is None or actual is None:
        return {"available": False, "rows": [], "coming": COMING}
    rows = _join_use(expected, actual)
    return {"available": True, "rows": rows, "coming": ""}


def use_for_filters(bundle, filters):
    if not bundle or not bundle.get("available"):
        return bundle or {"available": False, "rows": [], "coming": COMING}
    kind = (filters or {}).get("cc_range") or ""
    if not kind:
        return bundle
    from app.view_filters import resolve_bounds

    kept = []
    for row in bundle["rows"]:
        start, end = row.get("start"), row.get("end")
        if start is None or end is None:
            continue
        chosen_start, chosen_end = resolve_bounds(filters, start, end)
        if chosen_start == start and chosen_end == end:
            kept.append(row)
    if not kept:
        return {
            "available": False,
            "rows": [],
            "coming": "Use for this date range is not on file. Data coming.",
        }
    hidden = dict(bundle)
    hidden["rows"] = kept
    return hidden


def convert_qty(qty, from_unit, to_unit):
    if qty is None:
        return None
    source = _unit_key(from_unit)
    target = _unit_key(to_unit)
    if not source or not target:
        return None
    if source == target:
        return qty
    if source == "g" and target == "kg":
        return qty / 1000.0
    if source == "kg" and target == "g":
        return qty * 1000.0
    if source == "ml" and target == "ltr":
        return qty / 1000.0
    if source == "ltr" and target == "ml":
        return qty * 1000.0
    return None


def _build(directory):
    catalog = dict(_CATALOG_BY_KEY)
    lines_path = _lines_path(directory)
    usage, recipes, rates = _scan_lines(lines_path, set(catalog))
    summary = _summary_costs(directory)
    costs = {}
    cards = []
    seen = set()
    for key, (name, unit, group) in catalog.items():
        for city in sorted({row_city for row_city, row_key in usage if row_key == key}):
            seen.add((city, key))
            recipe = recipes.get((city, key))
            cost = summary.get((city, key))
            card = _card_from_export(city, name, unit, group, recipe, cost)
            cards.append(card)
            if card["cost"] is not None:
                costs[(city, key)] = {"cost": card["cost"], "unit": card["unit"]}
    csv_rows = _read_batch_recipes(directory / "batch_recipes.csv")
    for (city, key), spec in csv_rows.items():
        name, unit, group = catalog.get(key, (spec["item"], spec["yield_unit"] or "", "Things we make"))
        if key in catalog:
            unit = catalog[key][1]
        card = _card_from_csv(city, name, unit, group, spec, rates, costs)
        cards = [row for row in cards if not (row["city"] == city and row["key"] == key)]
        cards.append(card)
        seen.add((city, key))
        if card["cost"] is not None:
            costs[(city, key)] = {"cost": card["cost"], "unit": card["unit"] or unit}
        elif (city, key) in costs:
            del costs[(city, key)]
    cards.sort(key=lambda row: (row["city"], _GROUP_ORDER.get(row["group"], 99), row["item"].casefold()))
    return {"cards": cards, "costs": costs}


def _card_from_export(city, name, unit, group, recipe, cost):
    ingredients = []
    yield_qty = None
    yield_unit = unit
    if recipe:
        ingredients = recipe["ingredients"]
        yield_qty = recipe["yield_qty"]
        yield_unit = recipe["yield_unit"] or unit
    has_recipe = bool(ingredients)
    return {
        "city": city,
        "item": name,
        "key": name.casefold(),
        "group": group,
        "unit": unit,
        "yield_qty": yield_qty,
        "yield_unit": yield_unit,
        "cost": cost if has_recipe else None,
        "has_recipe": has_recipe,
        "ingredients": ingredients,
        "as_of": "",
    }


def _card_from_csv(city, name, unit, group, spec, rates, costs):
    ingredients = spec["ingredients"]
    cost = _recipe_cost(city, ingredients, spec["yield_qty"], rates, costs)
    return {
        "city": city,
        "item": name,
        "key": name.casefold(),
        "group": group,
        "unit": unit or spec["yield_unit"] or "",
        "yield_qty": spec["yield_qty"],
        "yield_unit": spec["yield_unit"] or unit,
        "cost": cost,
        "has_recipe": bool(ingredients),
        "ingredients": ingredients,
        "as_of": spec.get("as_of") or "",
    }


def _recipe_cost(city, ingredients, yield_qty, rates, costs):
    if not ingredients or yield_qty in (None, 0):
        return None
    total = 0.0
    priced = False
    for row in ingredients:
        if row.get("qty") is None and not _is_ro(row["name"]):
            return None
        if row.get("unpriced") or _is_ro(row["name"]):
            continue
        rate = _ingredient_rate(city, row["name"], row["unit"], rates, costs)
        if rate is None:
            return None
        total += row["qty"] * rate
        priced = True
    if not priced:
        return None
    return total / yield_qty


def _ingredient_rate(city, name, unit, rates, costs):
    known = costs.get((city, name.casefold()))
    if known and known.get("cost") is not None:
        factor = convert_qty(1, unit, known["unit"])
        if factor is not None:
            return known["cost"] * factor
    exact = rates.get((city, name.casefold(), _unit_key(unit)))
    if exact is not None:
        return exact
    for target, sample in (("kg", "g"), ("g", "kg"), ("ltr", "ml"), ("ml", "ltr")):
        if _unit_key(unit) != target:
            continue
        other = rates.get((city, name.casefold(), sample))
        if other is None:
            continue
        factor = convert_qty(1, unit, sample)
        if factor is not None:
            return other * factor
    return None


def _present_card(row):
    from app.menu_costing.catalog import owner_rupee

    per = _per_label(row["unit"] or row["yield_unit"])
    coming = "" if row["has_recipe"] else "recipe coming from Sailesh"
    ingredients = []
    for item in row["ingredients"]:
        qty = format_qty(item.get("qty"))
        unit = _per_label(item.get("unit") or "")
        ingredients.append(
            {
                "name": item["name"],
                "qty": f"{qty} {unit}".strip(),
                "unpriced": bool(item.get("unpriced")),
            }
        )
    yield_text = ""
    if row.get("yield_qty") is not None:
        yield_text = f"{format_qty(row['yield_qty'])} {_per_label(row.get('yield_unit') or '')}".strip()
    return {
        "city": row["city"],
        "item": row["item"],
        "group": row["group"],
        "group_order": _GROUP_ORDER.get(row["group"], 99),
        "yield": yield_text,
        "yield_attr": num_attr(row.get("yield_qty")),
        "cost": owner_rupee(row["cost"]) if row["has_recipe"] else "",
        "cost_attr": num_attr(row["cost"]) if row["has_recipe"] else "",
        "per": per,
        "coming": coming,
        "ingredients": ingredients,
        "as_of": row.get("as_of") or "",
    }


def _present_use(bundle, *, city, store, store_id, costs):
    from app.menu_costing.catalog import owner_rupee

    if not bundle.get("available"):
        return []
    shown = []
    for row in bundle["rows"]:
        if city and row.get("city") and row["city"] != city:
            continue
        if city and not row.get("city"):
            continue
        if not _store_match(row, store, store_id):
            continue
        expected = row.get("expected")
        actual = row.get("actual")
        variance = None
        pct = None
        rupee = None
        same_unit = _unit_key(row.get("expected_unit")) == _unit_key(row.get("actual_unit"))
        if expected is not None and actual is not None and same_unit and _unit_key(row.get("actual_unit")):
            variance = actual - expected
            pct = percent(variance, expected)
        known = costs.get((row.get("city"), row["key"]))
        if variance is not None and known and known.get("cost") is not None:
            converted = convert_qty(variance, row.get("actual_unit"), known["unit"])
            if converted is not None:
                rupee = converted * known["cost"]
        threat = pct is not None and abs(pct) > THREAT_PCT
        if variance is None:
            kind = ""
        elif variance > 0:
            kind = "Wastage"
        elif variance < 0:
            kind = "Leakage"
        else:
            kind = "No gap"
        unit = _per_label(row.get("actual_unit") or row.get("expected_unit") or "")
        shown.append(
            {
                "store": row["store"],
                "item": row["item"],
                "expected": _qty_text(expected, row.get("expected_unit")),
                "expected_missing": expected is None,
                "actual": _qty_text(actual, row.get("actual_unit")),
                "actual_missing": actual is None,
                "made": _qty_text(row.get("made"), row.get("actual_unit")),
                "made_missing": row.get("made") is None,
                "issued": _qty_text(row.get("issued"), row.get("actual_unit")),
                "issued_missing": row.get("issued") is None,
                "kind": kind,
                "qty": _qty_text(abs(variance) if variance is not None else None, unit),
                "qty_attr": num_attr(variance),
                "rupee": owner_rupee(abs(rupee)) if rupee is not None else "",
                "rupee_attr": num_attr(rupee),
                "rupee_missing": rupee is None and variance is not None,
                "pct": format_pct(pct),
                "pct_attr": num_attr(pct),
                "threat": threat,
                "period": row.get("period") or "",
            }
        )
    shown.sort(key=lambda row: (0 if row["threat"] else 1, -(abs(float(row["pct_attr"])) if row["pct_attr"] else 0), row["item"].casefold()))
    return shown


def _qty_text(qty, unit):
    if qty is None:
        return ""
    label = _per_label(unit or "")
    return f"{format_qty(qty)} {label}".strip()


def _store_match(row, store, store_id):
    if store_id and row.get("store_id") == store_id:
        return True
    if store and (row.get("store") or "").casefold() == store.casefold():
        return True
    if not store and not store_id:
        return True
    if store_id and not store:
        return False
    if store and not store_id:
        return (row.get("store") or "").casefold() == store.casefold()
    return False


def _join_use(expected, actual):
    keys = set(expected) | set(actual)
    rows = []
    places = _store_index()
    for key in keys:
        exp = expected.get(key)
        act = actual.get(key)
        sample = exp or act
        place = places.get(sample["store"].casefold()) or places.get(_short_store(sample["store"]))
        city = ""
        store_id = ""
        store = sample["store"]
        if place:
            city = place["city"]
            store_id = place["store_id"]
            store = place["name"] or store
        start, end = _period_bounds(sample.get("period") or "")
        period_label = format_period(start, end) if start or end else (sample.get("period") or "")
        rows.append(
            {
                "store": store,
                "store_id": store_id,
                "city": city,
                "item": sample["item"],
                "key": sample["key"],
                "period": period_label,
                "start": start,
                "end": end,
                "expected": None if exp is None else exp.get("qty"),
                "expected_unit": "" if exp is None else exp.get("unit") or "",
                "made": None if act is None else act.get("made"),
                "issued": None if act is None else act.get("issued"),
                "actual": _actual_qty(act),
                "actual_unit": "" if act is None else act.get("unit") or "",
            }
        )
    return rows


def _actual_qty(row):
    if row is None:
        return None
    if row.get("issued") is not None:
        return row["issued"]
    return row.get("made")


def _read_expected(path):
    try:
        rows = {}
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return {}
            for raw in reader:
                store = (raw.get("store") or "").strip()
                item = (raw.get("batch_item") or "").strip()
                if not store or not item:
                    continue
                period = (raw.get("period") or "").strip()
                key = (store.casefold(), item.casefold(), period.casefold())
                qty = parse_number(raw.get("expected_qty"))
                bucket = rows.get(key)
                if bucket is None:
                    rows[key] = {
                        "store": store,
                        "item": item,
                        "key": item.casefold(),
                        "period": period,
                        "qty": qty,
                        "unit": (raw.get("unit") or "").strip(),
                    }
                elif qty is not None:
                    bucket["qty"] = qty if bucket["qty"] is None else bucket["qty"] + qty
        return rows
    except OSError:
        return None


def _read_actual(path):
    try:
        rows = {}
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return {}
            for raw in reader:
                store = (raw.get("store") or "").strip()
                item = (raw.get("batch_item") or "").strip()
                if not store or not item:
                    continue
                period = (raw.get("period") or "").strip()
                key = (store.casefold(), item.casefold(), period.casefold())
                made = parse_number(raw.get("made_qty"))
                issued = parse_number(raw.get("issued_qty"))
                bucket = rows.get(key)
                if bucket is None:
                    rows[key] = {
                        "store": store,
                        "item": item,
                        "key": item.casefold(),
                        "period": period,
                        "made": made,
                        "issued": issued,
                        "unit": (raw.get("unit") or "").strip(),
                    }
                else:
                    if made is not None:
                        bucket["made"] = made if bucket["made"] is None else bucket["made"] + made
                    if issued is not None:
                        bucket["issued"] = issued if bucket["issued"] is None else bucket["issued"] + issued
        return rows
    except OSError:
        return None


def _period_bounds(text):
    start, end = parse_period(text)
    if start or end:
        return start, end
    day = parse_date(text)
    if day is not None:
        return day, day
    return None, None


def _store_index():
    from app.store_master import get_index
    from app.view_filters import CITY_LABEL

    found = {}
    for row in get_index().rows:
        city = CITY_LABEL.get(row.get("region") or "", "")
        info = {
            "store_id": row.get("store_id") or "",
            "name": row.get("display_name") or row.get("posist_name") or "",
            "city": city,
        }
        for label in (row.get("display_name"), row.get("posist_name"), row.get("store_id")):
            if not label:
                continue
            found.setdefault(label.casefold(), info)
            short = _short_store(label)
            if short:
                found.setdefault(short, info)
    return found


def _short_store(label):
    short = (label or "").split("(")[0].strip()
    short = short.replace("Dosa Coffee - ", "").strip().casefold()
    return short


def _dish_fills(directory, costs):
    path = _lines_path(directory)
    if path is None or not path.is_file():
        return {}
    fills = {}
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            has_source = "price_source" in (reader.fieldnames or [])
            for raw in reader:
                if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
                    continue
                if not _truthy(raw.get("is_menu_item")):
                    continue
                outlet = (raw.get("outlet") or "").strip()
                item = (raw.get("item_name") or raw.get("recipe_name") or "").strip()
                ingredient = (raw.get("ingredient_name") or "").strip()
                if not outlet or not item or not ingredient or _is_ro(ingredient):
                    continue
                source = (raw.get("price_source") or "").strip().casefold() if has_source else ""
                priced = source in {"restroworks", "grn_estimate"} or (
                    not has_source and not _truthy(raw.get("unpriced"))
                )
                bucket = fills.setdefault(
                    (outlet.casefold(), item.casefold()),
                    {"amount": 0.0, "names": set(), "estimated": False, "other_priced": False, "hit": False},
                )
                if source == "grn_estimate":
                    bucket["estimated"] = True
                if priced:
                    bucket["other_priced"] = True
                    continue
                known = costs.get((_canon_city(raw.get("city")), ingredient.casefold()))
                if not known or known.get("cost") is None:
                    continue
                qty = parse_number(raw.get("ingredient_qty"))
                converted = convert_qty(qty, raw.get("ingredient_unit"), known["unit"])
                if converted is None:
                    continue
                bucket["amount"] += converted * known["cost"]
                bucket["names"].add(ingredient.casefold())
                bucket["hit"] = True
    except OSError:
        return {}
    return {key: value for key, value in fills.items() if value["hit"]}


def _scan_lines(path, catalog_keys):
    usage = set()
    grouped = defaultdict(list)
    rates = defaultdict(list)
    if path is None or not path.is_file():
        return usage, {}, {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
                continue
            city = _canon_city(raw.get("city"))
            ingredient = (raw.get("ingredient_name") or "").strip()
            if city and ingredient:
                usage.add((city, ingredient.casefold()))
                _keep_rate(rates, city, raw)
            item = (raw.get("item_name") or "").strip()
            if not city or not item or item.casefold() not in catalog_keys:
                continue
            if _truthy(raw.get("is_inactive_ingredient")):
                continue
            name = ingredient
            if not name:
                continue
            grouped[(city, item.casefold(), (raw.get("outlet") or "").strip())].append(
                {
                    "yield_qty": parse_number(raw.get("recipe_qty")),
                    "yield_unit": (raw.get("unit") or "").strip(),
                    "name": name,
                    "qty": parse_number(raw.get("ingredient_qty")),
                    "unit": (raw.get("ingredient_unit") or "").strip(),
                    "unpriced": _truthy(raw.get("unpriced")) or _is_ro(name),
                }
            )
    recipes = {}
    by_item = defaultdict(list)
    for (city, key, outlet), lines in grouped.items():
        by_item[(city, key)].append((outlet, lines))
    for (city, key), outlets in by_item.items():
        outlets.sort(key=lambda pair: (-len(pair[1]), pair[0].casefold()))
        _outlet, lines = outlets[0]
        seen = set()
        ingredients = []
        yield_qty = None
        yield_unit = ""
        for line in lines:
            if yield_qty is None and line["yield_qty"] is not None:
                yield_qty = line["yield_qty"]
                yield_unit = line["yield_unit"]
            marker = line["name"].casefold()
            if marker in seen:
                continue
            seen.add(marker)
            ingredients.append(
                {
                    "name": line["name"],
                    "qty": line["qty"],
                    "unit": line["unit"],
                    "unpriced": line["unpriced"],
                }
            )
        recipes[(city, key)] = {
            "yield_qty": yield_qty,
            "yield_unit": yield_unit,
            "ingredients": ingredients,
        }
    medians = {key: statistics.median(values) for key, values in rates.items() if values}
    return usage, recipes, medians


def _keep_rate(rates, city, raw):
    if _truthy(raw.get("unpriced")) or _is_ro(raw.get("ingredient_name")):
        return
    qty = parse_number(raw.get("ingredient_qty"))
    cost = parse_number(raw.get("ingredient_cost_avg"))
    if cost is None or qty in (None, 0):
        return
    unit = _unit_key(raw.get("ingredient_unit"))
    name = (raw.get("ingredient_name") or "").strip().casefold()
    if not unit or not name:
        return
    rates[(city, name, unit)].append(cost / qty)


def _summary_costs(directory):
    path = directory / "menu_item_cost_summary.csv"
    costs = {}
    if not path.is_file():
        return costs
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or "").strip()
            city = _canon_city(raw.get("city"))
            if not name or not city or name.casefold() not in _CATALOG_BY_KEY:
                continue
            cost = parse_number(raw.get("city_baseline_median_cost"))
            if cost is None:
                continue
            costs[(city, name.casefold())] = cost
    return costs


def _read_batch_recipes(path):
    if not path.is_file():
        return {}
    grouped = defaultdict(list)
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                city = _canon_city(raw.get("city"))
                item = (raw.get("batch_item") or "").strip()
                ingredient = (raw.get("ingredient") or "").strip()
                if not city or not item or not ingredient:
                    continue
                grouped[(city, item.casefold())].append(
                    {
                        "item": item,
                        "name": ingredient,
                        "qty": parse_number(raw.get("qty")),
                        "unit": (raw.get("unit") or "").strip(),
                        "yield_qty": parse_number(raw.get("yield_qty")),
                        "yield_unit": (raw.get("yield_unit") or "").strip(),
                        "as_of": (raw.get("as_of") or "").strip(),
                        "unpriced": _is_ro(ingredient),
                    }
                )
    except OSError:
        return {}
    specs = {}
    for key, lines in grouped.items():
        yield_qty = next((line["yield_qty"] for line in lines if line["yield_qty"] is not None), None)
        yield_unit = next((line["yield_unit"] for line in lines if line["yield_unit"]), "")
        as_of = next((line["as_of"] for line in lines if line["as_of"]), "")
        specs[key] = {
            "item": lines[0]["item"],
            "yield_qty": yield_qty,
            "yield_unit": yield_unit,
            "as_of": as_of,
            "ingredients": [
                {
                    "name": line["name"],
                    "qty": line["qty"],
                    "unit": line["unit"],
                    "unpriced": line["unpriced"],
                }
                for line in lines
            ],
        }
    return specs


def _lines_path(directory):
    plain = directory / "menu_item_cost_lines.csv"
    if plain.is_file():
        return plain
    estimated = directory / "menu_item_cost_lines_estimated.csv"
    if estimated.is_file():
        return estimated
    return None


def _canon_city(value):
    key = " ".join((value or "").casefold().split())
    if key in {"kolkata", "calcutta"}:
        return "Kolkata"
    if key in {"delhi", "delhi ncr", "ncr"}:
        return "Delhi NCR"
    return (value or "").strip()


def _unit_key(unit):
    key = " ".join((unit or "").casefold().split())
    if key in _KG:
        return "kg"
    if key in _GM:
        return "g"
    if key in _LTR:
        return "ltr"
    if key in _ML:
        return "ml"
    return key


def _per_label(unit):
    key = _unit_key(unit)
    if key == "kg":
        return "kg"
    if key == "ltr":
        return "ltr"
    if key == "g":
        return "g"
    if key == "ml":
        return "ml"
    return (unit or "").strip()


def _is_ro(name):
    text = " ".join((name or "").casefold().replace(".", " ").split())
    return text in {"ro water", "r o water"}


def _truthy(value):
    return str(value or "").strip().casefold() in {"true", "1", "yes"}
