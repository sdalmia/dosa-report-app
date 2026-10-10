"""Tony's expected-use comparison for 24 Sep–8 Oct.

The verdict column is what the owner sees. The read column stays off the page.
A blank quantity stays blank. Booked output is what the kitchen entered so it
matches dispatch. It is not a physical measure.
"""

import csv
from pathlib import Path

from app.procurement.numbers import format_period, format_qty, num_attr, parse_number, sum_present

BOOKED_NOTE = "Booked to match what is sent out, not physically measured."
_JAIN = "Jain Sambar Bucket"
_DOSA = "Dosa Batter Mix"
_BENNE = "Benne Dosa Batter (Pack Size -3 Kg )"
_COCONUT = "Coconut Shredded"
_SAMBAR = ("Sambar Bucket", "Sambar Bucket - Delhi")
_DAAL = "Special Daal Bucket"
_NAME_PAIRS = (
    ("Medu Vada Batter", "Medu Vada Batter Mix"),
    ("Malabar Paratha Dough", "Malabar Paratha  (1pkt= 6Pcs)"),
)


def try_verdict(procurement, posist):
    path = Path(posist) / "batch_use_comparison.csv"
    if not path.is_file():
        return None
    rows = _read_comparison(path, _city_index(posist))
    period = _period_from(Path(procurement) / "batch_actual_use.csv", Path(posist) / "batch_theoretical_use.csv")
    start, end = _bounds(period)
    label = format_period(start, end) if start or end else ""
    for row in rows:
        row["period"] = label
        row["start"] = start
        row["end"] = end
    kitchens = _kitchens(Path(procurement) / "batch_actual_use.csv", label, start, end)
    return {
        "available": True,
        "mode": "verdict",
        "rows": rows,
        "kitchens": kitchens,
        "period": label,
        "start": start,
        "end": end,
        "coming": "",
    }


def filter_verdict_dates(bundle, filters):
    kind = (filters or {}).get("cc_range") or ""
    if not kind:
        return bundle
    from app.view_filters import resolve_bounds

    start, end = bundle.get("start"), bundle.get("end")
    if start is None or end is None:
        return {"available": False, "mode": "verdict", "rows": [], "kitchens": [], "coming": "Use for this date range is not on file. Data coming."}
    chosen_start, chosen_end = resolve_bounds(filters, start, end)
    if chosen_start == start and chosen_end == end:
        return bundle
    return {
        "available": False,
        "mode": "verdict",
        "rows": [],
        "kitchens": [],
        "coming": "Use for this date range is not on file. Data coming.",
        "period": "",
    }


def verdict_view(bundle, *, city, store, store_id, query):
    from app.menu_costing.batches import _store_match
    from app.menu_costing.catalog import owner_count, owner_rupee

    rows = []
    for row in bundle.get("rows") or []:
        if city and row.get("city") and row["city"] != city:
            continue
        if city and not row.get("city"):
            continue
        if not _store_match(row, store, store_id):
            continue
        if query and query not in (row.get("item") or "").casefold():
            continue
        rows.append(row)
    alerts = _alerts(rows, bundle.get("rows") or [], city, owner_count, owner_rupee, query)
    shown = [_present_row(row, owner_count, owner_rupee) for row in rows]
    shown.sort(key=_sort_key)
    kitchens = list(bundle.get("kitchens") or [])
    return {
        "alerts": alerts,
        "rows": shown,
        "kitchens": kitchens,
        "period": bundle.get("period") or "",
        "booked_note": BOOKED_NOTE if kitchens else "",
    }


def _alerts(rows, all_rows, city, owner_count, owner_rupee, query):
    alerts = []
    physical = _physical_alert(rows, owner_count)
    if physical:
        alerts.append(physical)
    # The surplus is booked back at stock count in both cities. The total is
    # the accounting effect Sailesh is correcting, so a city filter does not split it.
    recipe = _recipe_alert(all_rows, owner_count, owner_rupee)
    if recipe:
        alerts.append(recipe)
    info = _sambar_info(owner_count)
    if info and not query:
        alerts.append(info)
    receive = _receive_alert(rows, city, owner_rupee)
    if receive:
        alerts.append(receive)
    names = _name_alert(rows)
    if names:
        alerts.append(names)
    if query:
        alerts = [row for row in alerts if _alert_matches(row, query)]
    return alerts


