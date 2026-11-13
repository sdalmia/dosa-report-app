"""Detail behind a Today's insights card.

Every figure comes from a file. Net stays blank when the file leaves it blank.
A missing channel day is named, not treated as zero.
"""

import csv
import re
from datetime import date, timedelta

from app.chat.licences import allowed, red_flags
from app.chat.wizard_a import (
    _ROOT,
    _day,
    _display_store,
    _lakh,
    _navratri_days,
    _north,
    _num,
    _sales_by_store,
    _skip_day,
    _store_key,
    _weekly_gaps,
)

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MISSING = "not in the file"
_CHANNEL = {
    "DINEIN": "Dine-in and takeaway",
    "TAKEOUT": "Dine-in and takeaway",
    "POS": "Dine-in and takeaway",
    "SWIGGY": "Swiggy",
    "SWIGGYONLINE": "Swiggy",
    "SWIGGY-BOLT URGENT": "Swiggy",
    "SWIGGY-TOING": "Swiggy",
    "ZOMATO": "Zomato",
    "ZOMATOONLINE": "Zomato",
    "OWNLYONLINE": "Other",
    "RAPIDO": "Other",
    "MAGICPIN-ORDERING": "Other",
}
_CHANNEL_ORDER = ("Dine-in and takeaway", "Swiggy", "Zomato", "Other")
_LICENCE_TYPE = {
    "fssai": "FSSAI",
    "fire_noc": "Fire NOC",
    "trade_license": "Trade licence",
    "police": "Police",
    "ppl": "PPL",
    "shop_and_establishment": "Shop and establishment",
    "metrology": "Metrology",
    "dpcc": "DPCC",
    "eating_house": "Eating house",
    "labour": "Labour",
    "water_test": "Water test",
    "mcd_health_trade": "MCD health trade",
    "fire_cylinder": "Fire cylinder",
    "weighing_scale": "Weighing scale",
    "health_trade": "Health trade",
}


def card_id(title):
    text = re.sub(r"[^a-z0-9]+", "-", (title or "").casefold()).strip("-")
    return text or "card"


def build_detail(card_id_value, role, as_of=None):
    """One insight. None when the id is not a full week on file."""
    token = (card_id_value or "").strip().casefold()
    if token == "licences":
        if not allowed(role):
            return {"error": "forbidden"}
        return licence_detail(as_of or date.today())
    return sales_detail(token)


def licence_detail(as_of):
    rows = []
    for row in red_flags(as_of):
        expiry = _day(row.get("expiry"))
        if expiry is None:
            when = _MISSING
        elif expiry < as_of:
            when = f"{(as_of - expiry).days} days overdue"
        elif expiry == as_of:
            when = "due today"
        else:
            when = f"{(expiry - as_of).days} days left"
        kind = (row.get("licence_type") or "").strip().casefold()
        rows.append({
            "store": _display_store(row.get("store") or ""),
            "type": _LICENCE_TYPE.get(kind) or (row.get("licence_type") or "").replace("_", " "),
            "expiry": _long(expiry) if expiry else _MISSING,
            "when": when,
            "status": "expired" if row.get("status") == "expired" else "expiring",
        })
    expired = sum(1 for row in rows if row["status"] == "expired")
    expiring = sum(1 for row in rows if row["status"] == "expiring")
    lines = [
        f"{row['store']} | {row['type']} | {row['expiry']} | {row['when']}"
        for row in rows
    ]
    return {
        "id": "licences",
        "kind": "licences",
        "title": "Licences",
        "question": "Which licences expire in the next 30 days?",
        "headline": f"{expired} licences expired, {expiring} expire in 30 days",
        "window": f"As of {_long(as_of)}",
        "notes": [
            "Status is worked out from the expiry date.",
            "Closed stores are left out.",
            "NCR dates come from certificates. A dated NCR tracker is pending.",
        ],
        "rows": rows,
        "share_text": "\n".join([f"Licences as of {_long(as_of)}.", *lines]),
        "download": {
            "columns": ["Store", "Licence", "Expiry", "When"],
            "rows": [[row["store"], row["type"], row["expiry"], row["when"]] for row in rows],
        },
    }


