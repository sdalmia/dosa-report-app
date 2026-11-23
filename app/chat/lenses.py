"""Extra readings for the packet. A missing file is skipped, not an error.

Optional files, used only when they are present:

- data/procurement/kolkata_variance_weekly_*.csv (latest)
- data/procurement/price_revision_review_*.md (latest)
- data/flags/procurement.csv
- data/forecast/* (store-level daily forecast)
- data/menu_mix/menu_mix_latest.csv
- data/posist_insights/ channel files
"""

import csv
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CLOSED = ("faridabad", "chattarpur", "gk1", "gk 1")
_CHANNELS = {
    "dinein": "dine-in",
    "takeout": "takeaway",
    "swiggyonline": "Swiggy",
    "zomatoonline": "Zomato",
}


_CACHE = {}


def lens_text(role="ops", root=None):
    """Short block for the model. Never raises."""
    base = Path(root) if root else _ROOT
    key = ("lens", role or "ops", str(base))
    if key in _CACHE:
        return _CACHE[key]
    try:
        text = _compose(role or "ops", base)[:6000]
    except Exception:
        text = "Extra readings: not loaded."
    _CACHE[key] = text
    return text


def bill_driver(root=None):
    """One sentence on whether bills or the average bill drove the largest move."""
    base = Path(root) if root else _ROOT
    key = ("driver", str(base))
    if key in _CACHE:
        return _CACHE[key]
    try:
        text = _bill_driver(base)
    except Exception:
        text = ""
    _CACHE[key] = text
    return text


def _compose(role, root):
    lines = ["Readings from Posist Insights and the other loaded files:"]
    driver = _bill_driver(root)
    lines.append(driver or "Bill count versus average bill: not loaded.")
    lines.append(_channel_shift(root))
    lines.append(_range_watch(root))
    lines.append(_menu_line(root))
    lines.append(_forecast_folder(root))
    lines.append(
        "Known gap: no Insights daily files from 4 Sep 2026 to 8 Oct 2026. "
        "Per-store net is blank. Insights has no net by store, so 24.78% of net is not turned into a rupee here."
    )
    lines.append(_loyalty(role, root))
    lines.append(_cost(root, role))
    from app.chat.guard import can_see_pl

    if can_see_pl(role, role == "owner"):
        lines.append(_finance(root))
    else:
        lines.append("Profit, rent, bank, inbox, and Tally are not included for this role.")
    return "\n".join(line for line in lines if line)