def _physical_alert(rows, owner_count):
    pairs = []
    jain = [row for row in rows if row["item"] == _JAIN and row.get("city") == "Kolkata"]
    if jain:
        sent = sum_present(row["issued"] for row in jain)
        used = sum_present(row["used"] for row in jain)
        if sent is not None and used is not None:
            pairs.append(
                {
                    "left_label": "Jain sambar sent",
                    "left": f"{owner_count(sent)} L",
                    "left_attr": _attr(sent),
                    "right_label": "Deducted",
                    "right": f"{owner_count(used)} L",
                    "right_attr": _attr(used),
                }
            )
    for item, label in ((_DOSA, "Dosa batter"), (_BENNE, "Benne batter")):
        picked = [row for row in rows if row["item"] == item and row.get("city") == "Delhi NCR"]
        gap = sum_present(row["gain_qty"] for row in picked)
        if gap is None or gap >= 0:
            continue
        pairs.append(
            {
                "left_label": label,
                "left": f"{owner_count(abs(gap))} kg short",
                "left_attr": _attr(gap),
                "right_label": "City",
                "right": "Delhi",
                "right_attr": "",
            }
        )
    if not pairs:
        return None
    parts = []
    if any(pair["left_label"] == "Jain sambar sent" for pair in pairs):
        parts.append(
            "Kolkata Jain sambar was sent but much less was deducted. It was probably served as regular sambar."
        )
    batter = [pair["left_label"] for pair in pairs if pair["left_label"] in {"Dosa batter", "Benne batter"}]
    if len(batter) == 2:
        parts.append("Delhi dosa batter and benne batter are short on the physical count.")
    elif batter:
        parts.append(f"Delhi {batter[0].casefold()} is short on the physical count.")
    detail = " ".join(parts) or "More left the kitchen than the recipe deducted."
    return {
        "kind": "physical",
        "severity": "red",
        "kicker": "Physical loss",
        "title": "Physical loss",
        "detail": detail,
        "action": "Floor check by Sanjoy.",
        "pairs": pairs,
        "items": f"{_JAIN} {_DOSA} {_BENNE}",
    }


def _recipe_alert(rows, owner_count, owner_rupee):
    coconut = _gain(rows, {_COCONUT})
    sambar = _gain(rows, set(_SAMBAR))
    daal = _gain(rows, {_DAAL})
    pairs = []
    if coconut["qty"] is not None and coconut["qty"] > 0:
        pairs.append(
            {
                "left_label": "Coconut",
                "left": f"+{owner_count(coconut['qty'])} kg",
                "left_attr": _attr(coconut["qty"]),
                "right_label": "Stock-count gain",
                "right": owner_rupee(coconut["amt"]) if coconut["amt"] is not None else "",
                "right_attr": _attr(coconut["amt"]),
            }
        )
    if sambar["qty"] is not None and sambar["qty"] > 0:
        left = f"+{owner_count(sambar['qty'])} L"
        right = f"+{owner_count(daal['qty'])} kg" if daal["qty"] is not None and daal["qty"] > 0 else ""
        pairs.append(
            {
                "left_label": "Sambar",
                "left": left,
                "left_attr": _attr(sambar["qty"]),
                "right_label": "Daal" if right else "",
                "right": right,
                "right_attr": _attr(daal["qty"]) if right else "",
            }
        )
    elif daal["qty"] is not None and daal["qty"] > 0:
        pairs.append(
            {
                "left_label": "Daal",
                "left": f"+{owner_count(daal['qty'])} kg",
                "left_attr": _attr(daal["qty"]),
                "right_label": "",
                "right": "",
                "right_attr": "",
            }
        )
    if not pairs:
        return None
    return {
        "kind": "recipe",
        "severity": "amber",
        "kicker": "Recipe over-deducts",
        "title": "Coconut, sambar and daal",
        "detail": (
            "Stores book the surplus back as a stock-count gain, "
            "so this is an accounting effect, not missing stock."
        ),
        "action": "Correct the recipe quantities in Restroworks. Sailesh.",
        "pairs": pairs,
        "items": f"{_COCONUT} {_DAAL} {' '.join(_SAMBAR)}",
    }


def _sambar_info(owner_count):
    sold, litres, each = _addon_sales()
    if sold is None or litres is None or each is None:
        return None
    return {
        "kind": "info",
        "severity": "",
        "kicker": "Info",
        "title": "Free Regular Sambar",
        "detail": f"The free add-on is {format_qty(each)} L a portion, both cities, for this period.",
        "action": "",
        "pairs": [
            {
                "left_label": "Sold",
                "left": owner_count(sold),
                "left_attr": _attr(sold),
                "right_label": "Sambar in the add-on",
                "right": f"{owner_count(litres)} L",
                "right_attr": _attr(litres),
            }
        ],
        "items": "Regular Sambar",
    }


