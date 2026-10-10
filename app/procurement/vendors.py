"""Vendor panel from GRN lines and the supplier rate files.

Short delivery stays empty until a purchase-order versus GRN file exists.
Indent stock-out is warehouse-to-store dispatch, not a supplier short delivery.
"""

from app.procurement.loader import source_name
from app.procurement.numbers import (
    format_period,
    format_qty,
    format_whole,
    money_pair,
    pct_pair,
    percent,
    sum_present,
)

SHORT_DELIVERY_MESSAGE = (
    "Short deliveries cannot be computed. "
    "The ordered quantity is blank on every Restroworks receipt."
)

MOVE_THRESHOLD = 10.0


def build_vendors(bundle, selected_item=None):
    start, end = _grn_bounds(bundle)
    names = _item_names(bundle)
    moves = _time_moves(bundle)
    moved_names = {row["item"] for row in moves}
    chosen = _choose_item(selected_item, names, moved_names)
    above = _above_cheapest(bundle)
    return {
        "period_label": format_period(start, end) or "Period not on file",
        "period_note": _period_note(start, end),
        "suppliers": _suppliers(bundle),
        "item_names": [{"name": name, "moved": name in moved_names} for name in names],
        "selected_item": chosen,
        "price_rows": _price_rows(bundle, chosen),
        "rate_rows": _rate_rows(bundle, chosen),
        "time_moves": moves,
        "above_cheapest": above,
        "largest_gap": above[0] if above else None,
        "short_delivery": _short_delivery(),
        "po_coverage": _po_coverage(bundle),
        "reconciliation": _reconciliation(bundle),
        "missing_grn": "" if bundle["files"].get("grn_lines") else "Goods received are not on file.",
        "missing_rates": "" if bundle["files"].get("supplier_rates") else "Supplier rates are not on file.",
        "missing_summary": "" if bundle["files"].get("supplier_summary") else "Supplier spend is not on file.",
        "page_help": _period_note(start, end),
    }


def _grn_bounds(bundle):
    dates = [row["date"] for row in bundle["grn_lines"] if row.get("date")]
    if not dates:
        return bundle.get("period_start"), bundle.get("period_end")
    return min(dates), max(dates)


def _period_note(start, end):
    label = format_period(start, end)
    if not label:
        return "Supplier rates follow the dates on the goods received."
    return (
        f"Rates and supplier spend cover {label}. "
        "A single unusual receipt can make a gap look large."
    )


def _item_names(bundle):
    names = {row.get("item_name") for row in bundle["grn_lines"] if row.get("item_name")}
    return sorted(names, key=str.casefold)


def _choose_item(selected, names, moved_names):
    if selected and selected in names:
        return selected
    for name in sorted(moved_names, key=str.casefold):
        if name in names:
            return name
    return names[0] if names else ""


def _price_rows(bundle, item):
    if not item:
        return []
    rows = []
    for row in bundle["grn_lines"]:
        if row.get("item_name") != item:
            continue
        rows.append(
            {
                "date": row["date"].isoformat() if row.get("date") else "",
                "date_text": format_period(row.get("date"), row.get("date")),
                "city": row.get("city") or "",
                "supplier": row.get("supplier") or "",
                "qty_text": format_qty(row.get("qty")),
                "unit": row.get("unit") or "",
                "rate": money_pair(row.get("unit_price")),
                "total": money_pair(row.get("total")),
                "se_number": row.get("se_number") or "",
            }
        )
    rows.sort(key=lambda row: (row["date"], row["city"], row["supplier"], row["se_number"]))
    return rows


def _rate_rows(bundle, item):
    rows = []
    for row in bundle["supplier_rates"]:
        if row.get("item_name") != item:
            continue
        rows.append(_rate_record(row))
    rows.sort(key=lambda row: (row["city"], row["supplier"]))
    return rows


def _rate_record(row):
    return {
        "item": row.get("item_name") or "",
        "unit": row.get("unit") or "",
        "city": row.get("city") or "",
        "supplier": row.get("supplier") or "",
        "lines": format_whole(row.get("lines")),
        "qty_text": format_qty(row.get("qty")),
        "wavg": money_pair(row.get("wavg_rate")),
        "min_rate": money_pair(row.get("min_rate")),
        "max_rate": money_pair(row.get("max_rate")),
        "last_rate": money_pair(row.get("last_rate")),
        "last_date": row["last_date"].isoformat() if row.get("last_date") else "",
        "pct_vs_wavg": pct_pair(row.get("pct_vs_item_wavg_all")),
        "pct_vs_cheapest": pct_pair(row.get("pct_vs_cheapest_supplier")),
        "n_suppliers": format_whole(row.get("n_suppliers_for_item")),
    }