def sales_detail(token):
    gaps, label = _weekly_gaps()
    chosen = next((row for row in gaps if card_id(row["display"]) == token), None)
    if chosen is None:
        return None
    _grouped, latest = _sales_by_store()
    if latest is None:
        return None
    end = latest
    recent_start = end - timedelta(days=6)
    prior_start = recent_start - timedelta(days=7)
    measures = _measures()
    bucket = measures.get(_store_key(chosen["store"])) or {}
    points = bucket.get("days") or {}
    festive = _navratri_days()
    days = []
    for offset in range(7):
        recent_day = recent_start + timedelta(days=offset)
        prior_day = prior_start + timedelta(days=offset)
        recent = points.get(recent_day) or {}
        prior = points.get(prior_day) or {}
        days.append({
            "this_label": _short(recent_day),
            "prior_label": _short(prior_day),
            "this_gross": _shown(recent.get("gross")),
            "prior_gross": _shown(prior.get("gross")),
            "this_bills": _count(recent.get("bills")),
            "prior_bills": _count(prior.get("bills")),
            "this_apb": _shown(recent.get("apb")),
            "prior_apb": _shown(prior.get("apb")),
            "this_value": recent.get("gross"),
            "prior_value": prior.get("gross"),
            "this_bills_value": recent.get("bills"),
            "prior_bills_value": prior.get("bills"),
            "move": None if recent.get("gross") is None or prior.get("gross") is None else recent["gross"] - prior["gross"],
        })
    channels, channel_note, _used_pos = _channels(chosen["store"], recent_start, prior_start)
    city = _city_line(chosen, gaps)
    facts = _facts(chosen, days, channels, city)
    about = _about(channel_note, festive, recent_start)
    direction = "down" if chosen["gap"] < 0 else "up"
    headline = f"Sales {direction} {_lakh(chosen['gap'])} vs the week before ({label})"
    public_days = []
    for day in days:
        public_days.append({
            "day": day["this_label"],
            "this_gross": day["this_gross"],
            "prior_gross": day["prior_gross"],
            "change": _move(day["move"]),
            "this_bills": day["this_bills"],
            "prior_bills": day["prior_bills"],
            "this_apb": day["this_apb"],
            "prior_apb": day["prior_apb"],
        })
    total = _total(days, chosen["gap"])
    share_lines = [chosen["display"], headline, *facts, about]
    return {
        "id": token,
        "kind": "sales",
        "title": chosen["display"],
        "question": f"Why are {chosen['display']} sales {direction} versus the week before?",
        "headline": headline,
        "window": label,
        "facts": facts,
        "about": about,
        "chart": {
            "basis": "Gross",
            "this_week": [{"label": day["this_label"], "value": day["this_value"]} for day in days],
            "prior_week": [{"label": day["prior_label"], "value": day["prior_value"]} for day in days],
        },
        "days": public_days,
        "total": total,
        "channels": channels,
        "channel_note": channel_note,
        "city": city,
        "share_text": "\n".join(share_lines),
        "download": {
            "columns": ["This week", "Gross", "Bills", "APB", "Week before", "Gross", "Bills", "APB", "Change"],
            "rows": [[
                day["this_label"], day["this_gross"], day["this_bills"], day["this_apb"],
                day["prior_label"], day["prior_gross"], day["prior_bills"], day["prior_apb"],
                _move(day["move"]),
            ] for day in days],
            "series": [{"label": day["this_label"], "value": day["this_value"] or 0} for day in days],
        },
    }