def _receive_alert(rows, city, owner_rupee):
    if city and city != "Delhi NCR":
        return None
    picked = [row for row in rows if row.get("store") == "Connaught Place"]
    if not picked:
        return None
    total = 0.0
    priced = False
    for row in picked:
        received, issued = row.get("received"), row.get("issued")
        price = row.get("price")
        if received is None or issued is None or price is None:
            continue
        total += (received - issued) * price
        priced = True
    if not priced:
        return None
    return {
        "kind": "receive",
        "severity": "amber",
        "kicker": "Connaught Place",
        "title": "Received more than the kitchen sent",
        "detail": "Connaught Place booked more batch items as received than the kitchen sent.",
        "action": "Check with Sanjoy.",
        "pairs": [
            {
                "left_label": "Received above sent",
                "left": owner_rupee(total),
                "left_attr": _attr(total),
                "right_label": "Store",
                "right": "Connaught Place",
                "right_attr": "",
            }
        ],
        "items": "Connaught Place",
    }


def _name_alert(rows):
    names = {row["item"].casefold() for row in rows}
    lines = []
    if _has_pair(names, _NAME_PAIRS[0]):
        lines.append("Medu Vada Batter and Medu Vada Batter Mix are booked as different items.")
    if _has_pair(names, _NAME_PAIRS[1]):
        lines.append("Malabar Paratha Dough and the paratha packet are booked as different items.")
    if not lines:
        return None
    return {
        "kind": "names",
        "severity": "amber",
        "kicker": "Names",
        "title": "Batter and dough names do not match",
        "detail": " ".join(lines),
        "action": "Sailesh and Shanker.",
        "pairs": [],
        "items": "Medu Vada Batter Malabar Paratha Dough",
    }


def _has_pair(names, pair):
    left, right = pair
    return left.casefold() in names and right.casefold() in names


def _gain(rows, names):
    picked = [row for row in rows if row["item"] in names]
    return {
        "qty": sum_present(row["gain_qty"] for row in picked),
        "amt": sum_present(row["gain_amt"] for row in picked),
    }


def _present_row(row, owner_count, owner_rupee):
    unit = _unit_label(row.get("unit"))
    gain = row.get("gain_qty")
    gain_text = ""
    if gain is not None:
        sign = "+" if gain > 0 else ""
        gain_text = f"{sign}{format_qty(gain)} {unit}".strip()
    return {
        "store": row["store"],
        "item": row["item"],
        "period": row.get("period") or "",
        "verdict": row.get("verdict") or "",
        "threat": row.get("verdict") == "Physical loss",
        "expected": _qty_text(row.get("expected"), unit),
        "expected_missing": row.get("expected") is None,
        "used": _qty_text(row.get("used"), unit),
        "used_missing": row.get("used") is None,
        "sent": _qty_text(row.get("issued"), unit),
        "issued_missing": row.get("issued") is None,
        "gain": gain_text,
        "gain_missing": gain is None,
        "gain_rupee": owner_rupee(row["gain_amt"]) if row.get("gain_amt") is not None else "",
        "pct_attr": _attr(row.get("gain_qty")),
    }


def _sort_key(row):
    verdict = row.get("verdict") or ""
    rank = {
        "Physical loss": 0,
        "Recipe over-deducts": 1,
        "Unresolved": 2,
        "Consistent": 3,
        "Insufficient data": 4,
    }.get(verdict, 5)
    focus = 0 if row["item"] in {_JAIN, _DOSA, _BENNE, _COCONUT, _DAAL, *_SAMBAR} else 1
    return (rank, focus, row["item"].casefold(), row["store"].casefold())


def _alert_matches(alert, query):
    blob = " ".join(
        [
            alert.get("title") or "",
            alert.get("detail") or "",
            alert.get("items") or "",
            alert.get("kicker") or "",
        ]
    ).casefold()
    return query in blob


def _read_comparison(path, cities):
    from app.menu_costing.batches import _short_store, _store_index

    places = _store_index()
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            store = (raw.get("store") or "").strip()
            item = (raw.get("batch_item") or "").strip()
            if not store or not item:
                continue
            place = places.get(store.casefold()) or places.get(_short_store(store))
            city = ""
            store_id = ""
            if place:
                city = place["city"]
                store_id = place["store_id"]
            if not city:
                city = cities.get(store.casefold(), "")
            gain_qty = parse_number(raw.get("physical_gain_loss_qty"))
            gain_amt = parse_number(raw.get("physical_gain_loss_amt"))
            price = None
            if gain_qty not in (None, 0) and gain_amt is not None:
                price = gain_amt / gain_qty
            rows.append(
                {
                    "store": store,
                    "store_id": store_id,
                    "city": city,
                    "item": item,
                    "key": item.casefold(),
                    "unit": (raw.get("unit") or "").strip(),
                    "expected": parse_number(raw.get("theoretical_qty")),
                    "used": parse_number(raw.get("store_used_qty")),
                    "issued": parse_number(raw.get("issued_qty")),
                    "received": parse_number(raw.get("store_received_qty")),
                    "gain_qty": gain_qty,
                    "gain_amt": gain_amt,
                    "price": price,
                    "verdict": _verdict_label(raw.get("verdict") or ""),
                }
            )
    return rows


