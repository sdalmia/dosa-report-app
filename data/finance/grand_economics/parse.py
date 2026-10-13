"""Read the Kolkata and NCR workbooks into one tidy table, then the page files.

A month is kept only when gross revenue is a real number other than zero.
A blank cell stays out of the table. It is not written as zero.
Staff salary, CAM, gas, and ads accept the row names the sheets actually use.
Ads are the city total, not split across stores.
"""

import csv
import datetime
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

SOURCES = (
    ("kolkata_fy26_27.xlsx", "Kolkata", "FY26-27"),
    ("ncr_fy26_27.xlsx", "NCR", "FY26-27"),
    ("kolkata_fy25_26.xlsx", "Kolkata", "FY25-26"),
    ("ncr_fy25_26.xlsx", "NCR", "FY25-26"),
)

SKIP_SHEETS = {
    "Summary",
    "HO",
    "Misc Exp",
    "Misc Expenses",
    "Notes",
    "Cost Factors",
    "CK",
    "Central Kitchen - Kolkata",
    "Salary Reco",
    "Event Sales",
    "Chattarpur",
    "GK1 Cloud Kitchen",
}

# Sheet title, after letters and digits only, that is closing and gets no advice.
CLOSING = {
    "faridabadsec15": "Closing 20 Oct",
}

MONTH_NAMES = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

LINE_LABELS = {
    "ebitda": "EBITDA",
    "ebitda-pct": "EBITDA",
    "food-cost-pct": "Food cost",
    "rent-pct": "Rent of net",
    "salary-pct": "Salary of net",
    "ads": "Ads",
}


def canonical_line(label):
    """Map a sheet row name to a tidy line. Unknown rows are ignored."""
    text = str(label or "").replace(":", " ").replace("&", " and ")
    text = " ".join(text.split()).lower()
    exact = {
        "gross revenue": "gross_revenue",
        "less tax": "tax",
        "less commission": "commission",
        "net revenues from f and b sales": "net_revenue",
        "f and b cost": "fnb_cost",
        "electricity": "electricity",
        "gas": "gas",
        "lpg": "gas",
        "cooking gas": "gas",
        "gas charges": "gas",
        "rent and revenue share": "rent",
        "staff salary": "salary",
        "staff salary and bonus": "salary",
        "staff salaries": "salary",
        "cam": "cam",
        "cam charges": "cam",
        "common area maintenance": "cam",
        "c a m": "cam",
        "ads": "ads",
        "advertisement": "ads",
        "advertisement and promotion": "ads",
        "advertisements": "ads",
        "ho and ck cost": "ho_ck_cost",
        "store level ebitda": "ebitda",
    }
    if text in exact:
        return exact[text]
    if text.startswith("staff salary"):
        return "salary"
    return None