def _measures():
    grouped = {}

    def put(store, day, gross=None, bills=None, net=None, region="", replace=False):
        key = _store_key(store)
        if not key:
            return
        bucket = grouped.setdefault(key, {"name": store, "region": "", "days": {}})
        if "(" in store and "(" not in bucket["name"]:
            bucket["name"] = store
        if region and not bucket["region"]:
            bucket["region"] = region
        slot = bucket["days"].setdefault(day, {"gross": None, "bills": None, "net": None, "apb": None})
        if replace:
            if gross is not None:
                slot["gross"] = gross
            if bills is not None:
                slot["bills"] = bills
            if net is not None:
                slot["net"] = net
        else:
            if slot["gross"] is None and gross is not None:
                slot["gross"] = gross
            if slot["bills"] is None and bills is not None:
                slot["bills"] = bills
            if slot["net"] is None and net is not None:
                slot["net"] = net
        if slot["gross"] is not None and slot["bills"] not in (None, 0):
            slot["apb"] = slot["gross"] / slot["bills"]
        else:
            slot["apb"] = None

    daily = _ROOT / "data" / "store_health" / "posist_daily.csv"
    if daily.is_file():
        with daily.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                day = _day(raw.get("date"))
                store = (raw.get("store") or "").strip()
                if day is None or not store:
                    continue
                put(store, day, _num(raw.get("gross")), _num(raw.get("bills")), _num(raw.get("net")), raw.get("region") or "")
    folder = _ROOT / "data" / "posist" / "daily_sales"
    if folder.is_dir():
        for path in sorted(folder.glob("sales_*.csv")):
            stamp = _day(path.stem.replace("sales_", ""))
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for raw in csv.DictReader(handle):
                    day = _day(raw.get("date")) or stamp
                    store = (raw.get("store") or "").strip()
                    if day is None or not store:
                        continue
                    put(store, day, _num(raw.get("gross")), _num(raw.get("bills")), _num(raw.get("net")), replace=True)
    return grouped


def _channels(store, recent_start, prior_start):
    key = _store_key(store)
    recent_days = _window_days(recent_start)
    prior_days = _window_days(prior_start)
    totals = {name: {"this": 0.0, "prior": 0.0, "this_days": set(), "prior_days": set()} for name in _CHANNEL_ORDER}
    present_recent = set()
    present_prior = set()
    used_pos = False
    folder = _ROOT / "data" / "posist" / "daily_sales"
    if folder.is_dir():
        for path in folder.glob("channel_*.csv"):
            stamp = _day(path.stem.replace("channel_", ""))
            if stamp not in recent_days and stamp not in prior_days:
                continue
            side = "this" if stamp in recent_days else "prior"
            with path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
            store_rows = [row for row in rows if _store_key(row.get("store") or "") == key]
            if not store_rows:
                continue
            if side == "this":
                present_recent.add(stamp)
            else:
                present_prior.add(stamp)
            for row in store_rows:
                source = (row.get("source") or "").strip().upper()
                name = _CHANNEL.get(source)
                amount = _num(row.get("sales"))
                if name is None or amount is None:
                    continue
                if source == "POS":
                    used_pos = True
                totals[name][side] += amount
                totals[name][f"{side}_days"].add(stamp)
    missing_recent = [day for day in sorted(recent_days) if day not in present_recent]
    missing_prior = [day for day in sorted(prior_days) if day not in present_prior]
    rows = []
    comparable = bool(present_recent) and bool(present_prior)
    for name in _CHANNEL_ORDER:
        item = totals[name]
        if item["this"] == 0 and item["prior"] == 0:
            continue
        change = None
        if comparable and item["this_days"] and item["prior_days"]:
            change = item["this"] - item["prior"]
        rows.append({
            "name": name,
            "this": _shown(item["this"]) if present_recent else _MISSING,
            "prior": _shown(item["prior"]) if present_prior else _MISSING,
            "change": _move(change) if change is not None else _MISSING,
            "this_value": item["this"] if present_recent else None,
            "prior_value": item["prior"] if present_prior else None,
        })
    note = _channel_note(missing_recent, missing_prior, present_recent, present_prior)
    public = [{key: value for key, value in row.items() if not key.endswith("_value")} for row in rows]
    return {"rows": public, "comparable": comparable, "values": rows}, note, used_pos


