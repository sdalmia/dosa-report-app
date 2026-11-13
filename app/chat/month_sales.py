"""Calendar-month sales from Posist daily files, by city and store.

A completed month is the 1st through the last day of that month. Month-to-date,
the last 7 days, and a window that ends in the next month are not used in its place.
Manisquare and Forum sales are counted; only their bills and average bill stay
out of comparisons. Store-level net is left blank when the daily file has none.
"""

import csv
import re
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.food_courts import is_mall_food_court
from app.store_health.day_notes import FARIDABAD_CLOSED_FROM

_ROOT = Path(__file__).resolve().parents[2]
_CLOSED = ("chattarpur", "gk1", "gk 1")
_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH_LABEL = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTH_SHORT = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_SKIP_QUESTION = (
    "audit", "mystery", "payment", "licence", "license", "budget", "purchase",
    "inventory", "recipe", "ebitda", "grand economics", "tally", "day book",
    "daybook", "headcount", "employee",
)
_SALES_WORDS = ("sale", "sales", "sold", "gross", "revenue", "turnover")
_EAST_WORDS = ("kolkata", "calcutta", "east")
_NORTH_WORDS = ("ncr", "delhi", "north", "gurgaon", "gurugram", "noida", "faridabad")


def _num(value):
    text = str(value or "").strip().replace(",", "").replace("%", "").replace("₹", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _day(value):
    text = str(value or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _closed(name):
    text = (name or "").casefold()
    return any(token in text for token in _CLOSED)


def _skip_day(store, day):
    if day is None or _closed(store):
        return True
    if "faridabad" in (store or "").casefold() and day >= FARIDABAD_CLOSED_FROM:
        return True
    return False


def display_store(name):
    text = re.sub(r"\s*\([^)]*\)", "", name or "")
    text = re.sub(r"(?i)^dosa coffee\s*-\s*", "", text)
    text = re.sub(r"\s+\d{1,2}/\d{4}$", "", text)
    text = re.sub(r"\s+\d{5,}$", "", text)
    text = " ".join(text.split())
    return " ".join((word[:1].upper() + word[1:]) if word else "" for word in text.split())


def _store_key(name):
    return display_store(name).casefold()


def _lakh(value):
    """Always lakhs, so ₹316.53L is not rounded to ₹3.17Cr."""
    number = float(value)
    sign = "-" if number < 0 else ""
    return f"{sign}₹{abs(number) / 100000:.2f}L"


def _region(store, region):
    text = (region or "").strip()
    folded = text.casefold()
    if folded in {"east", "kolkata"}:
        return "East"
    if folded in {"north", "ncr", "delhi"}:
        return "North"
    if text:
        return text
    name = (store or "").casefold()
    raw = store or ""
    if "event" in name or "cater" in name:
        return "Events"
    if (
        re.search(r"\(02/", raw) or re.search(r"(?<!\d)02/", raw)
        or any(token in name for token in (
            "noida", "gurgaon", "faridabad", "connaught", "kalkaji",
            "rohini", "paschim", "shalimar", "model town", "jasola", "pacific",
        ))
    ):
        return "North"
    if (
        re.search(r"\(01/", raw) or re.search(r"(?<!\d)01/", raw)
        or re.search(r"\(\d{3,4}\)", raw)
        or "lake road" in name
    ):
        return "East"
    return ""


def _city_label(region):
    if region == "East":
        return "Kolkata"
    if region == "North":
        return "NCR"
    return region or "Network"


def _sales_by_store():
    """Store gross, bills and net by day. Dated sales_*.csv files overlay the cumulative file.

    Stores are joined by display name so 'Connaught place' and
    'Dosa Coffee - Connaught place' are one store, not two.
    """
    grouped = {}

    def put(store, day, gross, bills=None, net=None, region=""):
        if _skip_day(store, day) or gross is None:
            return
        key = _store_key(store)
        if not key:
            return
        bucket = grouped.setdefault(key, {"name": store, "region": "", "days": {}})
        if "(" in (store or "") and "(" not in bucket["name"]:
            bucket["name"] = store
        assigned = _region(store, region)
        if assigned and (not bucket["region"] or bucket["region"] == "Events"):
            bucket["region"] = assigned
        elif assigned and not bucket["region"]:
            bucket["region"] = assigned
        prior = bucket["days"].get(day) or {}
        bucket["days"][day] = {
            "gross": gross,
            "bills": bills if bills is not None else prior.get("bills"),
            "net": net if net is not None else prior.get("net"),
        }

    daily = _ROOT / "data" / "store_health" / "posist_daily.csv"
    if daily.is_file():
        with daily.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                put(
                    (raw.get("store") or "").strip(),
                    _day(raw.get("date")),
                    _num(raw.get("gross")),
                    _num(raw.get("bills")),
                    _num(raw.get("net")),
                    raw.get("region") or "",
                )
    folder = _ROOT / "data" / "posist" / "daily_sales"
    if folder.is_dir():
        for path in sorted(folder.glob("sales_*.csv")):
            stamp = _day(path.stem.replace("sales_", ""))
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for raw in csv.DictReader(handle):
                    put(
                        (raw.get("store") or "").strip(),
                        _day(raw.get("date")) or stamp,
                        _num(raw.get("gross")),
                        _num(raw.get("bills")),
                        _num(raw.get("net")),
                        raw.get("region") or "",
                    )
    return grouped


def _insights_net():
    """City and network net by day, from Posist Insights notes and network CSV files."""
    days = {}
    path = _ROOT / "data" / "posist" / "sales_pred_vs_actual.csv"
    pattern = re.compile(r"East ₹([0-9.]+)L \+ North ₹([0-9.]+)L")
    if path.is_file():
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                day = _day(raw.get("date"))
                if day is None:
                    continue
                row = days.setdefault(day, {"East": None, "North": None, "Network": None})
                network = _num(raw.get("actual_net_L"))
                if network is not None:
                    row["Network"] = network * 100000
                match = pattern.search(raw.get("notes") or "")
                if match:
                    row["East"] = float(Decimal(match.group(1)) * Decimal(100000))
                    row["North"] = float(Decimal(match.group(2)) * Decimal(100000))
    folder = _ROOT / "data" / "posist" / "daily_sales"
    if folder.is_dir():
        for path in sorted(folder.glob("network_*.csv")):
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for raw in csv.DictReader(handle):
                    day = _day(raw.get("date")) or _day(path.stem.replace("network_", ""))
                    if day is None:
                        continue
                    region = (raw.get("region") or "").strip()
                    net = _num(raw.get("net"))
                    if net is None:
                        continue
                    row = days.setdefault(day, {"East": None, "North": None, "Network": None})
                    if region in {"East", "North"}:
                        row[region] = net
                    elif region in {"Total", "Network", ""}:
                        row["Network"] = net
    return days


def month_span(year, month):
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _month_named(folded):
    found = []
    for name, month in _MONTHS.items():
        if re.search(r"\b" + name + r"\b", folded):
            found.append((len(name), month))
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][1]


def _year_for(month, folded, available):
    match = re.search(r"\b(20\d{2})\b", folded or "")
    if match:
        return int(match.group(1))
    years = sorted({year for year, item in available if item == month}, reverse=True)
    return years[0] if years else date.today().year


def relevant(question):
    """True when the question is asking for a named month's sales totals."""
    folded = (question or "").casefold()
    if not folded or _month_named(folded) is None:
        return False
    if any(token in folded for token in _SKIP_QUESTION):
        return False
    return any(token in folded for token in _SALES_WORDS)


def _wanted_city(folded):
    if any(word in folded for word in _EAST_WORDS):
        return "East"
    if any(word in folded for word in _NORTH_WORDS):
        return "North"
    return None


def _aggregate(year, month):
    """Gross and bills by city and store for one calendar month. Net is attached separately."""
    start, end = month_span(year, month)
    stores = _sales_by_store()
    cities = {}
    for bucket in stores.values():
        region = bucket.get("region") or ""
        # Events is its own city, counted in the network total, kept out of
        # Kolkata and NCR store comparisons.
        if region not in {"East", "North", "Events"}:
            continue
        city = cities.setdefault(region, {
            "region": region,
            "label": _city_label(region),
            "gross": 0.0,
            "bills": 0.0,
            "bills_ex_mall": 0.0,
            "mall_gross": 0.0,
            "days": set(),
            "stores": [],
        })
        name = bucket["name"]
        mall = is_mall_food_court(name)
        gross = bills = net = 0.0
        has_net = False
        days = []
        for day, row in bucket["days"].items():
            if day < start or day > end:
                continue
            gross += float(row.get("gross") or 0)
            bills += float(row.get("bills") or 0)
            if row.get("net") is not None:
                net += float(row["net"])
                has_net = True
            days.append(day)
        if not days:
            continue
        days.sort()
        city["gross"] += gross
        city["bills"] += bills
        if not mall:
            city["bills_ex_mall"] += bills
        else:
            city["mall_gross"] += gross
        city["days"].update(days)
        city["stores"].append({
            "name": display_store(name),
            "raw": name,
            "mall": mall,
            "gross": gross,
            "bills": bills,
            "net": net if has_net else None,
            "days": days,
        })
    for city in cities.values():
        city["stores"].sort(key=lambda row: row["gross"], reverse=True)
        city["day_count"] = len(city["days"])
    return cities, start, end


def _net_for(year, month, insights):
    start, end = month_span(year, month)
    sums = {"East": 0.0, "North": 0.0, "Network": 0.0}
    days = {"East": [], "North": [], "Network": []}
    for day, row in insights.items():
        if day < start or day > end:
            continue
        for key in sums:
            if row.get(key) is not None:
                sums[key] += row[key]
                days[key].append(day)
    result = {}
    for key in sums:
        found = sorted(days[key])
        result[key] = {
            "net": sums[key] if found else None,
            "days": found,
            "first": found[0] if found else None,
            "last": found[-1] if found else None,
            "count": len(found),
        }
    return result


def months_available():
    stores = _sales_by_store()
    found = set()
    for bucket in stores.values():
        for day in bucket["days"]:
            found.add((day.year, day.month))
    return sorted(found)


def _complete(day_count, start, end):
    return day_count >= (end - start).days + 1


def _span_label(start, end):
    if start.month == end.month and start.year == end.year:
        return f"{start.day}–{end.day} {_MONTH_SHORT[start.month]} {start.year}"
    return f"{start.day} {_MONTH_SHORT[start.month]}–{end.day} {_MONTH_SHORT[end.month]} {end.year}"


def _gaps(days, start, end):
    from datetime import timedelta
    have = set(days)
    return [start + timedelta(days=n) for n in range((end - start).days + 1) if start + timedelta(days=n) not in have]


def _short_days(days):
    if not days:
        return ""
    if len({day.month for day in days}) == 1:
        return ", ".join(str(day.day) for day in days) + f" {_MONTH_SHORT[days[0].month]}"
    return ", ".join(f"{day.day} {_MONTH_SHORT[day.month]}" for day in days)


def _net_clause(row, start, end, label):
    if not row or not row.get("days") or row.get("net") is None:
        return f"{label} net is not loaded for this month."
    first, last, count = row["first"], row["last"], row["count"]
    needed = (end - start).days + 1
    figure = _lakh(row["net"])
    if count >= needed and first == start and last == end:
        return f"{label} net was {figure} for {_span_label(start, end)}."
    missing = []
    if first and first > start:
        missing.append(_span_label(start, first.fromordinal(first.toordinal() - 1)) if first > start else "")
    note = (
        f"{label} net was {figure} for {_span_label(first, last)} ({count} of {needed} days), "
        f"from Posist Insights."
    )
    if start.month == 10 and start.year == 2026 and start not in set(row["days"]):
        note += " 1 Oct net is not loaded, so a full-month net is not stated."
    else:
        note += " Days without net are not treated as zero, and a full-month net is not stated."
    return note


def packet(question=""):
    """Text for the model: completed calendar months, city and store totals."""
    available = months_available()
    if not available:
        return "Calendar-month sales: no daily sales file is loaded."
    insights = _insights_net()
    folded = (question or "").casefold()
    wanted_month = _month_named(folded)
    wanted_year = _year_for(wanted_month, folded, available) if wanted_month else None
    wanted_city = _wanted_city(folded)
    lines = [
        "Calendar-month sales, 1st through last day of each month. "
        "These are not month-to-date and not a rolling 7-day or 30-day window. "
        "If the question asks for a completed month such as October, use that month's 1–31 table. "
        "Do not use month-to-date, do not use a window that ends in the next month, "
        "and do not relabel November figures as October.",
        "Gross includes Manisquare and Forum sales. Their bills and average bill stay out of comparisons. "
        "Chattarpur and GK1 Cloud Kitchen are out of the sales base. Faridabad is out from 23 Oct. "
        "Store-level net is blank unless a net cell is in the file. "
        "The 24.78% Swiggy/Zomato charge is on net delivery bills only and is not a way to invent store net from gross.",
        "Source for gross and bills: Posist daily sales (posist_daily.csv, with dated sales_*.csv overlays for the same store). "
        "Source for city net: Posist Insights notes in sales_pred_vs_actual.csv, and network_*.csv where those files exist. "
        "Grand Economics has no October 2026.",
    ]
    for year, month in available:
        cities, start, end = _aggregate(year, month)
        nets = _net_for(year, month, insights)
        complete = all(_complete(city["day_count"], start, end) for city in cities.values()) if cities else False
        status = "complete" if complete else "incomplete"
        if month == 11:
            status = "incomplete; this is November, not October. Month-to-date rows later in this packet are November"
        if month == 9 and start.year == 2026:
            status = "incomplete; the daily file starts on 4 Sep, so 1–3 Sep are not on file"
        lines.append("")
        lines.append(
            f"{_MONTH_LABEL[month]} {year} ({_span_label(start, end)}, {status})."
        )
        lines.append("city | gross | bills_ex_mall | mall_sales | days | complete | net | net_window")
        network_gross = sum(city["gross"] for city in cities.values())
        network_bills = sum(city["bills_ex_mall"] for city in cities.values())
        network_mall = sum(city["mall_gross"] for city in cities.values())
        day_count = max((city["day_count"] for city in cities.values()), default=0)
        net_row = nets.get("Network") or {}
        net_window = _span_label(net_row["first"], net_row["last"]) if net_row.get("first") else "not loaded"
        net_fig = _lakh(net_row["net"]) if net_row.get("net") is not None else "not loaded"
        for region in ("East", "North"):
            city = cities.get(region)
            if not city:
                continue
            n = nets.get(region) or {}
            n_fig = _lakh(n["net"]) if n.get("net") is not None else "not loaded"
            n_win = _span_label(n["first"], n["last"]) if n.get("first") else "not loaded"
            lines.append(
                f"{city['label']} | {_lakh(city['gross'])} | {int(round(city['bills_ex_mall']))} | "
                f"{_lakh(city['mall_gross']) if city['mall_gross'] else '₹0'} | {city['day_count']} | "
                f"{'yes' if _complete(city['day_count'], start, end) else 'no'} | {n_fig} | {n_win}"
            )
        lines.append(
            f"Network | {_lakh(network_gross)} | {int(round(network_bills))} | "
            f"{_lakh(network_mall) if network_mall else '₹0'} | {day_count} | "
            f"{'yes' if complete else 'no'} | {net_fig} | {net_window}"
        )
        show_stores = False
        if wanted_month == month and (wanted_year is None or wanted_year == year):
            show_stores = True
        elif wanted_month is None and month == 10 and year == 2026:
            show_stores = True
        if not show_stores:
            continue
        regions = [wanted_city] if wanted_city else ["East", "North"]
        for region in regions:
            city = cities.get(region)
            if not city:
                continue
            lines.append("")
            lines.append(
                f"{city['label']} stores, {_MONTH_LABEL[month]} {year}, {_span_label(start, end)}. "
                "Gross includes mall-bulk stores. Bills for Manisquare and Forum are blank."
            )
            lines.append("store | gross | bills | days | note")
            for row in city["stores"]:
                note = ""
                if row["mall"]:
                    note = "mall bulk: sales counted; bills and APB left out of comparisons"
                gaps = _gaps(row["days"], start, end)
                if gaps:
                    note = (note + "; " if note else "") + (
                        f"{len(row['days'])} of {(end - start).days + 1} days; "
                        f"missing {_short_days(gaps)}, left out not treated as zero"
                    )
                if "faridabad" in row["raw"].casefold():
                    note = (note + "; " if note else "") + "out of the sales base from 23 Oct; 1–22 Oct is included"
                bills = "" if row["mall"] else str(int(round(row["bills"])))
                lines.append(
                    f"{row['name']} | {_lakh(row['gross'])} | {bills} | {len(row['days'])} | {note}"
                )
    return "\n".join(lines)


def answer(question, data, owner):
    """A file-backed total for a named month. Never uses month-to-date as a stand-in."""
    from app.chat.facts import _pack
    from app.chat.visuals import chart_block, table_block

    folded = (question or "").casefold()
    available = months_available()
    month = _month_named(folded)
    if month is None:
        return _pack("Name the month. No monthly total was assumed.", "", "sales", question, owner)
    year = _year_for(month, folded, available)
    if (year, month) not in available:
        label = f"{_MONTH_LABEL[month]} {year}"
        return _pack(
            f"{label} sales are not in the loaded daily files. That month would come from Alfred, who pulls Posist Insights daily sales. No figure is invented.",
            "",
            "sales",
            question,
            owner,
        )
    cities, start, end = _aggregate(year, month)
    nets = _net_for(year, month, _insights_net())
    city_key = _wanted_city(folded)
    label = f"{_MONTH_LABEL[month]} {year}"
    span = _span_label(start, end)
    as_of = f"{end.day} {_MONTH_SHORT[end.month]} {end.year}"

    if city_key:
        city = cities.get(city_key)
        if not city:
            return _pack(
                f"{_city_label(city_key)} {label} sales are not in the loaded daily files. That month would come from Alfred, who pulls Posist Insights daily sales. No figure is invented.",
                as_of,
                "sales",
                question,
                owner,
            )
        return _city_answer(question, owner, city, nets.get(city_key) or {}, start, end, label, span, as_of)

    network_gross = sum(city["gross"] for city in cities.values())
    network_bills = sum(city["bills"] for city in cities.values())
    east = cities.get("East")
    north = cities.get("North")
    bits = [
        f"**Network {label} sales were {_lakh(network_gross)} gross"
        + (f", {int(round(network_bills)):,} bills" if network_bills else "")
        + f", for the full calendar month {span}.**",
        "",
    ]
    bullets = []
    if east:
        mall = ""
        if east["mall_gross"]:
            mall = (
                f" That includes Manisquare and Forum sales of {_lakh(east['mall_gross'])}. "
                "Mall bulk bills and average bill stay out of comparisons; their sales are counted."
            )
        bullets.append(f"Kolkata {_lakh(east['gross'])} gross.{mall}")
    events = cities.get("Events")
    if north:
        if end < FARIDABAD_CLOSED_FROM:
            fb = "Faridabad is included (it is in the sales base until 22 Oct)."
        elif start < FARIDABAD_CLOSED_FROM:
            fb = "Faridabad is out of the sales base from 23 Oct; 1–22 Oct is included."
        else:
            fb = "Faridabad is out of the sales base from 23 Oct."
        bullets.append(f"NCR {_lakh(north['gross'])} gross. {fb}")
    if events and events["gross"]:
        ev_days = sorted(events["days"])
        ev_span = _span_label(ev_days[0], ev_days[-1]) if ev_days else ""
        bullets.append(
            f"Events & Catering {_lakh(events['gross'])} is counted in the network total "
            f"and kept as its own row, outside store comparisons"
            + (f" ({ev_span} only)" if ev_span else "")
            + "."
        )
    net = nets.get("Network") or {}
    bullets.append(_net_clause(net, start, end, "Network"))
    bullets.append(
        "Store-level net is not in the daily sales file. "
        "The 24.78% Swiggy/Zomato charge is on net delivery bills only and is not used to invent net from gross."
    )
    bits.extend(f"- {item}" for item in bullets)
    bits.append("")
    bits.append(f"Data: Posist daily sales, {span}. Net: Posist Insights. Grand Economics has no {label}.")
    text = "\n".join(bits)
    table_rows = []
    series = []
    if east:
        table_rows.append(["Kolkata", _lakh(east["gross"]), str(int(round(east["bills_ex_mall"])))])
        series.append({"label": "Kolkata", "value": round(east["gross"] / 100000, 2)})
    if north:
        table_rows.append(["NCR", _lakh(north["gross"]), str(int(round(north["bills_ex_mall"])))])
        series.append({"label": "NCR", "value": round(north["gross"] / 100000, 2)})
    table = table_block(["City", "Gross", "Bills"], table_rows, f"{label} gross")
    chart = chart_block(f"{label} gross", series, "₹L")
    amounts = [network_gross]
    if east:
        amounts.extend([east["gross"], east["mall_gross"], east["bills_ex_mall"]])
    if north:
        amounts.extend([north["gross"], north["bills_ex_mall"]])
    if net.get("net") is not None:
        amounts.append(net["net"])
    for item in series:
        amounts.append(item["value"])
    return _pack(
        text,
        as_of,
        "sales",
        question,
        owner,
        table=table,
        chart=chart,
        source={"text": text, "amounts": amounts},
    )


def _city_answer(question, owner, city, net, start, end, label, span, as_of):
    from app.chat.facts import _pack
    from app.chat.visuals import chart_block, table_block

    complete = _complete(city["day_count"], start, end)
    window = f"the full calendar month {span}" if complete else f"{span}, which is not a complete calendar month"
    lines = [
        f"**{city['label']}'s {label} sales were {_lakh(city['gross'])} gross, for {window}.**",
        "",
    ]
    bullets = []
    mall_names = [row["name"] for row in city["stores"] if row["mall"]]
    if city["mall_gross"] and mall_names:
        parts = " and ".join(f"{row['name']} {_lakh(row['gross'])}" for row in city["stores"] if row["mall"])
        bullets.append(
            f"That total includes {parts}. "
            "Mall bulk bills and average bill stay out of comparisons; their sales are counted."
        )
    thin = [row for row in city["stores"] if len(row["days"]) < (end - start).days + 1]
    bills_note = f"Bills at the other stores: {int(round(city['bills_ex_mall'])):,}."
    if thin:
        thin_bits = []
        for row in thin:
            gaps = _gaps(row["days"], start, end)
            thin_bits.append(
                f"{row['name']} has {len(row['days'])} of {(end - start).days + 1} days"
                + (f" (missing {_short_days(gaps)})" if gaps else "")
            )
        bills_note += (
            " " + "; ".join(thin_bits) + ". Missing days are left out, not treated as zero. "
            "Every other store in this city has every day of the month on file."
        )
    else:
        bills_note += " Every store in this city has every day of the month on file."
    if "faridabad" in " ".join(row["raw"] for row in city["stores"]).casefold():
        if end < FARIDABAD_CLOSED_FROM:
            bills_note += " Faridabad is included (it is in the sales base until 22 Oct)."
        elif start < FARIDABAD_CLOSED_FROM:
            bills_note += " Faridabad is out of the sales base from 23 Oct; 1–22 Oct is included."
        else:
            bills_note += " Faridabad is out of the sales base from 23 Oct."
    bullets.append(bills_note)
    bullets.append(_net_clause(net, start, end, city["label"]))
    bullets.append(
        "Store-level net is not in the daily sales file. "
        "The 24.78% Swiggy/Zomato charge is on net delivery bills only and is not used to invent a full-month net from gross."
    )
    lines.extend(f"- {item}" for item in bullets)
    lines.append("")
    lines.append("Store | Gross | Bills")
    for row in city["stores"]:
        bills = "—" if row["mall"] else f"{int(round(row['bills'])):,}"
        lines.append(f"{row['name']} | {_lakh(row['gross'])} | {bills}")
    lines.append("")
    lines.append(f"Data: Posist daily sales, {span}. Net: Posist Insights. Grand Economics has no {label}.")
    text = "\n".join(lines)
    table_rows = []
    series = []
    for row in city["stores"]:
        bills = "—" if row["mall"] else f"{int(round(row['bills'])):,}"
        table_rows.append([row["name"], _lakh(row["gross"]), bills])
        if not row["mall"] and len(series) < 8:
            series.append({"label": row["name"], "value": round(row["gross"] / 100000, 2)})
    table = table_block(["Store", "Gross", "Bills"], table_rows, f"{city['label']} {label} gross")
    chart = chart_block(f"{city['label']} {label} gross", series, "₹L")
    amounts = [city["gross"], city["mall_gross"], city["bills_ex_mall"], city["bills"]]
    if net.get("net") is not None:
        amounts.append(net["net"])
    for row in city["stores"]:
        amounts.extend([row["gross"], row["bills"], round(row["gross"] / 100000, 2)])
    return _pack(
        text,
        as_of,
        "sales",
        question,
        owner,
        table=table,
        chart=chart,
        source={"text": text, "amounts": amounts},
    )


def use_file_answer(question, local):
    """The file-backed monthly total should be shown instead of a model rewrite."""
    if not relevant(question):
        return False
    text = (local or {}).get("text") or ""
    if not text.strip():
        return False
    folded = text.casefold()
    if "aren't connected" in folded or "isn't available" in folded:
        return False
    if "not in the loaded" in folded and "were" not in folded:
        return False
    return True