def as_number(value):
    """A real number, or None. Blank, text, and sheet errors are None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("₹", "").replace("%", "")
        if not text or text.startswith("#"):
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _slug(text):
    lowered = str(text or "").lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


def _letters(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def _month_header(rows):
    for row in rows:
        if len(row) > 1 and isinstance(row[1], datetime.datetime):
            return row
    return None


def _months(header):
    found = []
    for cell in header[1:13]:
        if isinstance(cell, datetime.datetime):
            found.append(cell.strftime("%Y-%m"))
        else:
            found.append(None)
    return found


def _line_values(rows):
    data = {}
    for row in rows:
        if not row or not isinstance(row[0], str):
            continue
        key = canonical_line(row[0])
        if key and key not in data:
            data[key] = list(row[1:13])
    return data


def _ads_total(rows):
    for row in rows:
        if row and isinstance(row[0], str) and row[0].strip().lower() == "total":
            return list(row[1:13])
    return None


def read_workbook(path, city, fy):
    import openpyxl

    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    store_rows = []
    ads_values = None
    ads_months = None
    notes = []
    for sheet in book.worksheets:
        rows = list(sheet.iter_rows(max_row=80, max_col=14, values_only=True))
        if sheet.title == "Ads Account":
            header = _month_header(rows)
            if header is None:
                notes.append(f"{path.name}:{sheet.title}: no month header")
                continue
            ads_months = _months(header)
            ads_values = _ads_total(rows)
            continue
        if sheet.title in SKIP_SHEETS:
            continue
        header = _month_header(rows)
        if header is None:
            notes.append(f"{path.name}:{sheet.title}: no month header")
            continue
        months = _months(header)
        lines = _line_values(rows)
        gross = lines.get("gross_revenue") or [None] * 12
        store = sheet.title.strip()
        for index, month in enumerate(months):
            if not month:
                continue
            amount = as_number(gross[index] if index < len(gross) else None)
            if amount is None or amount == 0:
                continue
            for line, cells in lines.items():
                value = as_number(cells[index] if index < len(cells) else None)
                if value is None:
                    continue
                store_rows.append((fy, city, store, month, line, round(value, 2)))
    return store_rows, ads_months, ads_values, notes


def tidy_rows(source):
    """Every kept cell from the four workbooks, including city ads."""
    source = Path(source)
    rows = []
    notes = []
    filled = defaultdict(set)
    for filename, city, fy in SOURCES:
        path = source / filename
        store_rows, ads_months, ads_values, sheet_notes = read_workbook(path, city, fy)
        notes.extend(sheet_notes)
        rows.extend(store_rows)
        for fy_name, row_city, _store, month, line, _value in store_rows:
            if line == "gross_revenue":
                filled[(fy_name, row_city)].add(month)
        if not ads_months or not ads_values:
            continue
        for index, month in enumerate(ads_months):
            if not month or month not in filled[(fy, city)]:
                continue
            value = as_number(ads_values[index] if index < len(ads_values) else None)
            if value is None:
                continue
            rows.append((fy, city, "", month, "ads", round(value, 2)))
    return rows, notes


def _month_label(month):
    year, raw = month.split("-")
    return f"{MONTH_NAMES[int(raw) - 1]} {year}"


def _span_label(months):
    first, last = months[0], months[-1]
    fy, fm = first.split("-")
    ly, lm = last.split("-")
    start = MONTH_NAMES[int(fm) - 1]
    end = MONTH_NAMES[int(lm) - 1]
    if fy == ly and fm == lm:
        return f"{start} {fy}"
    if fy == ly:
        return f"{start}–{end} {fy}"
    return f"{start} {fy}–{end} {ly}"


def _fmt_rupee(value):
    if value is None:
        return "not yet in"
    number = float(value)
    if number == 0:
        return "₹0"
    sign = "-" if number < 0 else ""
    amount = abs(number)
    if amount >= 10_000_000:
        body = f"{amount / 10_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{sign}₹{body}Cr"
    if amount >= 100_000:
        body = f"{amount / 100_000:.1f}".rstrip("0").rstrip(".")
        return f"{sign}₹{body}L"
    digits = str(int(round(amount)))
    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while head:
            parts.append(head[-2:])
            head = head[:-2]
        grouped = ",".join(reversed(parts)) + "," + tail
    return f"{sign}₹{grouped}"


def _fmt_pct(value):
    if value is None:
        return "not yet in"
    text = f"{float(value):.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text}%"


def _trim_number(value):
    text = f"{abs(float(value)):.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _points_change(current, previous, previous_label):
    if current is None:
        return "not yet in"
    if previous is None:
        return "Last year is not in."
    delta = current - previous
    if abs(delta) < 0.05:
        return f"Same as {previous_label}"
    word = "over" if delta > 0 else "under"
    return f"{_trim_number(delta)} points {word} {previous_label}"


def _rupee_change(current, previous, previous_label):
    if current is None:
        return "not yet in"
    if previous is None:
        return "Last year is not in."
    if previous == 0:
        return f"{previous_label} was {_fmt_rupee(previous)}"
    delta = (current - previous) / abs(previous) * 100
    if abs(delta) < 0.05:
        return f"Same as {previous_label}"
    word = "over" if delta > 0 else "under"
    return f"{_trim_number(delta)}% {word} {previous_label}"


def _prior_month(month):
    year, raw = month.split("-")
    return f"{int(year) - 1}-{raw}"


def _pct(part, whole):
    if part is None or whole is None or whole == 0:
        return None
    return part / whole * 100.0


def _spark(points):
    """Inline sparkline. Missing months break the line. They are not drawn as zero."""
    usable = [(index, value) for index, value in enumerate(points) if value is not None]
    if len(usable) < 2:
        return ""
    width, height, pad = 280, 48, 4
    values = [value for _index, value in usable]
    low, high = min(values), max(values)
    span = high - low or 1
    last_index = max(len(points) - 1, 1)

    def xpos(index):
        return pad + (width - 2 * pad) * (index / last_index)

    def ypos(value):
        return pad + (height - 2 * pad) * (1 - (value - low) / span)

    commands = []
    drawing = False
    for index, value in enumerate(points):
        if value is None:
            drawing = False
            continue
        command = "L" if drawing else "M"
        commands.append(f"{command}{xpos(index):.1f},{ypos(value):.1f}")
        drawing = True
    last = usable[-1]
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Monthly trend">'
        f'<path d="{" ".join(commands)}" fill="none" stroke="currentColor" stroke-width="2"/>'
        f'<circle cx="{xpos(last[0]):.1f}" cy="{ypos(last[1]):.1f}" r="3" fill="currentColor"/>'
        "</svg>"
    )


def _index_rows(rows):
    table = defaultdict(dict)
    for fy, city, store, month, line, value in rows:
        table[(fy, city, store, month)][line] = value
    return table


def _store_metric(cells, kind):
    if kind == "ebitda":
        return cells.get("ebitda")
    if kind == "ebitda-pct":
        return _pct(cells.get("ebitda"), cells.get("net_revenue"))
    if kind == "food-cost-pct":
        return _pct(cells.get("fnb_cost"), cells.get("net_revenue"))
    if kind == "rent-pct":
        return _pct(cells.get("rent"), cells.get("net_revenue"))
    if kind == "salary-pct":
        return _pct(cells.get("salary"), cells.get("net_revenue"))
    if kind == "ads":
        return cells.get("ads")
    return None


def _format_metric(kind, value):
    if value is None:
        return "not yet in"
    if kind in {"ebitda", "ads"}:
        return _fmt_rupee(value)
    return _fmt_pct(value)


def _change(kind, current, previous, previous_label):
    if kind in {"ebitda", "ads"}:
        return _rupee_change(current, previous, previous_label)
    return _points_change(current, previous, previous_label)


def build_views(rows):
    """Threats, cards, the store list, and one record per clickable figure."""
    table = _index_rows(rows)
    stores = defaultdict(set)
    months_by_city = defaultdict(set)
    for (fy, city, store, month), cells in table.items():
        if store and "gross_revenue" in cells:
            stores[(fy, city)].add(store)
            if fy == "FY26-27":
                months_by_city[city].add(month)
    latest = {city: max(months) for city, months in months_by_city.items()}
    coverage = []
    for city in ("Kolkata", "NCR"):
        months = sorted(months_by_city.get(city) or [])
        if not months:
            coverage.append(f"{city} is not yet in.")
            continue
        coverage.append(
            f"{city} is in for {_span_label(months)}. Later months are not yet in."
        )

    store_names = sorted(
        {store for (_fy, _city, store, _month) in table if store},
        key=str.casefold,
    )
    city_of = {}
    for store in store_names:
        for city in ("Kolkata", "NCR"):
            if store in stores.get(("FY26-27", city), ()):
                city_of[store] = city
                break

    def cells_for(city, store, month):
        fy = "FY26-27" if month >= "2026-04" else "FY25-26"
        return table.get((fy, city, store, month), {})

    def city_cells(city, month):
        names = stores.get(("FY26-27" if month >= "2026-04" else "FY25-26", city), ())
        if month < "2026-04":
            names = stores.get(("FY25-26", city), names)
        totals = defaultdict(float)
        counts = defaultdict(int)
        for store in names:
            cells = cells_for(city, store, month)
            for line in ("ebitda", "net_revenue", "fnb_cost", "rent", "salary"):
                value = cells.get(line)
                if value is None:
                    continue
                if line != "net_revenue" and cells.get("net_revenue") is None:
                    continue
                if line == "net_revenue" or cells.get("net_revenue") is not None:
                    totals[line] += value
                    counts[line] += 1
        ads = table.get(
            ("FY26-27" if month >= "2026-04" else "FY25-26", city, "", month),
            {},
        ).get("ads")
        return totals, counts, ads

    def city_metric(city, month, kind):
        if kind == "ads":
            _totals, _counts, ads = city_cells(city, month)
            return ads
        totals, counts, _ads = city_cells(city, month)
        if kind == "ebitda":
            return totals.get("ebitda") if counts.get("ebitda") else None
        pair = {
            "ebitda-pct": "ebitda",
            "food-cost-pct": "fnb_cost",
            "rent-pct": "rent",
            "salary-pct": "salary",
        }[kind]
        if not counts.get(pair) or not totals.get("net_revenue"):
            return None
        return _pct(totals.get(pair), totals.get("net_revenue"))

    all_months = sorted({month for (_fy, _city, _store, month) in table})
    details = {}
    threats = []
    cards = []

    def add_detail(anchor, title_store, city, store, kind, month, series, peers, peer_note):
        previous_month = _prior_month(month)
        current = series.get(month)
        previous = series.get(previous_month)
        previous_label = _month_label(previous_month)
        tag = CLOSING.get(_letters(store), "")
        details[anchor] = {
            "id": anchor,
            "title": title_store,
            "line": LINE_LABELS[kind],
            "month": _month_label(month),
            "month_key": month,
            "value": _format_metric(kind, current),
            "tag": tag,
            "last_year_label": previous_label,
            "last_year": _format_metric(kind, previous) if previous is not None else "Last year is not in.",
            "change": _change(kind, current, previous, previous_label),
            "peer_note": peer_note,
            "peers": peers,
            "spark": _spark([series.get(item) for item in all_months]),
            "trend_caption": "Months left off the line are not yet in.",
            "city": city,
            "store": store,
        }

    kinds = ("ebitda", "ebitda-pct", "food-cost-pct", "rent-pct", "salary-pct")
    for city in ("Kolkata", "NCR"):
        month = latest.get(city)
        if not month:
            continue
        month_label = _month_label(month)
        for store in sorted(stores.get(("FY26-27", city), ()), key=str.casefold):
            series = {}
            for kind in kinds:
                series[kind] = {}
                for item in all_months:
                    series[kind][item] = _store_metric(cells_for(city, store, item), kind)
            ebitda = series["ebitda"].get(month)
            if ebitda is not None and ebitda < 0:
                anchor = f"{_slug(store)}-ebitda-{month}"
                threats.append({
                    "id": anchor,
                    "store": store,
                    "city": city,
                    "month": month_label,
                    "value": _fmt_rupee(ebitda),
                    "pct": _fmt_pct(series["ebitda-pct"].get(month)),
                    "tag": CLOSING.get(_letters(store), ""),
                    "sort": ebitda,
                })
            for kind in kinds:
                anchor = f"{_slug(store)}-{kind}-{month}"
                peers = []
                for other in sorted(stores.get(("FY26-27", city), ()), key=str.casefold):
                    value = _store_metric(cells_for(city, other, month), kind)
                    peers.append({
                        "name": other,
                        "value": _format_metric(kind, value),
                        "sort": value,
                        "current": other == store,
                    })
                reverse = kind in {"food-cost-pct", "rent-pct", "salary-pct"}
                peers.sort(key=lambda item: (item["sort"] is None, -(item["sort"] or 0) if reverse else (item["sort"] if item["sort"] is not None else 10**12)))
                for peer in peers:
                    peer.pop("sort", None)
                note = f"{city} stores in {month_label}"
                if kind == "food-cost-pct":
                    note = f"Food cost is compared within {city} only."
                add_detail(anchor, store, city, store, kind, month, series[kind], peers, note)

        city_series = {kind: {} for kind in kinds + ("ads",)}
        for item in all_months:
            for kind in city_series:
                city_series[kind][item] = city_metric(city, item, kind)
        card_kinds = ("ebitda-pct", "food-cost-pct", "rent-pct", "salary-pct", "ads")
        for kind in card_kinds:
            anchor = f"{_slug(city)}-{kind}-{month}"
            current = city_series[kind].get(month)
            previous = city_series[kind].get(_prior_month(month))
            note = _change(kind, current, previous, _month_label(_prior_month(month)))
            if kind == "food-cost-pct":
                note = f"Within {city} only. {note}"
            if kind == "ads":
                note = "City total. " + note
            cards.append({
                "id": anchor,
                "kicker": f"{city} · {month_label}",
                "value": _format_metric(kind, current),
                "label": LINE_LABELS[kind],
                "note": note,
            })
            if kind == "ads":
                peers = []
                for other in ("Kolkata", "NCR"):
                    peers.append({
                        "name": other,
                        "value": _format_metric(kind, city_metric(other, month, kind)),
                        "current": other == city,
                    })
                peer_note = "City total, not a store."
            else:
                peers = []
                for store in sorted(stores.get(("FY26-27", city), ()), key=str.casefold):
                    value = _store_metric(cells_for(city, store, month), kind)
                    peers.append({
                        "name": store,
                        "value": _format_metric(kind, value),
                        "sort": value,
                        "current": False,
                    })
                reverse = kind in {"food-cost-pct", "rent-pct", "salary-pct"}
                peers.sort(key=lambda item: (item["sort"] is None, -(item["sort"] or 0) if reverse else (item["sort"] if item["sort"] is not None else 10**12)))
                for peer in peers:
                    peer.pop("sort", None)
                peer_note = f"{city} stores in {month_label}"
                if kind == "food-cost-pct":
                    peer_note = f"Food cost is compared within {city} only."
            add_detail(anchor, city, city, "", kind, month, city_series[kind], peers, peer_note)

    threats.sort(key=lambda item: (item["city"], item["sort"], item["store"].casefold()))
    for item in threats:
        item.pop("sort", None)

    grouped = []
    for city in ("Kolkata", "NCR"):
        month = latest.get(city)
        if not month:
            continue
        entries = []
        for store in sorted(stores.get(("FY26-27", city), ()), key=str.casefold):
            figs = []
            for kind in kinds:
                anchor = f"{_slug(store)}-{kind}-{month}"
                panel = details[anchor]
                figs.append({
                    "id": anchor,
                    "label": LINE_LABELS[kind],
                    "value": panel["value"],
                    "note": panel["change"] if kind == "ebitda-pct" else "",
                })
            entries.append({
                "name": store,
                "tag": CLOSING.get(_letters(store), ""),
                "figs": figs,
            })
        grouped.append({"name": city, "month": _month_label(month), "stores": entries})

    summary = {"coverage": coverage, "threats": threats, "cards": cards}
    store_view = {"cities": grouped}
    return summary, store_view, details


def write_outputs(rows, dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "grand_economics_tidy.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["fy", "city", "store", "month", "line", "value"])
        writer.writerows(rows)
    summary, store_view, details = build_views(rows)
    for name, payload in (
        ("summary.json", summary),
        ("stores.json", store_view),
        ("details.json", details),
    ):
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        (dest / name).write_text(text, encoding="utf-8")
    return summary


def main(source=None, dest=None):
    source = Path(source or HERE)
    dest = Path(dest or source)
    rows, notes = tidy_rows(source)
    summary = write_outputs(rows, dest)
    print(len(rows))
    if notes:
        print("\n".join(notes))
    for line in summary["coverage"]:
        print(line)
    print("threats", len(summary["threats"]))
    print("cards", len(summary["cards"]))
    return rows


if __name__ == "__main__":
    main()