def _channel_note(missing_recent, missing_prior, present_recent, present_prior):
    parts = []
    if present_recent:
        parts.append("Store channel sales are in the file for " + _day_list(sorted(present_recent)) + ".")
    if missing_recent:
        parts.append(_day_list(missing_recent) + " has no store channel file.")
    if not present_prior:
        parts.append(
            "The week before has no store channel file, so the change by channel is not shown. "
            "1–5 Nov in that week are totals for the whole company, not this store."
        )
    elif missing_prior:
        parts.append("Channel sales are missing for " + _day_list(missing_prior) + " in the week before. Those days are left out, not treated as zero.")
    return " ".join(parts)


def _facts(chosen, days, channels, city):
    facts = []
    this_bills = _sum(day.get("this_bills_value") for day in days)
    prior_bills = _sum(day.get("prior_bills_value") for day in days)
    this_gross = _sum(day.get("this_value") for day in days)
    prior_gross = _sum(day.get("prior_value") for day in days)
    bill_move = _pct_word(this_bills, prior_bills)
    this_apb = this_gross / this_bills if this_bills else None
    prior_apb = prior_gross / prior_bills if prior_bills else None
    apb_move = _pct_word(this_apb, prior_apb)
    if bill_move and apb_move:
        apb_text = "the average bill was about the same" if apb_move == "about the same" else f"the average bill was {apb_move}"
        facts.append(f"Bills {bill_move}, and {apb_text}.")
    elif bill_move:
        facts.append(f"Bills {bill_move}.")
    moves = [day for day in days if day["move"] is not None]
    if moves:
        pick = min(moves, key=lambda day: day["move"]) if chosen["gap"] < 0 else max(moves, key=lambda day: day["move"])
        word = "drop" if pick["move"] < 0 else "gain"
        facts.append(f"Biggest {word}: {pick['this_label']}, {_move(pick['move'])}.")
    if city.get("percent") is not None:
        word = "up" if city["percent"] >= 0 else "down"
        facts.append(f"City: other {city['name']} stores were {word} {abs(city['percent']):.0f}%.")
    elif city.get("line"):
        facts.append(city["line"])
    lead = _largest_channel(channels)
    if lead:
        facts.append(f"Largest channel this week: {lead['name']}, {lead['this']}.")
    return facts[:4]


def _about(channel_note, festive, recent_start):
    first = "Sales here are gross, because net is blank in the file, and the average bill is gross divided by bills."
    note = channel_note or ""
    no_prior = "week before" in note.casefold() and "no store channel file" in note.casefold()
    if no_prior and "9 Nov" in note:
        channel = "the week before has no store channel file and 9 Nov has none either"
    elif no_prior:
        channel = "the week before has no store channel file"
    else:
        channel = "days with no channel file are left out, not treated as zero"
    navratri = "Navratri days in this window are left out" if any(day in festive for day in _window_days(recent_start)) else "these two weeks are not Navratri"
    second = f"{channel[0].upper()}{channel[1:]}, while Rosedale, Faridabad, and closed stores are left out of the city figure and {navratri}."
    return f"{first} {second}"


def _largest_channel(channels):
    rows = [row for row in channels.get("values") or [] if row.get("this_value")]
    if not rows:
        return None
    return max(rows, key=lambda row: row["this_value"])


def _sum(values):
    numbers = [value for value in values if isinstance(value, (int, float))]
    if len(numbers) != 7:
        return None
    return sum(numbers)


