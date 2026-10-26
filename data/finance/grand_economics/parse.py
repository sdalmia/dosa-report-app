"""Read the Kolkata and NCR workbooks into one tidy table, then the page files.

Tidy columns: fy, city, store, month, line, value, level
  level "city"    store ""                   taken straight from the city Summary sheet
  level "store"   store = sheet name          one row per store sheet
  level "events"  store "Event Sales"         Kolkata event sales sheet, not a store
  level "central" store CENTRAL               city total minus stores and events, per line
                                              (ads, kitchen food not charged to a store)
stores + events + central = city for every line and month; the build stops if not.

A city month is kept when its Summary gross revenue is a real number other than zero.
A store month is kept inside those months when the store has revenue or EBITDA.
A blank cell stays out of the table. It is not written as zero (a real 0 in the sheet is kept).
Every row name in every sheet read is either mapped or listed in IGNORED_ROWS;
anything else is printed as "row not read" so a new sheet row is never lost quietly.
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
    "Chattarpur",
    "GK1 Cloud Kitchen",
}

# Sheet title, after letters and digits only, that is closing and gets no advice.
CLOSING = {
    "faridabadsec15": "Closing 20 Oct",
}

CENTRAL = "Kitchen & central"
EVENTS = "Event Sales"
NOT_STORES = {"", CENTRAL, EVENTS}

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
    "city-ebitda": "EBITDA after ads and kitchen",
}

# Row names that are headings, ratios, or repeats of another row. Not read on purpose.
IGNORED_ROWS = {
    "food cost calculation", "commission %", "ebitda margin %", "ebidta margin %",
    "food cost", "department", "p/l", "depriciation (2%) + interest (1%)",
}

# Plain names for the city bridge (city total minus stores), per tidy line.
BRIDGE_NAMES = {
    "ads": "Ads (city total, not split by store)",
    "fnb_cost": "Kitchen food not charged to any store",
    "net_revenue": "Revenue not in any store sheet",
}

# Ads Account rows, both years' layouts, used only to check the sheet's own total.
ADS_PARTS = {
    "team", "social media/digital media", "print media", "radio", "public relations",
    "influencers", "pop materials", "photo and video shoot", "website",
    "competitions and give aways", "reelo campaign", "misc. & others", "zomato", "swiggy",
    "social media & marketing expenses", "photo and video shoot expenses",
    "facebook expenses", "klarus tech", "reelo technologies", "others",
}


def canonical_line(label):
    """Map a sheet row name to a tidy line. Unknown rows are ignored."""
    text = str(label or "").replace(":", " ").replace("&", " and ").replace("+", " and ")
    text = " ".join(text.split()).lower()
    exact = {
        "opening stock": "opening_stock",
        "purchases food (less purchase return)": "purchases",
        "transferred out": "transferred_out",
        "wastage and date expired": "wastage",
        "closing stock": "closing_stock",
        "catering and fairs": "catering",
        "telephone/internet": "telephone",
        "software": "software",
        "amc": "amc",
        "subscription": "subscription",
        "insurance": "insurance",
        "insurance premium": "insurance",
        "repairs and maintenance": "repairs",
        "miscellaneous expenses": "misc",
        "staff incentives": "staff_incentives",
        "advertisement expenses": "ads",
        "ads account": "ads",
        "operating expenses": "opex_total",
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


def _line_values(rows, first=1, unread=None, where=""):
    data = {}
    for row in rows:
        if not row or not isinstance(row[0], str) or not row[0].strip():
            continue
        key = canonical_line(row[0])
        if key is None:
            text = " ".join(row[0].replace(":", " ").split()).lower()
            if text not in IGNORED_ROWS and not text.startswith("dosa coffee") and text != "f" and unread is not None:
                unread.append(f"row not read: {row[0]!r} in {where}")
            continue
        if key not in data:
            data[key] = list(row[first:first + 12])
    return data


def _ads_parts(rows, unread, where):
    """Sum of the Ads Account rows under the heading, per month (None where all blank)."""
    parts = [None] * 12
    for row in rows:
        if not row or not isinstance(row[0], str):
            continue
        text = " ".join(row[0].split()).lower().lstrip("- ").strip()
        if text in ("total", "advertisement & promotion") or text.startswith("dosa coffee"):
            continue
        if text not in ADS_PARTS:
            unread.append(f"row not read: {row[0]!r} in {where}")
            continue
        for index, cell in enumerate(row[1:13]):
            value = as_number(cell)
            if value is not None:
                parts[index] = (parts[index] or 0.0) + value
    return parts


def _ads_total(rows):
    for row in rows:
        if row and isinstance(row[0], str) and row[0].strip().lower() == "total":
            return list(row[1:13])
    return None


def read_workbook(path, city, fy):
    import openpyxl

    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    notes = []
    where = lambda title: f"{city} {fy} {title}"

    # 1. City Summary sheet: label in A, department in B, months from C.
    summary = list(book["Summary"].iter_rows(max_row=80, max_col=16, values_only=True))
    header = next((row for row in summary if len(row) > 2 and isinstance(row[2], datetime.datetime)), None)
    city_months = _months(header[1:]) if header else []
    city_lines = _line_values(summary, first=2, unread=notes, where=where("Summary"))
    gross = city_lines.get("gross_revenue") or [None] * 12
    filled = set()
    city_rows = []
    for index, month in enumerate(city_months):
        amount = as_number(gross[index] if index < len(gross) else None)
        if not month or amount is None or amount == 0:
            continue
        filled.add(month)
        for line, cells in city_lines.items():
            value = as_number(cells[index] if index < len(cells) else None)
            if value is None:
                continue
            city_rows.append((fy, city, "", month, line, round(value, 2), "city"))

    store_rows = []
    ads_check = {}
    for sheet in book.worksheets:
        title = sheet.title.strip()
        if sheet.title == "Summary" or sheet.title in SKIP_SHEETS:
            continue
        rows = list(sheet.iter_rows(max_row=80, max_col=14, values_only=True))
        header = _month_header(rows)
        if header is None:
            notes.append(f"{path.name}:{sheet.title}: no month header")
            continue
        months = _months(header)
        if sheet.title == "Ads Account":
            parts = _ads_parts(rows, notes, where(title))
            for index, month in enumerate(months):
                if month in filled and parts[index] is not None:
                    ads_check[month] = round(parts[index], 2)
            continue
        lines = _line_values(rows, unread=notes, where=where(title))
        gross = lines.get("gross_revenue") or [None] * 12
        ebitda = lines.get("ebitda") or [None] * 12
        level = "events" if title == EVENTS else "store"
        for index, month in enumerate(months):
            if not month or month not in filled:
                continue
            amount = as_number(gross[index] if index < len(gross) else None)
            profit = as_number(ebitda[index] if index < len(ebitda) else None)
            if not amount and not profit:
                continue
            for line, cells in lines.items():
                value = as_number(cells[index] if index < len(cells) else None)
                if value is None:
                    continue
                store_rows.append((fy, city, title, month, line, round(value, 2), level))

    # 2. Kitchen & central = city total minus stores and events, per line and month.
    city_value = {(r[3], r[4]): r[5] for r in city_rows}
    below = defaultdict(float)
    for r in store_rows:
        below[(r[3], r[4])] += r[5]
    central_rows = []
    for key in sorted(set(city_value) | set(below)):
        month, line = key
        if line in ("opening_stock", "closing_stock"):
            continue  # stock on hand, not a monthly flow
        gap = round(city_value.get(key, 0.0) - below.get(key, 0.0), 2)
        if abs(gap) >= 1:
            central_rows.append((fy, city, CENTRAL, month, line, gap, "central"))

    # 3. Checks: EBITDA = net revenue minus costs on every row group; ads rows vs total.
    cost_lines = ("fnb_cost", "electricity", "telephone", "gas", "rent", "software", "salary",
                  "staff_incentives", "amc", "subscription", "insurance", "repairs", "misc",
                  "cam", "ads", "ho_ck_cost")
    groups = defaultdict(dict)
    for r in city_rows + store_rows + central_rows:
        groups[(r[2], r[3])][r[4]] = r[5]
    for (store, month), cells in groups.items():
        if "ebitda" not in cells:
            continue
        worked = cells.get("net_revenue", 0.0) - sum(cells.get(line, 0.0) for line in cost_lines)
        if abs(worked - cells["ebitda"]) > 5:
            raise ValueError(f"{city} {fy} {store or 'city'} {month}: EBITDA does not add up "
                             f"({worked:.0f} vs {cells['ebitda']:.0f})")
    checks = []
    for month, parts in sorted(ads_check.items()):
        total = city_value.get((month, "ads"))
        if total is not None and abs(parts - total) >= 1:
            checks.append({"fy": fy, "city": city, "month": month, "line": "ads",
                           "sheet_total": total, "rows_total": parts})
    return city_rows + store_rows + central_rows, checks, notes


def tidy_rows(source):
    """Every kept cell from the four workbooks: city totals, stores, events, kitchen & central."""
    source = Path(source)
    rows, checks, notes = [], [], []
    for filename, city, fy in SOURCES:
        found, found_checks, sheet_notes = read_workbook(source / filename, city, fy)
        rows.extend(found)
        checks.extend(found_checks)
        notes.extend(sheet_notes)
    return rows, checks, notes


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


def _fmt_rupee_full(value):
    """Rupees with paise rounded off, grouped the Indian way. Not shortened to lakhs."""
    amount = int(round(abs(float(value))))
    digits = str(amount)
    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while head:
            parts.append(head[-2:])
            head = head[:-2]
        grouped = ",".join(reversed(parts)) + "," + tail
    sign = "-" if float(value) < 0 else ""
    return f"{sign}₹{grouped}"


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
    for fy, city, store, month, line, value, _level in rows:
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
    if kind in {"ebitda", "ads", "city-ebitda"}:
        return _fmt_rupee(value)
    return _fmt_pct(value)


def _rupee_gap(current, previous, previous_label):
    if current is None:
        return "not yet in"
    if previous is None:
        return "Last year is not in."
    delta = current - previous
    if abs(delta) < 1:
        return f"Same as {previous_label}"
    word = "better" if delta > 0 else "worse"
    return f"{_fmt_rupee(abs(delta))} {word} than {previous_label}"


def _change(kind, current, previous, previous_label):
    if kind == "city-ebitda":
        return _rupee_gap(current, previous, previous_label)
    if kind in {"ebitda", "ads"}:
        return _rupee_change(current, previous, previous_label)
    return _points_change(current, previous, previous_label)


def build_views(rows, checks=()):
    """Threats, cards, the store list, and one record per clickable figure."""
    table = _index_rows(rows)
    stores = defaultdict(set)
    months_by_city = defaultdict(set)
    for (fy, city, store, month), cells in table.items():
        if store not in NOT_STORES and "gross_revenue" in cells:
            stores[(fy, city)].add(store)
        if store == "" and "gross_revenue" in cells and fy == "FY26-27":
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
        {store for (_fy, _city, store, _month) in table if store not in NOT_STORES},
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

    def city_row(city, month):
        fy = "FY26-27" if month >= "2026-04" else "FY25-26"
        return table.get((fy, city, "", month), {})

    def city_metric(city, month, kind):
        """City figures come from the city Summary sheet, so they include ads and kitchen costs."""
        cells = city_row(city, month)
        if kind == "city-ebitda":
            return cells.get("ebitda")
        return _store_metric(cells, kind)

    def bridge(city, month):
        """Stores, then each city-level item, then the city total. Real sheet figures only."""
        fy = "FY26-27" if month >= "2026-04" else "FY25-26"
        names = stores.get((fy, city), ())
        in_stores = [table.get((fy, city, name, month), {}).get("ebitda") for name in names]
        in_stores = [value for value in in_stores if value is not None]
        steps = []
        if in_stores:
            steps.append({"name": f"All {len(in_stores)} stores", "value": _fmt_rupee(sum(in_stores)), "current": False})
        events = table.get((fy, city, EVENTS, month), {}).get("ebitda")
        if events is not None:
            steps.append({"name": "Event sales", "value": _fmt_rupee(events), "current": False})
        central = table.get((fy, city, CENTRAL, month), {})
        for line in ("net_revenue", "ads", "fnb_cost"):
            if line in central:
                sign = 1 if line == "net_revenue" else -1
                steps.append({"name": BRIDGE_NAMES[line], "value": _fmt_rupee(sign * central[line]), "current": False})
        known = central.get("net_revenue", 0.0) - central.get("ads", 0.0) - central.get("fnb_cost", 0.0)
        rest = central.get("ebitda", 0.0) - known
        if abs(rest) >= 1:
            steps.append({"name": "Other city costs not in any store sheet", "value": _fmt_rupee(rest), "current": False})
        total = city_row(city, month).get("ebitda")
        steps.append({"name": f"{city} total", "value": _fmt_rupee(total), "current": True})
        return steps

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

        city_series = {kind: {} for kind in kinds + ("ads", "city-ebitda")}
        for item in all_months:
            for kind in city_series:
                city_series[kind][item] = city_metric(city, item, kind)
        card_kinds = ("city-ebitda", "ebitda-pct", "food-cost-pct", "rent-pct", "salary-pct", "ads")
        for kind in card_kinds:
            anchor = f"{_slug(city)}-{kind}-{month}"
            current = city_series[kind].get(month)
            previous = city_series[kind].get(_prior_month(month))
            note = _change(kind, current, previous, _month_label(_prior_month(month)))
            if kind == "food-cost-pct":
                note = f"Within {city} only. {note}"
            if kind == "ads":
                note = "City total. " + note
            if kind == "city-ebitda":
                note = "From the city summary. " + note
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
            elif kind == "city-ebitda":
                peers = bridge(city, month)
                peer_note = "How the stores add up to the city figure."
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

    # These two Kolkata ads differences are invoices the owner booked in October.
    booked_in_oct = {("Kolkata", "2026-08"), ("Kolkata", "2026-09")}
    to_check = []
    booked = []
    for item in checks:
        if item["fy"] != "FY26-27" or item["line"] != "ads":
            continue
        gap = item["rows_total"] - item["sheet_total"]
        if (item["city"], item["month"]) in booked_in_oct:
            booked.append(
                f"{item['city']} ads, {_month_label(item['month'])}: {_fmt_rupee_full(abs(gap))}. Booked in Oct."
            )
            continue
        to_check.append(
            f"{item['city']} ads, {_month_label(item['month'])}: the sheet total is "
            f"{_fmt_rupee(item['sheet_total'])} but its rows add up to {_fmt_rupee(item['rows_total'])}. "
            f"If the {_fmt_rupee(abs(gap))} left out is a real cost, {item['city']} EBITDA is "
            f"{_fmt_rupee(abs(gap))} {'lower' if gap > 0 else 'higher'}. To check with Shilajit."
        )
    summary = {"coverage": coverage, "threats": threats, "cards": cards, "checks": to_check, "booked": booked}
    store_view = {"cities": grouped}
    return summary, store_view, details


def write_outputs(rows, dest, checks=()):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "grand_economics_tidy.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["fy", "city", "store", "month", "line", "value", "level"])
        writer.writerows(rows)
    summary, store_view, details = build_views(rows, checks)
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
    rows, checks, notes = tidy_rows(source)
    summary = write_outputs(rows, dest, checks)
    print(len(rows))
    if notes:
        print("\n".join(notes))
    for line in summary["coverage"]:
        print(line)
    print("threats", len(summary["threats"]))
    print("cards", len(summary["cards"]))
    for line in summary["checks"]:
        print("check:", line)
    return rows


if __name__ == "__main__":
    main()