def _verdict_label(text):
    low = " ".join((text or "").casefold().split())
    if low.startswith("physical loss"):
        return "Physical loss"
    if low.startswith("recipe over-deducts"):
        return "Recipe over-deducts"
    if "broadly consistent" in low:
        return "Consistent"
    if low.startswith("insufficient"):
        return "Insufficient data"
    if "unresolved" in low:
        return "Unresolved"
    return ""


def _kitchens(path, label, start, end):
    if not path.is_file():
        return []
    found = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            store = (raw.get("store") or "").strip()
            if not store.casefold().startswith("central kitchen"):
                continue
            if parse_number(raw.get("made_qty")) is None:
                continue
            if "delhi" in store.casefold():
                found.add(("Delhi NCR", "Delhi kitchen"))
            elif "kolkata" in store.casefold():
                found.add(("Kolkata", "Kolkata kitchen"))
    order = {"Kolkata": 0, "Delhi NCR": 1}
    kitchens = [
        {"city": city, "name": name, "period": label, "start": start, "end": end}
        for city, name in sorted(found, key=lambda pair: (order.get(pair[0], 9), pair[1]))
    ]
    return kitchens


def _city_index(posist):
    path = Path(posist) / "batch_store_map.csv"
    found = {}
    if not path.is_file():
        return found
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            city = (raw.get("city") or "").strip()
            for column in ("restroworks_store", "recipe_outlet", "posist_store"):
                label = (raw.get(column) or "").strip()
                if label and city:
                    found[label.casefold()] = city
    return found


def _period_from(*paths):
    for path in paths:
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                period = (raw.get("period") or "").strip()
                if period:
                    return period
    return ""


def _bounds(period):
    from app.menu_costing.batches import _period_bounds

    return _period_bounds(period)


def _addon_sales():
    """Regular Sambar portions in the batch window, times the recipe litres."""
    sales_path = _sales_path()
    if sales_path is None:
        return None, None, None
    each = _sambar_litres()
    if each is None:
        return None, None, None
    start, end = _bounds(_period_from(
        Path(__file__).resolve().parents[2] / "data" / "procurement" / "batch_actual_use.csv"
    ))
    if start is None or end is None:
        return None, None, None
    column = f"qty_{start.strftime('%m-%d')}_{end.strftime('%m-%d')}"
    sold = 0.0
    seen = False
    with sales_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if column not in (reader.fieldnames or []):
            return None, None, None
        for raw in reader:
            if (raw.get("item") or "").strip().casefold() != "regular sambar":
                continue
            qty = parse_number(raw.get(column))
            if qty is None:
                continue
            seen = True
            sold += qty
    if not seen:
        return None, None, None
    return sold, sold * each, each


def _sales_path():
    folder = Path(__file__).resolve().parents[2] / "data" / "menu"
    matches = sorted(folder.glob("item_sales_*.csv"))
    return matches[-1] if matches else None


_SAMBAR_LITRES = {}


def _sambar_litres():
    """Litres of sambar in one Regular Sambar portion.

    The cost-line file is large. The result is cached by file identity so a
    page view does not read it again.
    """
    path = Path(__file__).resolve().parents[2] / "data" / "procurement" / "menu_item_cost_lines.csv"
    if not path.is_file():
        return None
    st = path.stat()
    token = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    if token in _SAMBAR_LITRES:
        return _SAMBAR_LITRES[token]
    qtys = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            if (raw.get("recipe_tab") or "base").strip().casefold() not in {"", "base"}:
                continue
            item = (raw.get("item_name") or "").strip().casefold()
            if not item.startswith("regular sambar"):
                continue
            ingredient = (raw.get("ingredient_name") or "").strip().casefold()
            if "sambar" not in ingredient or "bucket" not in ingredient:
                continue
            qty = parse_number(raw.get("ingredient_qty"))
            unit = (raw.get("ingredient_unit") or "").strip().casefold()
            if qty is None or unit not in {"ltr", "l", "lt", "litre", "liter"}:
                continue
            qtys.add(qty)
    result = qtys.pop() if len(qtys) == 1 else None
    _SAMBAR_LITRES[token] = result
    return result


def _unit_label(unit):
    key = (unit or "").strip().casefold()
    if key in {"ltr", "l", "lt", "litre", "liter", "litres", "liters"}:
        return "L"
    if key in {"kg", "kgs"}:
        return "kg"
    return (unit or "").strip()


def _qty_text(qty, unit):
    if qty is None:
        return ""
    return f"{format_qty(qty)} {unit}".strip()


def _attr(value):
    return num_attr(value)