def _pct_word(now, then):
    if now is None or then in (None, 0):
        return None
    pct = (now - then) / abs(then) * 100
    if abs(pct) < 0.5:
        return "about the same"
    word = "down" if pct < 0 else "up"
    shown = abs(pct)
    text = f"{shown:.0f}%" if shown >= 10 else f"{shown:.1f}%"
    return f"{word} {text}"


def _total(days, gap):
    this_gross = _sum(day.get("this_value") for day in days)
    prior_gross = _sum(day.get("prior_value") for day in days)
    this_bills = _sum(day.get("this_bills_value") for day in days)
    prior_bills = _sum(day.get("prior_bills_value") for day in days)
    return {
        "day": "Total",
        "this_gross": _shown(this_gross),
        "prior_gross": _shown(prior_gross),
        "change": _move(gap),
        "this_bills": _count(this_bills),
        "prior_bills": _count(prior_bills),
        "this_apb": _shown(this_gross / this_bills) if this_gross is not None and this_bills else _MISSING,
        "prior_apb": _shown(prior_gross / prior_bills) if prior_gross is not None and prior_bills else _MISSING,
    }


def _driver(chosen, days, channels):
    moves = [day for day in days if day["move"] is not None]
    if not moves:
        day_line = "No day in this window has gross in both weeks."
    else:
        pick = min(moves, key=lambda day: day["move"]) if chosen["gap"] < 0 else max(moves, key=lambda day: day["move"])
        word = "drop" if pick["move"] < 0 else "gain"
        day_line = (
            f"The biggest {word} on one day is {pick['this_label']} versus {pick['prior_label']}, {_move(pick['move'])}."
        )
    if channels["comparable"]:
        ranked = [row for row in channels["values"] if row["this_value"] is not None and row["prior_value"] is not None]
        if ranked and chosen["gap"] < 0:
            lead = min(ranked, key=lambda row: row["this_value"] - row["prior_value"])
            channel_line = f" The channel move on days in both files is largest for {lead['name']}, {_move(lead['this_value'] - lead['prior_value'])}."
        elif ranked:
            lead = max(ranked, key=lambda row: row["this_value"] - row["prior_value"])
            channel_line = f" The channel move on days in both files is largest for {lead['name']}, {_move(lead['this_value'] - lead['prior_value'])}."
        else:
            channel_line = ""
    else:
        channel_line = " Which channel drove it is not in the file, because the week before has no store channel sales."
    return day_line + channel_line


def _city_line(chosen, gaps):
    city = "Delhi NCR" if _north(chosen["store"], chosen.get("region") or "") else "Kolkata"
    peers = [
        row for row in gaps
        if row["store"] != chosen["store"] and (_north(row["store"], row.get("region") or "") == (city == "Delhi NCR"))
    ]
    names = [row["display"] for row in peers]
    if not peers:
        return {"name": city, "line": f"No other {city} store has a full week in the file.", "peers": names, "percent": None}
    recent = sum(row["recent"] for row in peers)
    prior = sum(row["prior"] for row in peers)
    percent = None if not prior else (recent - prior) / abs(prior) * 100
    return {"name": city, "line": "", "peers": names, "percent": percent}


def _window_days(start):
    return {start + timedelta(days=offset) for offset in range(7)}


def _short(day):
    return f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"


def _long(day):
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def _day_list(days):
    if not days:
        return ""
    if len({day.month for day in days}) == 1:
        labels = [str(day.day) for day in days]
        suffix = f" {_MONTHS[days[0].month - 1]}"
    else:
        labels = [f"{day.day} {_MONTHS[day.month - 1]}" for day in days]
        suffix = ""
    if len(labels) > 1:
        labels[-1] = "and " + labels[-1]
    return ", ".join(labels) + suffix


def _shown(value):
    if value is None:
        return _MISSING
    return _lakh(value)


def _count(value):
    if value is None:
        return _MISSING
    return f"{int(round(value)):,}"


def _move(value):
    if value is None:
        return _MISSING
    word = "down" if value < 0 else "up"
    return f"{word} {_lakh(value)}"
