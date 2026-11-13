"""Location, brands, prices, gaps, training, Reelo, and Posist channel sales."""

import csv
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_NOT_ON_REELO = (
    "Manisquare",
    "Forum",
    "New Town Cloud Kitchen",
    "Calcutta Swimming Club",
    "Food Truck",
    "Events & Catering",
    "GK1 Cloud Kitchen",
    "Chattarpur",
)
_OPS_GAP_OWNERS = {"tony", "alfred", "albus", "logan", "procurement"}


def _read(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _num(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pack(text, as_of, topic, question, owner, chart=None):
    from app.chat.facts import _pack as pack

    result = pack(text, as_of, topic, question, owner, chart=chart, source={"text": text})
    return result


def _asks_location(question):
    folded = (question or "").casefold()
    return any(token in folded for token in (
        "where should", "where next", "open next", "where in delhi", "where in ncr", "location finder",
    ))


def _asks_brands(question):
    folded = (question or "").casefold()
    return any(token in folded for token in ("which brands", "what brands", "brands are in", "brands in ", "what's near", "whats near"))


def location_text(question):
    folded = (question or "").casefold()
    clusters = _read(_ROOT / "data" / "site_pattern" / "candidate_clusters.csv")
    scores = _read(_ROOT / "data" / "site_pattern" / "location_finder_ncr.csv")
    want_airport = "airport" in folded
    city = "kolkata" if "kolkata" in folded else "ncr"
    if "delhi" in folded or "ncr" in folded:
        city = "ncr"
    rows = []
    for row in clusters:
        if (row.get("city") or "").casefold() != city and city == "ncr" and (row.get("city") or "").casefold() != "ncr":
            continue
        if city == "kolkata" and (row.get("city") or "").casefold() != "kolkata":
            continue
        flag = (row.get("flag") or "").casefold()
        if "airport" in flag and not want_airport:
            continue
        rows.append(row)
    rows.sort(key=lambda row: _num(row.get("weighted_score")) or 0, reverse=True)
    lines = [
        "Location Finder. Live Google scoring is not called here, so a candidate does not get a new score out of 10.",
        "The scores out of 10 below are the saved scores of existing NCR stores, for scale.",
        "Airport sites are left out unless the question asks for an airport.",
    ]
    for row in scores:
        if row.get("score_out_of_10"):
            lines.append(
                f"{row.get('posist_store')} score {row.get('score_out_of_10')} out of 10, {row.get('verdict')}. "
                f"Energy {row.get('Energy')}, Quality {row.get('Quality')}, Anchor {row.get('Anchor')}, "
                f"Diversity {row.get('Diversity')}, Transport {row.get('Transport')}, Reviews {row.get('Reviews')}."
            )
            if len([line for line in lines if "out of 10" in line]) >= 4:
                break
    lines.append("Candidate areas by the site-pattern weight, which is not a score out of 10:")
    for row in rows[:5]:
        note = ""
        area = row.get("candidate_area") or ""
        if "sector 81" in area.casefold() or "sector 81" in (row.get("anchor_example") or "").casefold():
            note = " Near closed Faridabad Sec-15. Do not treat it as a normal comparison."
        lines.append(
            f"{area}: weight {row.get('weighted_score')}, nearest {row.get('nearest_dosa_coffee')} "
            f"at {row.get('nearest_dc_km')} km, brands {row.get('brands')}.{note}"
        )
    if not rows:
        lines.append("No candidate row matched.")
    return "\n".join(lines)


def brands_text(question):
    folded = (question or "").casefold()
    path = _ROOT / "data" / "site_pattern" / "neighbour_brand_outlets.csv"
    if not path.is_file():
        return "Brand list is not loaded."
    rows = _read(path)
    area = ""
    for token in ("rajouri", "saket", "kalkaji", "connaught", "dlf", "noida", "gurgaon", "salt lake"):
        if token in folded:
            area = token
            break
    picked = []
    for row in rows:
        blob = " ".join([
            row.get("outlet_area") or "",
            row.get("outlet_address") or "",
            row.get("city") or "",
            row.get("outlet_name") or "",
        ]).casefold()
        if area and area not in blob:
            continue
        picked.append(row)
    if area and not picked:
        return f"No saved brand outlet matches {area}. Google Places is not called from chat. The finder page can search live."
    if not area:
        picked = picked[:8]
    lines = [
        "Brand outlets from the Location Finder file. Distance is to the nearest Dosa Coffee store. Google Places is not called, so this is the saved list.",
        "brand | outlet | area | km | rating | reviews | nearest store",
    ]
    for row in picked[:12]:
        metres = _num(row.get("nearest_dc_dist_m"))
        km = "" if metres is None else f"{metres / 1000:.1f}"
        lines.append(" | ".join([
            row.get("brand") or "",
            row.get("outlet_name") or "",
            row.get("outlet_area") or "",
            km,
            row.get("rating") or "",
            row.get("reviews") or "",
            row.get("nearest_dosa_coffee") or "",
        ]))
    return "\n".join(lines)


def _asks_price(question):
    folded = (question or "").casefold()
    if any(token in folded for token in ("ticket", "famepilot")):
        return False
    if any(token in folded for token in ("price trend", "how has", "ingredient tracker", "price graph")):
        return True
    return "moved" in folded and any(token in folded for token in ("price", "paneer", "milk", "cheese", "ingredient"))


def price_answer(question, owner):
    path = _ROOT / "data" / "procurement" / "procurement_summary.json"
    if not path.is_file():
        return _pack("Ingredient prices are not loaded.", "", "procurement", question, owner)
    payload = json.loads(path.read_text(encoding="utf-8"))
    block = payload.get("monthly_prices") or {}
    items = block.get("items") or []
    folded = (question or "").casefold()
    words = [word for word in folded.replace("?", " ").split() if len(word) > 3 and word not in {"how", "has", "have", "price", "moved", "trend", "this", "month", "what"}]
    picked = []
    for row in items:
        name = str(row.get("item") or "")
        if words and not any(word in name.casefold() for word in words):
            continue
        picked.append(row)
    if not picked:
        picked = items[:6]
    lines = [
        f"Ingredient prices. This month {block.get('this_month') or 'unknown'}, last month {block.get('last_month') or 'unknown'}.",
        "A third month is not in this summary, so the 3-month change is not stated.",
        "Compare a city only with its own last month.",
    ]
    series = []
    for row in picked[:8]:
        this = (row.get("this_month") or {}).get("avg_unit_price") if isinstance(row.get("this_month"), dict) else None
        last = (row.get("last_month") or {}).get("avg_unit_price") if isinstance(row.get("last_month"), dict) else None
        lines.append(
            f"{row.get('city')} {row.get('item')}: this month {this}, last month {last}, change {row.get('pct_change')}%."
        )
        if this is not None:
            series.append({"label": f"{row.get('city')} now", "value": this})
        if last is not None:
            series.append({"label": f"{row.get('city')} last", "value": last})
    chart = None
    if series:
        chart = {"type": "bar", "title": "Unit price, this month and last", "unit": "", "series": series[:8]}
    return _pack("\n".join(lines), str(payload.get("as_of") or ""), "procurement", question, owner, chart=chart)


def _ops_gap(row):
    area = (row.get("area") or "").casefold()
    owner = (row.get("owner") or "").casefold()
    if area in {"accounts", "people", "hr", "finance"}:
        return False
    if owner in {"hr", "accountant"}:
        return False
    return owner in _OPS_GAP_OWNERS or area in {"sales", "general", "procurement", "reputation", "tech"}


def gaps_text(question, role):
    from app.gaps import load_gap_files

    rows = load_gap_files()
    if role != "owner":
        rows = [row for row in rows if _ops_gap(row)]
    folded = (question or "").casefold()
    if "tony" in folded:
        rows = [row for row in rows if (row.get("owner") or "").casefold() == "tony"]
    lines = [
        "Data gaps from data/gaps. Owner sees every file. Other roles see ops gaps only.",
        "No earlier snapshot is stored yet, so a change-since date cannot be shown. This is the current file list.",
        "owner | status | title | since | blocks",
    ]
    for row in rows[:20]:
        lines.append(" | ".join([
            row.get("owner") or "",
            row.get("status") or "",
            row.get("title") or "",
            str(row.get("as_of") or row.get("due") or ""),
            row.get("why_it_matters") or "",
        ]))
    if len(lines) == 3:
        lines.append("(none)")
    return "\n".join(lines)


def _asks_gaps(question):
    folded = (question or "").casefold()
    return any(token in folded for token in ("data gap", "are we missing", "pending from", "what's missing", "whats missing"))


def frontlyne_text(role):
    if role not in {"owner", "hr", "ops"}:
        return "Training: not included for this role."
    summary_path = _ROOT / "data" / "frontlyne" / "summary.json"
    store_path = _ROOT / "data" / "frontlyne" / "active_no_login_by_store.csv"
    lines = ["Frontlyne. Counts only. Individual names are not included."]
    if summary_path.is_file():
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        lines.append(str(payload.get("headline") or ""))
        lines.append(str(payload.get("totals") or ""))
    if store_path.is_file():
        rows = _read(store_path)
        rows.sort(key=lambda row: _num(row.get("active_no_login")) or 0, reverse=True)
        lines.append("Active users with no login, by store:")
        for row in rows[:12]:
            lines.append(f"{row.get('store')} | {row.get('active_no_login')}")
    lines.append(_course_completion())
    lines.append("Week-over-week change needs two weekly files. Only one drop is loaded, so the change is not stated. Any link to sales or reviews would be a correlation, and none is invented here.")
    return "\n".join(lines)


def _course_completion():
    """Mean course completion by store. Names and employee numbers are not written out."""
    try:
        return _course_completion_rows()
    except Exception:
        return "Course completion could not be read from the weekly workbook."


def _course_completion_rows():
    from openpyxl import load_workbook
    folder = _ROOT / "data" / "frontlyne" / "weekly"
    if not folder.is_dir():
        return "No Frontlyne weekly workbook is loaded."
    by_store = {}
    for path in sorted(folder.glob("Course_Status_*.xlsx")):
        book = load_workbook(path, read_only=True, data_only=True)
        sheet = book.active
        header = None
        store_at = course_at = pct_at = None
        seen = set()
        for raw in sheet.iter_rows(values_only=True):
            cells = [str(cell or "").strip() for cell in raw]
            if header is None:
                header = [cell.casefold() for cell in cells]
                for index, name in enumerate(header):
                    if "store name" in name:
                        store_at = index
                    elif name == "course title":
                        course_at = index
                    elif "completion" in name:
                        pct_at = index
                continue
            if store_at is None or pct_at is None:
                break
            store = cells[store_at] if store_at < len(cells) else ""
            course = cells[course_at] if course_at is not None and course_at < len(cells) else ""
            if not store:
                continue
            try:
                pct = float(str(cells[pct_at]).replace("%", ""))
            except (TypeError, ValueError):
                continue
            key = (store, course)
            if key in seen:
                continue
            seen.add(key)
            by_store.setdefault(store, []).append(pct)
        book.close()
    if not by_store:
        return "Course completion by store is not in the weekly file."
    ranked = sorted(by_store.items(), key=lambda item: sum(item[1]) / len(item[1]))
    lines = ["Mean course completion by store, from the weekly workbooks. Names are not listed."]
    for store, values in ranked[:8]:
        lines.append(f"{store} | {sum(values) / len(values):.1f}%")
    return "\n".join(lines)


def _asks_training(question):
    folded = (question or "").casefold()
    return any(token in folded for token in ("frontlyne", "training", "never logged", "no login"))


def reelo_text():
    from app.chat.reelo_deep import summary_text
    from app.chat.reelo_storewise import PERIOD, load_storewise

    rows = load_storewise()
    lines = [
        summary_text(),
        f"Monday storewise file, period {PERIOD}. That file still refreshes on its own.",
        "These stores are not on Reelo, so they are not shown as zero: " + ", ".join(_NOT_ON_REELO) + ".",
        "store | orders | new | repeat | repeat share % | phone capture %",
    ]
    for row in rows[:20]:
        lines.append(" | ".join([
            str(row.get("store") or ""),
            "" if row.get("orders") is None else str(row.get("orders")),
            "" if row.get("new_customers") is None else str(row.get("new_customers")),
            "" if row.get("repeat_customers") is None else str(row.get("repeat_customers")),
            "" if row.get("repeat_share") is None else str(row.get("repeat_share")),
            "" if row.get("phone_capture") is None else str(row.get("phone_capture")),
        ]))
    return "\n".join(lines)


def _asks_reelo_deep(question):
    folded = (question or "").casefold()
    if "phone" in folded or "captur" in folded or ("repeat" in folded and "lapsed" not in folded and "segment" not in folded):
        return False
    return any(token in folded for token in ("lapsed", "reelo deep", "not on reelo", "which stores are not on reelo", "campaign", "nps"))


def posist_text(question):
    folder = _ROOT / "data" / "posist" / "daily_sales"
    folded = (question or "").casefold()
    if any(token in folded for token in ("hourly", "daypart", "payment", "discount", "comp ", "void")):
        voids = sorted(folder.glob("unsettled_voids_*.csv")) if folder.is_dir() else []
        if "void" in folded and voids:
            rows = _read(voids[-1])
            lines = [f"Voids from {voids[-1].name}. Manisquare and Forum bill counts stay out of comparisons.", "store | date | type | count | amount"]
            for row in rows[:12]:
                if "mani" in (row.get("store") or "").casefold() or "forum" in (row.get("store") or "").casefold():
                    continue
                lines.append(" | ".join([row.get("store") or "", row.get("date") or "", row.get("type") or "", row.get("count") or "", row.get("amount") or ""]))
            return "\n".join(lines)
        return (
            "Hourly, daypart, payment-mode, and discount files are not in data/posist yet. "
            "Channel gross and voids are the slices that are loaded. No figure is invented for the missing ones."
        )
    files = sorted(folder.glob("channel_*.csv")) if folder.is_dir() else []
    if not files:
        return "Posist channel file is not loaded."
    rows = _read(files[-1])
    lines = [
        f"Channel sales from {files[-1].name}. Figures are gross. Manisquare and Forum bills are not used in a comparison.",
        "store | source | sales | orders",
    ]
    for row in rows[:15]:
        lines.append(" | ".join([
            row.get("store") or "",
            row.get("source") or "",
            row.get("sales") or "",
            row.get("orders") or "",
        ]))
    return "\n".join(lines)


def _asks_posist(question):
    folded = (question or "").casefold()
    if _asks_location(question) or "fix" in folded:
        return False
    return any(token in folded for token in ("channel sales", "by channel", "daypart", "hourly", "payment mix", "voids", "posist insight"))


def domain_text(question, role):
    parts = []
    if _asks_location(question):
        parts.append(location_text(question))
    if _asks_brands(question):
        parts.append(brands_text(question))
    if _asks_gaps(question):
        parts.append(gaps_text(question, role))
    if _asks_training(question):
        parts.append(frontlyne_text(role))
    if _asks_reelo_deep(question):
        parts.append(reelo_text())
    if _asks_posist(question):
        parts.append(posist_text(question))
    return "\n\n".join(part for part in parts if part)


def _asks_productivity(question):
    folded = (question or "").casefold()
    return any(token in folded for token in ("per employee", "understaff", "overstaff", "productivity", "sales per active"))


def productivity_text(role):
    if role not in {"owner", "hr"}:
        return "Staff productivity uses headcount, so it is not included for this role."
    hr = _ROOT / "data" / "hr"
    dated = sorted(path for path in hr.iterdir() if path.is_dir()) if hr.is_dir() else []
    if not dated:
        return "No Keka headcount file is loaded, so sales per employee is not stated."
    head = {}
    with (dated[-1] / "location_headcount.csv").open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            store = (raw.get("posist_store") or "").strip()
            if not store or (raw.get("match_status") or "") != "matched":
                continue
            try:
                active = int(float(raw.get("active") or ""))
            except ValueError:
                continue
            if active:
                head[store.casefold()] = (store, active)
    sales = {}
    path = _ROOT / "data" / "store_health" / "posist_daily.csv"
    if path.is_file():
        days = {}
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                gross = _num(raw.get("gross"))
                store = raw.get("store") or ""
                day = raw.get("date") or ""
                if gross is None or not day:
                    continue
                days.setdefault(store, []).append((day, gross))
        for store, points in days.items():
            points.sort()
            recent = points[-7:]
            if len(recent) < 5:
                continue
            sales[store.casefold()] = (store, sum(gross for _day, gross in recent), len(recent))
    lines = [
        f"Sales per active employee from Keka counts as of {dated[-1].name} and the latest Posist days. Gross is used. Mall bill counts are not.",
        "store | active | 7-day gross | per active employee",
    ]
    ratios = []
    for key, (label, active) in head.items():
        found = None
        for sale_key, value in sales.items():
            if key in sale_key or sale_key in key:
                found = value
                break
        if not found:
            continue
        _store, gross, count = found
        per = gross / active
        ratios.append(per)
        lines.append(f"{label} | {active} | {gross:.0f} over {count} days | {per:.0f}")
    if len(ratios) >= 4:
        ordered = sorted(ratios)
        mid = ordered[len(ordered) // 2]
        lines.append(f"Median sales per active employee across these stores is {mid:.0f} for that same window. A store far from this median is the flag. This is not a staffing recommendation by itself.")
    else:
        lines.append("Too few stores matched both files, so a median is not stated.")
    return "\n".join(lines)


def _asks_new_store(question):
    folded = (question or "").casefold()
    if _asks_location(question):
        return False
    return any(token in folded for token in ("payback", "capex", "break-even", "breakeven", "new store p"))


def new_store_text(question):
    import re
    numbers = [float(item.replace(",", "")) for item in re.findall(r"₹\s*([0-9][0-9,]*)", question or "")]
    rent = numbers[0] if numbers else None
    capex = numbers[1] if len(numbers) > 1 else None
    lines = [
        "New-store sketch. Closed stores, Faridabad from 23 Oct, and Rosedale from 1 Nov (partly open; closed 10 Nov) are not used as comparables.",
    ]
    if rent is None:
        lines.append("Rent was not given, so rent, EBITDA, and payback are not calculated. No rent is invented.")
    else:
        lines.append(f"Rent used is the figure you gave, ₹{rent:,.0f} a month.")
    if capex is None:
        lines.append("Capex was not given, so payback in months is not calculated.")
    else:
        lines.append(f"Capex used is the figure you gave, ₹{capex:,.0f}.")
    lines.append("A sales range needs the city's own recent gross. This answer does not turn a candidate area into a forecast.")
    return "\n".join(lines)


def try_answer(question, data, owner):
    role = data.get("role") or ("owner" if owner else "ops")
    if _asks_productivity(question):
        return _pack(productivity_text(role), "", "sales", question, owner)
    if _asks_new_store(question):
        return _pack(new_store_text(question), "", "finance", question, owner)
    if _asks_location(question):
        return _pack(location_text(question), "2026-10-10", "sales", question, owner)
    if _asks_brands(question):
        return _pack(brands_text(question), "2026-10-10", "sales", question, owner)
    if _asks_price(question):
        return price_answer(question, owner)
    if _asks_gaps(question):
        return _pack(gaps_text(question, role), "", "sales", question, owner)
    if _asks_training(question):
        return _pack(frontlyne_text(role), "3 Oct 2026", "sales", question, owner)
    if _asks_reelo_deep(question):
        return _pack(reelo_text(), "13 Oct to 12 Nov 2026", "reelo", question, owner)
    if _asks_posist(question):
        return _pack(posist_text(question), "", "sales", question, owner)
    return None