def _time_moves(bundle):
    moves = []
    for row in bundle["supplier_rates"]:
        low = row.get("min_rate")
        high = row.get("max_rate")
        if low is None or high is None or low == 0:
            continue
        if (row.get("lines") or 0) < 2:
            continue
        move = percent(high - low, low)
        if move is None or move <= MOVE_THRESHOLD:
            continue
        record = _rate_record(row)
        record["move"] = pct_pair(move)
        moves.append(record)
    moves.sort(key=lambda row: -(row["move"]["value"] or 0))
    return moves


def _above_cheapest(bundle):
    """Gap versus the cheapest supplier in the same city.

    The rate file also compares a city with the other city's cheapest supplier.
    That cross-city gap is not shown.
    """
    groups = {}
    for row in bundle["supplier_rates"]:
        key = (row.get("item_name") or "", row.get("unit") or "", row.get("city") or "")
        groups.setdefault(key, []).append(row)
    rows = []
    for group in groups.values():
        rates = [row.get("wavg_rate") for row in group if row.get("wavg_rate") is not None]
        if not rates:
            continue
        cheapest = min(rates)
        for row in group:
            rate = row.get("wavg_rate")
            if rate is None or not cheapest:
                continue
            gap = percent(rate - cheapest, cheapest)
            if gap is None or gap <= MOVE_THRESHOLD:
                continue
            record = _rate_record(row)
            record["pct_vs_cheapest"] = pct_pair(gap)
            record["n_suppliers"] = format_whole(len(group))
            rows.append(record)
    rows.sort(key=lambda row: -(row["pct_vs_cheapest"]["value"] or 0))
    return rows


def _suppliers(bundle):
    rows = []
    for row in bundle["supplier_summary"]:
        rows.append(
            {
                "city": row.get("city") or "",
                "supplier": row.get("supplier") or "",
                "lines": format_whole(row.get("lines")),
                "items": format_whole(row.get("distinct_items")),
                "bills": format_whole(row.get("bills")),
                "total": money_pair(row.get("total_value")),
                "share": pct_pair(row.get("share_of_city_spend_pct")),
                "first_date": row["first_date"].isoformat() if row.get("first_date") else "",
                "last_date": row["last_date"].isoformat() if row.get("last_date") else "",
                "first_text": format_period(row.get("first_date"), row.get("first_date")),
                "last_text": format_period(row.get("last_date"), row.get("last_date")),
            }
        )
    rows.sort(key=lambda row: (row["city"] != "Kolkata", -(row["total"]["value"] or 0)))
    return rows


def _short_delivery():
    return {"available": False, "missing": SHORT_DELIVERY_MESSAGE}


def _po_coverage(bundle):
    rows = bundle.get("po_coverage") or []
    if not rows:
        return {
            "available": False,
            "missing": "Purchase orders are not on file, so short delivery cannot be checked.",
        }
    received = sum_present(row.get("received_value") for row in rows)
    return {
        "available": True,
        "missing": "",
        "suppliers": len(rows),
        "received": money_pair(received if rows else None),
        "note": (
            "The ordered quantity and the order number are blank on every receipt. "
            "That is not a short-delivery rate."
        ),
        "source": source_name(bundle, "po_coverage"),
        "period": rows[0].get("period") or "",
    }


def _reconciliation(bundle):
    summary = bundle.get("po_summary") or []
    bills = bundle.get("po_by_se") or []
    if not summary and not bills:
        return {
            "available": False,
            "missing": "Bill reconciliation is not on file.",
            "matched": None,
            "bills": None,
            "cities": [],
            "mismatches": [],
        }
    matched = sum(1 for row in bills if (row.get("status") or "") == "match")
    mismatches = []
    for row in bills:
        if (row.get("status") or "") == "match":
            continue
        mismatches.append(
            {
                "city": row.get("city") or "",
                "se_number": row.get("se_number") or "",
                "supplier": row.get("pd_supplier") or row.get("grn_supplier") or "",
                "status": row.get("status") or "",
                "pd_total": money_pair(row.get("pd_total")),
                "grn_total": money_pair(row.get("grn_total")),
                "diff": money_pair(row.get("diff_pd_total_minus_grn")),
                "date": row["pd_date"].isoformat() if row.get("pd_date") else "",
            }
        )
    cities = []
    for row in summary:
        cities.append(
            {
                "city": row.get("city") or "",
                "pd_lines": format_whole(row.get("pd_lines")),
                "grn_lines": format_whole(row.get("grn_lines")),
                "pd_total": money_pair(row.get("pd_total")),
                "grn_total": money_pair(row.get("grn_total")),
                "diff": money_pair(row.get("diff_pd_total_minus_grn")),
                "discount": money_pair(row.get("pd_discount")),
            }
        )
    return {
        "available": True,
        "missing": "",
        "matched": matched,
        "bills": len(bills),
        "cities": cities,
        "mismatches": mismatches,
        "source": source_name(bundle, "po_summary"),
        "bill_source": source_name(bundle, "po_by_se"),
    }