def _num(value):
    text = str(value or "").strip().replace(",", "").replace("%", "").replace("₹", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _closed(name):
    text = (name or "").casefold()
    return any(token in text for token in _CLOSED)


def _rosedale(name):
    return "rosedale" in (name or "").casefold()


def _mall(name):
    text = (name or "").casefold()
    return "manisquare" in text or "mani square" in text or "forum" in text


def _rupee(value):
    number = float(value)
    sign = "-" if number < 0 else ""
    return f"{sign}₹{abs(number) / 100000:.2f}L"


def _read_csv(path):
    if not path or not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def _latest(folder, pattern):
    if not folder.is_dir():
        return None
    found = sorted(path for path in folder.glob(pattern) if path.is_file())
    return found[-1] if found else None


def _day_from_name(path, prefix):
    text = path.stem.replace(prefix, "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _sales_files(root):
    folder = root / "data" / "posist" / "daily_sales"
    if not folder.is_dir():
        return []
    from app.chat.correctness import drop_pending

    rows = []
    for path in folder.glob("sales_*.csv"):
        day = _day_from_name(path, "sales_")
        if day and not drop_pending(day, root):
            rows.append((day, path))
    rows.sort()
    return rows


def _pending_note(root, days):
    """Only the latest expected day, and only when it sits inside this period."""
    from app.chat.correctness import day_status

    days = list(days or [])
    if not days:
        return ""
    start, end = min(days), max(days)
    notes = []
    for day in days:
        status = day_status(day, root=root, asked_start=start, asked_end=end)
        if not status:
            continue
        line = f"{status} No partial number from that day is used."
        if line not in notes:
            notes.append(line)
    return " ".join(notes)


def _windows(root):
    files = _sales_files(root)
    if not files:
        return None, None, ""
    latest = files[-1][0]
    recent_days = [latest - timedelta(days=offset) for offset in range(6, -1, -1)]
    prior_days = [recent_days[0] - timedelta(days=offset) for offset in range(7, 0, -1)]
    by_day = {day: path for day, path in files}
    label = f"{recent_days[0].isoformat()} to {latest.isoformat()}"
    return recent_days, prior_days, label, by_day


def _sum_window(days, by_day):
    """Gross and bills by store. A store missing from an export that exists is ₹0."""
    universe = set()
    loaded = {}
    present_days = [day for day in days if day in by_day]
    for day in present_days:
        seen = set()
        for row in _read_csv(by_day[day]):
            store = (row.get("store") or "").strip()
            if not store:
                continue
            seen.add(store)
            universe.add(store)
            bucket = loaded.setdefault(store, {"gross": 0.0, "bills": 0.0, "net_blank": True})
            gross = _num(row.get("gross"))
            bills = _num(row.get("bills"))
            if gross is not None:
                bucket["gross"] += gross
            if bills is not None:
                bucket["bills"] += bills
            if _num(row.get("net")) is not None:
                bucket["net_blank"] = False
        for store in universe:
            if store not in seen:
                loaded.setdefault(store, {"gross": 0.0, "bills": 0.0, "net_blank": True})
    return loaded, present_days


def _bill_driver(root):
    windows = _windows(root)
    if not windows or windows[0] is None:
        return ""
    recent_days, prior_days, label, by_day = windows
    recent, recent_present = _sum_window(recent_days, by_day)
    prior, prior_present = _sum_window(prior_days, by_day)
    pending = _pending_note(root, recent_days)
    if not recent_present or not prior_present:
        return pending
    best = None
    for store, now in recent.items():
        if _closed(store) or _rosedale(store):
            continue
        before = prior.get(store)
        if not before:
            continue
        gap = now["gross"] - before["gross"]
        if best is None or abs(gap) > abs(best["gap"]):
            best = {"store": store, "now": now, "before": before, "gap": gap}
    if not best:
        return pending
    now, before = best["now"], best["before"]
    if _mall(best["store"]):
        sentence = (
            f"{_short(best['store'])} gross moved {_rupee(best['gap'])} ({label}). "
            "Its bill count and average bill stay out of the comparison."
        )
        return f"{sentence} {pending}".strip()
    if not now["bills"] or not before["bills"]:
        sentence = (
            f"{_short(best['store'])} gross moved {_rupee(best['gap'])} ({label}). "
            "Bill count is blank, so the driver is not named."
        )
        return f"{sentence} {pending}".strip()
    apb_now = now["gross"] / now["bills"]
    apb_before = before["gross"] / before["bills"]
    bill_effect = (now["bills"] - before["bills"]) * apb_before
    apb_effect = now["bills"] * (apb_now - apb_before)
    driver = "bill count" if abs(bill_effect) >= abs(apb_effect) else "the average bill"
    direction = "down" if best["gap"] < 0 else "up"
    sentence = (
        f"{_short(best['store'])} gross is {direction} {_rupee(abs(best['gap']))} versus the previous 7 days ({label}). "
        f"{driver[0].upper()}{driver[1:]} drove it: bills {now['bills']:.0f} versus {before['bills']:.0f}, "
        f"average bill ₹{apb_now:.0f} versus ₹{apb_before:.0f}."
    )
    return f"{sentence} {pending}".strip()


def _channel_shift(root):
    insights = root / "data" / "posist_insights"
    folder = insights if insights.is_dir() and any(insights.glob("channel*.csv")) else root / "data" / "posist" / "daily_sales"
    if not folder.is_dir():
        return "Store-by-channel files are not loaded."
    from app.chat.correctness import channel_exceeds_gross, drop_pending

    files = []
    for path in folder.glob("channel*.csv"):
        day = _day_from_name(path, "channel_")
        if day is None:
            day = _day_from_name(path, "channel")
        if day and not drop_pending(day, root):
            files.append((day, path))
    files.sort()
    if len(files) < 2:
        return "Store-by-channel files are not loaded."
    latest = files[-1][0]
    recent_days = {latest - timedelta(days=offset) for offset in range(7)}
    prior_days = {latest - timedelta(days=offset) for offset in range(7, 14)}
    recent = _channel_totals(files, recent_days)
    prior = _channel_totals(files, prior_days)
    recent_gross = _store_gross(root, recent_days)
    prior_gross = _store_gross(root, prior_days)
    flagged = []
    best = None
    for store, now in recent.items():
        if _closed(store) or _rosedale(store) or store not in prior:
            continue
        before = prior[store]
        if not now["gross"] or not before["gross"]:
            continue
        if (
            channel_exceeds_gross(now["gross"], recent_gross.get(store))
            or channel_exceeds_gross(before["gross"], prior_gross.get(store))
        ):
            flagged.append(_short(store))
            continue
        now_share = now["delivery"] / now["gross"]
        before_share = before["delivery"] / before["gross"]
        shift = now_share - before_share
        if best is None or abs(shift) > abs(best["shift"]):
            best = {"store": store, "shift": shift, "now": now_share, "before": before_share, "delivery_gap": now["delivery"] - before["delivery"]}
    flag_note = ""
    if flagged:
        names = ", ".join(flagged[:4])
        flag_note = f" Channel total exceeds store gross for {names}, so that mix is not used."
    if not best:
        return "Store-by-channel mix: no two weeks to compare." + flag_note
    direction = "toward delivery" if best["shift"] > 0 else "toward dine-in and takeaway"
    return (
        f"{_short(best['store'])} mix moved {direction}: delivery was {best['before'] * 100:.1f}% of its gross, now {best['now'] * 100:.1f}%. "
        "Per-store net is blank, so the 24.78% take is not applied to this gross and the rupee margin effect is not sized."
        + flag_note
    )


def _store_gross(root, days):
    files = {day: path for day, path in _sales_files(root)}
    totals = {}
    for day in days:
        path = files.get(day)
        if not path:
            continue
        for row in _read_csv(path):
            store = (row.get("store") or "").strip()
            gross = _num(row.get("gross"))
            if store and gross is not None:
                totals[store] = totals.get(store, 0.0) + gross
    return totals


def _channel_totals(files, days):
    found = {}
    for day, path in files:
        if day not in days:
            continue
        for row in _read_csv(path):
            store = (row.get("store") or "").strip()
            source = _CHANNELS.get((row.get("source") or "").replace(" ", "").casefold())
            sales = _num(row.get("sales") or row.get("gross"))
            if not store or sales is None:
                continue
            bucket = found.setdefault(store, {"gross": 0.0, "delivery": 0.0})
            bucket["gross"] += sales
            if source in {"Swiggy", "Zomato"}:
                bucket["delivery"] += sales
    return found


def _range_watch(root):
    path = root / "data" / "store_health" / "sales_pred_vs_actual.csv"
    optional = _latest(root / "data" / "forecast", "*")
    source = optional if optional and optional.suffix.lower() == ".csv" else path
    if not source or not source.is_file():
        return "Forecast range: not loaded."
    by_store = {}
    for row in _read_csv(source):
        store = (row.get("store") or "").strip()
        day = _parse_day(row.get("date"))
        actual = _num(row.get("actual_gross") or row.get("actual"))
        low = _num(row.get("pred_low") or row.get("low"))
        high = _num(row.get("pred_high") or row.get("high"))
        if not store or day is None or actual is None or low is None or high is None:
            continue
        note = " ".join([row.get("tier") or "", row.get("drivers") or "", row.get("notes") or ""]).casefold()
        seasonal = ("navratri" in note or "chhath" in note) and _north(store)
        by_store.setdefault(store, []).append({
            "day": day,
            "weekday": row.get("weekday") or day.strftime("%A"),
            "outside": actual < low or actual > high,
            "seasonal": seasonal,
        })
    misses = []
    recovering = []
    reported = []
    for store, rows in by_store.items():
        if _closed(store):
            continue
        rows.sort(key=lambda item: item["day"])
        usable = [row for row in rows if not row["seasonal"]]
        pair = _two_running(usable)
        if _rosedale(store):
            if pair:
                reported.append(_short(store))
            continue
        if pair:
            misses.append(f"{_short(store)} {pair[0]['day'].isoformat()} and {pair[1]['day'].isoformat()} ({pair[1]['weekday']})")
        elif usable and not usable[-1]["outside"] and any(row["outside"] for row in usable[-8:-1]):
            recovering.append(_short(store))
    parts = []
    if misses:
        parts.append("Outside the forecast range two days running: " + "; ".join(misses[:3]) + ".")
    else:
        parts.append("No open store is outside its forecast range two days running.")
    if recovering:
        parts.append("Back inside the range: " + ", ".join(recovering[:3]) + ".")
    if reported:
        parts.append("Rosedale is in the export and is not flagged.")
    if optional:
        parts.append(f"Store-level forecast file {optional.name} is loaded.")
    return " ".join(parts)


def _two_running(rows):
    previous = None
    found = None
    for row in rows:
        if previous and row["outside"] and previous["outside"] and (row["day"] - previous["day"]).days == 1:
            found = (previous, row)
        previous = row
    return found


def _north(store):
    text = (store or "").casefold()
    return "(02/" in text or text.startswith("02") or "noida" in text or "gurgaon" in text or "delhi" in text


def _menu_line(root):
    path = root / "data" / "menu_mix" / "menu_mix_latest.csv"
    rows = _read_csv(path) if path.is_file() else []
    as_of = ""
    if not rows:
        try:
            from app.chat.menu_hr import newest_menu
            picked = newest_menu()
        except Exception:
            picked = None
        if not picked:
            return "Menu mix: not loaded."
        file_path, rows, meta = picked
        as_of = str((meta or {}).get("as_of") or "")
        path = file_path
    if not rows:
        return "Menu mix: not loaded."
    ranked = []
    north_as_of = ""
    other_as_of = ""
    for row in rows:
        gross = _num(row.get("gross") or row.get("total_sales"))
        if gross is None:
            continue
        city = (row.get("city") or "").casefold()
        end = row.get("date_to") or row.get("period_end") or as_of
        if "ncr" in city or "delhi" in city or str(row.get("store_code") or "").startswith("02"):
            if end and end > north_as_of:
                north_as_of = end
        elif end and end > other_as_of:
            other_as_of = end
        ranked.append((gross, row.get("store") or "", row.get("item") or "", end))
    if not ranked:
        return "Menu mix: not loaded."
    ranked.sort(reverse=True)
    gross, store, item, end = ranked[0]
    stale = ""
    if north_as_of and other_as_of and north_as_of < other_as_of:
        stale = f" North menu mix may be stale. Its as-of date is {north_as_of}."
    net = " Net by item is blank." if not any(_num(row.get("net_sales")) is not None for row in rows[:20]) else ""
    return f"Menu mix as of {end or 'unknown'}: {item} at {store} is the largest loaded item gross, {_rupee(gross)}.{stale}{net}"


def _forecast_folder(root):
    folder = root / "data" / "forecast"
    if not folder.is_dir() or not any(folder.iterdir()):
        return "Store-level forecast folder data/forecast is not loaded. The range above is the loaded pred low and pred high."
    return "Store-level forecast folder is loaded."


def _loyalty(role, root):
    try:
        from app.chat.reelo_storewise import load_storewise
        rows = load_storewise(root / "data" / "reelo" / "reelo_storewise_latest.csv")
    except Exception:
        rows = []
    shares = [row["repeat_share"] for row in rows if row.get("repeat_share") is not None]
    if not shares:
        line = "Reelo repeat share: not loaded."
    else:
        median = statistics.median(shares)
        lowest = min(rows, key=lambda row: row.get("repeat_share") if row.get("repeat_share") is not None else 10**9)
        line = (
            f"Reelo repeat share median is {median:.2f}%. "
            f"{lowest['store']} is {lowest['repeat_share']:.2f}%, the lowest loaded, against that median."
        )
    line += " " + _campaign(root)
    return line


def _campaign(root):
    files = sorted((root / "data" / "reelo").glob("**/campaigns_manual.csv")) if (root / "data" / "reelo").is_dir() else []
    if not files:
        return "Campaign results are pending. No campaign file is loaded."
    chosen = None
    for row in _read_csv(files[-1]):
        start = _parse_long_day(row.get("start"))
        audience = (row.get("stores") or row.get("sent") or "").strip()
        if start and audience:
            chosen = (start, row)
    if not chosen:
        return "Campaign results are pending. No campaign has both a send date and an audience."
    start, row = chosen
    visited = (row.get("customers_visited") or "").strip()
    revenue = (row.get("revenue") or "").strip()
    if not visited and not revenue:
        return f"Campaign '{row.get('campaign') or 'untitled'}' was sent {start.isoformat()}. Results are pending."
    before, after = _around(root, start)
    if before is None or after is None:
        return (
            f"Campaign '{row.get('campaign') or 'untitled'}' was sent {start.isoformat()} "
            f"to {row.get('stores') or 'the listed audience'}. Sales before versus after are pending."
        )
    return (
        f"Campaign '{row.get('campaign') or 'untitled'}' sent {start.isoformat()}: "
        f"network gross {_rupee(before)} in the 7 days before and {_rupee(after)} in the 7 days from the send date. "
        f"The campaign row records visited {visited or 'blank'} and revenue {revenue or 'blank'}."
    )


def _around(root, start):
    files = dict(_sales_files(root))
    def total(days):
        gross = 0.0
        seen = 0
        for day in days:
            path = files.get(day)
            if not path:
                continue
            seen += 1
            for row in _read_csv(path):
                value = _num(row.get("gross"))
                if value is not None:
                    gross += value
        return gross if seen >= 4 else None
    before_days = [start - timedelta(days=offset) for offset in range(7, 0, -1)]
    after_days = [start + timedelta(days=offset) for offset in range(7)]
    return total(before_days), total(after_days)


def _variance_line(path):
    """A Kolkata week is true food cost only when that row says it was counted."""
    if path is None:
        return "Kolkata weekly variance file is not loaded. An absent count flag is treated as uncounted."
    from app.chat.correctness import like_for_like, variance_basis, variance_label

    rows = _read_csv(path)
    if not rows:
        return (
            f"Kolkata variance file {path.name} has no rows. "
            "recipe use + booked wastage, no stock count"
        )
    labelled = []
    bases = []
    for row in rows:
        basis = variance_basis(row)
        bases.append(basis)
        week = row.get("week") or row.get("week_start") or row.get("date") or "that week"
        labelled.append(f"{week}: {variance_label(basis)}")
    if len(bases) >= 2 and like_for_like(bases[-2], bases[-1]):
        compare = " The latest two weeks both have a physical stock count, so they can be compared."
    elif len(bases) >= 2:
        compare = " These weeks are not compared like-for-like."
    else:
        compare = ""
    return f"Kolkata variance file {path.name}: " + "; ".join(labelled[:8]) + "." + compare


def _cost(root, role):
    from app.chat.guard import can_see_pl, flag_unconfirmed, unconfirmed_label

    parts = []
    flags = root / "data" / "flags" / "procurement.csv"
    flag_rows = _read_csv(flags) if flags.is_file() else []
    summary_flags = []
    summary_path = root / "data" / "procurement" / "procurement_summary.json"
    if summary_path.is_file():
        try:
            import json
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            summary_flags = list(payload.get("flags") or []) if isinstance(payload, dict) else []
        except (OSError, json.JSONDecodeError):
            summary_flags = []
    shown = 0
    held = 0
    for lead in list(flag_rows) + summary_flags:
        if not isinstance(lead, dict):
            continue
        if flag_unconfirmed(lead):
            if held < 2:
                parts.append(
                    f"Procurement flag ({lead.get('as_of') or 'date not on the row'}): {unconfirmed_label()}. "
                    "Its price is not used."
                )
                held += 1
            continue
        elif shown < 2 and (lead.get("title") or lead.get("item")):
            parts.append(
                f"Procurement flag ({lead.get('as_of') or 'date not on the row'}): {lead.get('title') or lead.get('item')}."
            )
            shown += 1
        if shown >= 2 and any(flag_unconfirmed(row) for row in summary_flags[:8]):
            break
    if not flag_rows and not summary_flags:
        parts.append("Procurement flags file is not loaded.")
    variance = _latest(root / "data" / "procurement", "kolkata_variance_weekly_*.csv")
    parts.append(_variance_line(variance))
    review = _latest(root / "data" / "procurement", "price_revision_review_*.md")
    if can_see_pl(role, role == "owner"):
        if review:
            try:
                excerpt = " ".join(review.read_text(encoding="utf-8").split())[:280]
            except OSError:
                excerpt = ""
            parts.append(f"Price revision note {review.name}: {excerpt}" if excerpt else f"Price revision note {review.name} is loaded.")
        else:
            parts.append("Price revision note is not loaded.")
    else:
        parts.append("Price revision notes are not included for this role.")
    wastage = _read_csv(root / "data" / "procurement" / "store_item_wastage_top.csv")
    if wastage:
        wastage.sort(key=lambda row: _num(row.get("total_wastage_amt")) or 0, reverse=True)
        top = wastage[0]
        amount = _num(top.get("total_wastage_amt"))
        parts.append(
            f"Largest loaded wastage line: {top.get('item_name') or 'item'} at {top.get('store') or 'the store'} "
            f"{_rupee(amount) if amount is not None else 'amount blank'}. "
            "That file is not labelled as a calendar month, so this is not called a monthly cost."
        )
    return " ".join(parts)


def _finance(root):
    path = root / "data" / "finance" / "grand_economics" / "grand_economics_tidy.csv"
    rows = _read_csv(path)
    if not rows:
        return "Economics file is not loaded, so profit and rent are not stated."
    latest = max((row.get("month") or "") for row in rows)
    stores = {}
    cities = {}
    for row in rows:
        if (row.get("month") or "") not in {latest, _prior_month(latest)}:
            continue
        line = row.get("line") or ""
        value = _num(row.get("value"))
        if value is None or line not in {"rent", "net_revenue", "fnb_cost"}:
            continue
        if (row.get("level") or "") == "store" and (row.get("store") or "").strip():
            if _closed(row.get("store")):
                continue
            bucket = stores.setdefault((row.get("city"), row.get("store"), row.get("month")), {})
            bucket[line] = value
        elif not (row.get("store") or "").strip():
            bucket = cities.setdefault((row.get("city"), row.get("month")), {})
            bucket[line] = value
    flags = []
    for (city, store, month), bucket in stores.items():
        if month != latest:
            continue
        sales = bucket.get("net_revenue")
        rent = bucket.get("rent")
        if not sales or rent is None:
            continue
        ratio = rent / sales * 100
        if ratio > 25:
            flags.append((ratio, f"{store} rent is {ratio:.1f}% of its own sales ({month})"))
    flags.sort(reverse=True)
    if flags:
        rent_line = "Rent above 25% of sales: " + "; ".join(item[1] for item in flags[:4]) + "."
    else:
        rent_line = f"No loaded store has rent above 25% of its own sales in {latest}."
    food_bits = []
    for city in ("Kolkata", "NCR"):
        now = cities.get((city, latest)) or {}
        prior = cities.get((city, _prior_month(latest))) or {}
        if now.get("net_revenue") and now.get("fnb_cost") is not None and prior.get("net_revenue") and prior.get("fnb_cost") is not None:
            now_pct = now["fnb_cost"] / now["net_revenue"] * 100
            prior_pct = prior["fnb_cost"] / prior["net_revenue"] * 100
            food_bits.append(f"{city} food cost {now_pct:.1f}% of its own net in {latest}, versus {prior_pct:.1f}% in {_prior_month(latest)}")
    food_line = ". ".join(food_bits)
    if food_line:
        food_line += ". Each city is compared with its own past month. NCR is higher on purpose (3 chutneys versus 1)."
    return rent_line + (" " + food_line if food_line else "")


def _prior_month(month):
    try:
        year, mon = month.split("-")
        stamp = date(int(year), int(mon), 1)
    except (TypeError, ValueError):
        return ""
    previous = stamp - timedelta(days=1)
    return f"{previous.year:04d}-{previous.month:02d}"


def _parse_day(value):
    text = str(value or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_long_day(value):
    head = str(value or "").split(",")[0].strip()
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def _short(name):
    text = str(name or "").split("(")[0].strip()
    return text or "That store"
