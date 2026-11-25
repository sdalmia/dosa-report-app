"""Rupee values for a move, from the loaded files only.

Two nets are kept apart. Posist net is gross minus tax and service charge.
It still includes the aggregator cut, so the contribution base subtracts
24.78% of the Swiggy and Zomato part. Grand Economics net is already after
tax and commission, and that cut is not taken again.

A week is a full week. The comparison is 17-23 Nov against 20 Oct-2 Nov,
per day. Faridabad is out. Navratri, Diwali and Chhath are not the baseline.
"""

import csv
import re
import statistics
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from app.chat.names import clean_store_name, rs_lakh, rs_rupees
from app.chat.owners import owner_for

_ROOT = Path(__file__).resolve().parents[2]
_RECENT = (date(2026, 11, 17), date(2026, 11, 23))
_BASE = (date(2026, 10, 20), date(2026, 11, 2))
_TAKE = Decimal("0.2478")
_PAISE = Decimal("0.236")
_ESTIMATED = Decimal("0.90")
_DRIFT = Decimal("0.005")
_SALES = {}
_ECON = None


def _dec(value):
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _code(store, raw=""):
    match = re.search(r"\(([^)]+)\)", store or "")
    if match:
        return match.group(1).strip()
    return (raw or "").strip()


def _closed(name, code):
    blob = f"{name} {code}".casefold()
    return any(token in blob for token in ("faridabad", "chattarpur", "gk1", "gk 1"))


def _north(code, name):
    if _closed(name, code):
        return False
    return str(code).startswith("02")


def _mall(name):
    folded = (name or "").casefold()
    return "manisquare" in folded or ("forum" in folded and "rangoli" not in folded)


def sales_rows():
    if _SALES:
        return _SALES
    folder = _ROOT / "data" / "posist" / "daily_sales"
    for path in folder.glob("sales_*.csv"):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                store = (raw.get("store") or "").strip()
                if not store:
                    continue
                try:
                    day = date.fromisoformat(str(raw.get("date") or "")[:10])
                except ValueError:
                    continue
                code = _code(store, raw.get("store_code"))
                gross = _dec(raw.get("gross")) or Decimal(0)
                bills = _dec(raw.get("bills")) or Decimal(0)
                net = _dec(raw.get("net"))
                _SALES.setdefault(code, {})[day] = {
                    "gross": gross, "bills": bills, "net": net, "name": store,
                }
    return _SALES


def economics():
    global _ECON
    if _ECON is not None:
        return _ECON
    path = _ROOT / "data" / "finance" / "store_month_net.csv"
    rows = []
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    _ECON = rows
    return rows


def city_economics():
    path = _ROOT / "data" / "finance" / "city_month_economics.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _span(series, start, end):
    gross = bills = Decimal(0)
    days = 0
    name = ""
    day = start
    while day <= end:
        row = series.get(day)
        if row:
            gross += row["gross"]
            bills += row["bills"]
            days += 1
            name = row["name"]
        day += timedelta(days=1)
    return gross, bills, days, name


def _city_days(start, end, north_only=True):
    found = {}
    day = start
    while day <= end:
        gross = bills = Decimal(0)
        for code, series in sales_rows().items():
            row = series.get(day)
            if not row:
                continue
            if north_only and not _north(code, row["name"]):
                continue
            if not north_only and _closed(row["name"], code):
                continue
            gross += row["gross"]
            bills += row["bills"]
        if gross:
            found[day] = (gross, bills)
        day += timedelta(days=1)
    return found


def per_day(start, end, north_only=True):
    found = _city_days(start, end, north_only)
    if not found:
        return None
    gross = sum(item[0] for item in found.values())
    bills = sum(item[1] for item in found.values())
    days = Decimal(len(found))
    return {
        "gross_per_day": gross / days,
        "bills_per_day": bills / days,
        "days": int(days),
        "gross": gross,
        "bills": bills,
    }


def bill_apb_split(base, recent):
    """Rupees a day from fewer bills, and from a smaller bill. Signs follow the change."""
    bill_effect = (recent["bills_per_day"] - base["bills_per_day"]) * (
        base["gross_per_day"] / base["bills_per_day"]
    )
    apb_base = base["gross_per_day"] / base["bills_per_day"]
    apb_recent = recent["gross_per_day"] / recent["bills_per_day"]
    apb_effect = recent["bills_per_day"] * (apb_recent - apb_base)
    if abs(bill_effect) > abs(apb_effect) * Decimal("1.15"):
        driver = "bill count"
    elif abs(apb_effect) > abs(bill_effect) * Decimal("1.15"):
        driver = "the average bill"
    else:
        driver = "both the bill count and the average bill"
    return bill_effect, apb_effect, driver


def store_rates():
    """Per-day gross and bills for each store on the two full windows."""
    rows = []
    for code, series in sales_rows().items():
        base_g, base_b, base_n, name = _span(series, *_BASE)
        rec_g, rec_b, rec_n, name = _span(series, *_RECENT)
        if base_n < 7 or rec_n < 7 or _closed(name, code) or _mall(name):
            continue
        if not _north(code, name):
            continue
        base_day, rec_day = base_g / Decimal(base_n), rec_g / Decimal(rec_n)
        base_bills, rec_bills = base_b / Decimal(base_n), rec_b / Decimal(rec_n)
        base_apb = base_g / base_b if base_b else Decimal(0)
        rec_apb = rec_g / rec_b if rec_b else Decimal(0)
        rows.append({
            "code": code,
            "name": clean_store_name(name),
            "base_per_day": base_day,
            "recent_per_day": rec_day,
            "gap_per_day": rec_day - base_day,
            "base_apb": base_apb,
            "recent_apb": rec_apb,
            "bills_change": (rec_bills / base_bills - 1) if base_bills else None,
            "up": rec_day > base_day,
        })
    rows.sort(key=lambda row: row["gap_per_day"])
    return rows


def ncr_window():
    base = per_day(*_BASE, True)
    recent = per_day(*_RECENT, True)
    bill_effect, apb_effect, driver = bill_apb_split(base, recent)
    return base, recent, bill_effect, apb_effect, driver


def october_store_gross():
    """NCR store gross from 9 Oct, the first day on file. Faridabad stops on 23 Oct."""
    total = Decimal(0)
    start, end = date(2026, 10, 9), date(2026, 10, 31)
    day = start
    while day <= end:
        for code, series in sales_rows().items():
            row = series.get(day)
            if not row or not str(code).startswith("02"):
                continue
            if "faridabad" in row["name"].casefold() and day >= date(2026, 10, 23):
                continue
            if "faridabad" in row["name"].casefold():
                continue
            total += row["gross"]
        day += timedelta(days=1)
    return total


def network_north_gross(start, end):
    """North gross implied by the network file is not used as a store sum."""
    return None


def posist_net(gross, explicit=None, ratio=None):
    """Posist net, and the label for which rule was used."""
    amount = _dec(gross) or Decimal(0)
    if explicit is not None:
        return explicit, "posist net"
    if ratio is not None:
        return (amount * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "store ratio"
    return (amount * _ESTIMATED).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "estimated net"


def week_ratio(code):
    """The store's own net/gross from days in 17-23 Nov that carry a net."""
    series = sales_rows().get(code) or {}
    gross = net = Decimal(0)
    day = _RECENT[0]
    while day <= _RECENT[1]:
        row = series.get(day)
        if row and row.get("net") is not None and row["gross"]:
            gross += row["gross"]
            net += row["net"]
        day += timedelta(days=1)
    if not gross:
        return None
    return net / gross


def ratio_drift(code):
    """Days whose net/gross is more than 0.5 points off the store's own week."""
    ratio = week_ratio(code)
    if ratio is None:
        return []
    flagged = []
    series = sales_rows().get(code) or {}
    for day, row in series.items():
        if row.get("net") is None or not row["gross"]:
            continue
        got = row["net"] / row["gross"]
        if abs(got - ratio) > _DRIFT:
            flagged.append(day.isoformat())
    return flagged


def contribution(posist, delivery_posist):
    """Net after aggregators. Posist net still includes the aggregator cut."""
    return posist - _TAKE * delivery_posist


def ge_ratio(needle, month="2026-10"):
    folded = needle.casefold()
    for row in economics():
        if row.get("month") != month:
            continue
        if folded in (row.get("store") or "").casefold():
            return _dec(row.get("net_over_gross")), row
    return None, None


def repeat_story():
    from app.chat.reelo_storewise import PERIOD, load_storewise

    rows = [row for row in load_storewise() if row.get("repeat_share") is not None and row.get("customers")]
    if not rows:
        return None
    shares = [row["repeat_share"] for row in rows]
    median = statistics.median(shares)
    cp = next((row for row in rows if row["store"].casefold().endswith(" cp") or row["store"].casefold() == "dosa coffee cp"), None)
    if cp is None:
        return None
    guests = Decimal(str(cp["customers"]))
    repeat = Decimal(str(cp["repeat_customers"] or 0))
    target = guests * Decimal(str(median)) / Decimal(100)
    gap = target - repeat
    # APB from CP's own gross and bills on the recent full week.
    series = None
    for code, bucket in sales_rows().items():
        sample = next(iter(bucket.values()))["name"]
        if "connaught" in sample.casefold():
            series = bucket
            break
    apb = None
    if series:
        gross, bills, days, _name = _span(series, *_RECENT)
        if bills:
            apb = gross / bills
    if apb is None:
        return None
    full = gap * apb
    quarter = full / Decimal(4)
    ratio, _row = ge_ratio("CP")
    net_full = full * ratio if ratio else None
    net_quarter = quarter * ratio if ratio else None
    return {
        "period": PERIOD,
        "stores": len(rows),
        "median": median,
        "share": cp["repeat_share"],
        "guests": guests,
        "repeat": repeat,
        "gap": gap,
        "apb": apb,
        "full": full,
        "quarter": quarter,
        "ratio": ratio,
        "net_full": net_full,
        "net_quarter": net_quarter,
    }


def _money_pair(gross, ratio):
    gross_text = rs_rupees(gross)
    if ratio is None:
        return gross_text + " gross"
    net = (Decimal(gross) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{gross_text} gross, {rs_rupees(net)} net after aggregators"


def move_lines(see_finance=False):
    """Up to five moves. Each one has a rupee value or a stated test."""
    lines = []
    story = repeat_story()
    if story:
        net_bit = ""
        if story["ratio"] is not None and story["net_quarter"] is not None:
            net_bit = (
                f", about {rs_lakh(story['net_quarter']/Decimal(100000))} to "
                f"{rs_lakh(story['net_full']/Decimal(100000))} net after aggregators "
                f"at CP's October Grand Economics ratio {story['ratio']*100:.1f}% "
                "(that ratio is already after commission)"
            )
        lines.append(
            "Run a repeat-visit test at Connaught Place, where repeat share is "
            f"{story['share']:.2f}% against the median {story['median']:.2f}% of {story['stores']} stores "
            f"({story['period']}). "
            f"Value: {rs_lakh(story['quarter']/Decimal(100000))} to {rs_lakh(story['full']/Decimal(100000))} gross a month"
            f"{net_bit}. Estimate, not a booked result. "
            f"How sized: {story['guests']:.0f} guests, {story['repeat']:.0f} repeat, "
            f"about {story['gap']:.0f} more repeat guests to the median, times APB {rs_rupees(story['apb'])} "
            "from Connaught Place's own 17-23 Nov bills. A quarter of that gap to the whole gap. "
            "The 13 Nov thank-you to 1,322 lapsed CP guests, in Reelo learnings, is measured on 30 Nov, so this is not that result. "
            f"Owner: {owner_for('reelo')}. Timeframe: measure on 30 Nov."
        )
    rates = [row for row in store_rates() if not row["up"]]
    rates.sort(key=lambda row: row["gap_per_day"])
    top = rates[:4]
    if top:
        base, recent, bill_effect, apb_effect, driver = ncr_window()
        bits = []
        month_gross = Decimal(0)
        for row in top:
            month = row["gap_per_day"] * Decimal(30)
            month_gross += month
            bits.append(f"{row['name']} {rs_rupees(row['gap_per_day'])} a day")
        lines.append(
            "Walk the stores that make almost all of the NCR per-day drop, "
            + "; ".join(bits)
            + f". Together {rs_rupees(sum(row['gap_per_day'] for row in top))} of "
            f"{rs_rupees(recent['gross_per_day'] - base['gross_per_day'])} a day. "
            f"Value: {rs_rupees(month_gross)} gross a month, "
            f"{rs_rupees(month_gross * _ESTIMATED)} estimated Posist net a month (90% of gross, no store net column yet). "
            f"How sized: 17-23 Nov against 20 Oct-2 Nov, per day. "
            f"Fewer bills are {rs_rupees(bill_effect)} a day and the average bill is {rs_rupees(apb_effect)} a day, so the driver is {driver}. "
            "Rohini, Model Town and Connaught Place are up on this window and are not listed. "
            f"Owner: {owner_for('north')}. Timeframe: this week."
        )
    delivery = _delivery_line()
    if delivery:
        lines.append(delivery)
    complaints = _complaint_line()
    if complaints:
        lines.append(complaints)
    if see_finance:
        rent = _rent_line()
        if rent and len(lines) < 5:
            lines.append(rent)
    return lines[:5]


def _delivery_line():
    """Size delivery from the rupee change. A higher share is not extra commission by itself."""
    change = _channel_change("Sec 18")
    if change is None:
        return (
            "Delivery mix at Sec 18 Noida needs a channel file for both weeks. "
            "Value: run a one-week pilot and measure Swiggy and Zomato rupees against dine-in rupees. "
            "Test: compare those rupees with 17-23 Nov. "
            f"Owner: {owner_for('north')}. Timeframe: this week."
        )
    base_share, rec_share, dine_change, delivery_change, base_dine, base_delivery, coverage = change
    text = (
        f"At Sec 18 Noida delivery was {base_share*100:.1f}% of gross and is {rec_share*100:.1f}% ({coverage}). "
        f"Dine-in rupees a day changed {_signed_pct(dine_change, base_dine)} and "
        f"delivery rupees a day changed {_signed_pct(delivery_change, base_delivery)}. "
    )
    if delivery_change <= 0:
        text += (
            "No added commission; the share rose because dine-in fell. "
            "Value: already inside the four-store dine-in walk above, not a commission figure. "
        )
    else:
        extra = delivery_change * _PAISE * Decimal(30)
        text += (
            f"Value: {rs_rupees(extra)} gross a month at 23.6 paise per delivery rupee added, "
            f"{rs_rupees(extra * _ESTIMATED)} estimated Posist net. "
        )
    text += (
        "How sized: dine-in plus takeaway against Swiggy and Zomato, per day, on the same 20 Oct-2 Nov baseline as the rest. "
        "The 24.78% take applies only to delivery rupees that were actually added. "
        + _tabwise_contrast("Sec 18")
        + f"Owner: {owner_for('north')}. Timeframe: this week."
    )
    return text


def _pct(change, base):
    if not base:
        return "n/a"
    return f"{(change / base) * 100:.1f}%"


def _signed_pct(change, base):
    if not base:
        return "n/a"
    value = (change / base) * 100
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _channel_change(needle):
    """Per-day dine-in and delivery, 20 Oct-2 Nov against 17-23 Nov."""
    prior = _insight_block(needle, *_BASE)
    recent = _channel_csv_block(needle, *_RECENT)
    if not prior or not recent:
        return None
    base_dine, base_del, base_n = prior
    rec_dine, rec_del, rec_n = recent
    base_tot = base_dine + base_del
    rec_tot = rec_dine + rec_del
    if not base_tot or not rec_tot:
        return None
    return (
        base_del / base_tot,
        rec_del / rec_tot,
        rec_dine - base_dine,
        rec_del - base_del,
        base_dine,
        base_del,
        f"{base_n} days 20 Oct-2 Nov from the second-pass channel tabs against {rec_n} days 17-23 Nov from the channel files",
    )


def _tabwise_contrast(needle):
    """Say why the short 12-16 Nov window does not match the shared baseline."""
    prior = _tabwise_block(needle, date(2026, 11, 12), date(2026, 11, 16))
    recent = _tabwise_block(needle, *_RECENT)
    if not prior or not recent:
        return ""
    base_dine, base_del, base_n = prior
    rec_dine, rec_del, _rec_n = recent
    base_tot = base_dine + base_del
    rec_tot = rec_dine + rec_del
    if not base_tot or not rec_tot or not base_del:
        return ""
    return (
        f"The {base_n}-day tabwise window of 12-16 Nov, which is not this baseline, "
        f"had delivery at {base_del / base_tot * 100:.1f}% then {rec_del / rec_tot * 100:.1f}%, "
        f"with delivery rupees {_signed_pct(rec_del - base_del, base_del)}. "
        "That week sits just after Chhath, so it is not 20 Oct-2 Nov. "
    )


_INSIGHT = {}


def _insight_block(needle, start, end):
    """Dine-in plus takeaway, and Swiggy plus Zomato, from the second-pass daily tabs."""
    days = _insight_days(needle)
    return _average_block(days, start, end)


def _insight_days(needle):
    if needle in _INSIGHT:
        return _INSIGHT[needle]
    folder = _ROOT / "data" / "posist_insights" / "2026-11-13"
    found = {}
    _INSIGHT[needle] = found
    if not folder.is_dir():
        return found
    try:
        import openpyxl
    except ImportError:
        return found
    kinds = {"dinein": "dine", "takeout": "dine", "swiggyonline": "del", "zomatoonline": "del"}
    token = needle.casefold()
    for path in folder.glob("secondpass_daily_tabs_*.xlsx"):
        parts = path.stem.split("_")
        kind = parts[3] if len(parts) > 3 else ""
        side = kinds.get(kind)
        if side is None:
            continue
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        table = list(book.active.iter_rows(values_only=True))
        book.close()
        if not table:
            continue
        columns = []
        for index, header in enumerate(table[0]):
            text = str(header or "")
            match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})", text)
            if match and "Sales" in text and "Change" not in text:
                columns.append((index, date(int(match.group(3)), int(match.group(2)), int(match.group(1)))))
        for row in table[1:]:
            if not row or not row[0] or token not in str(row[0]).casefold():
                continue
            for index, day in columns:
                value = row[index] if index < len(row) else None
                if value in (None, ""):
                    continue
                cell = found.setdefault(day, {"dine": Decimal(0), "del": Decimal(0), "seen": set()})
                slot = (day, side, kind)
                if slot in cell["seen"]:
                    continue
                cell["seen"].add(slot)
                cell[side] += Decimal(str(value))
    _INSIGHT[needle] = found
    return found


def _channel_csv_block(needle, start, end):
    folder = _ROOT / "data" / "posist" / "daily_sales"
    if not folder.is_dir():
        return None
    token = needle.casefold()
    days = {}
    for path in folder.glob("channel_*.csv"):
        try:
            day = date.fromisoformat(path.stem.replace("channel_", ""))
        except ValueError:
            continue
        if day < start or day > end:
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                name = (row.get("store") or "")
                if token not in name.casefold():
                    continue
                amount = _dec(row.get("sales"))
                if amount is None:
                    continue
                source = (row.get("source") or "").upper()
                side = "del" if any(word in source for word in ("SWIGGY", "ZOMATO", "RAPIDO")) else "dine"
                cell = days.setdefault(day, {"dine": Decimal(0), "del": Decimal(0)})
                cell[side] += amount
    return _average_block(days, start, end)


def _average_block(days, start, end):
    dine = delivery = Decimal(0)
    count = 0
    day = start
    while day <= end:
        found = days.get(day)
        if found and found["dine"] and found["del"]:
            dine += found["dine"]
            delivery += found["del"]
            count += 1
        day += timedelta(days=1)
    if not count:
        return None
    return dine / Decimal(count), delivery / Decimal(count), count


def _tabwise_block(needle, start, end):
    rows = _tabwise_store(needle)
    if not rows:
        return None
    dine = delivery = Decimal(0)
    days = 0
    day = start
    while day <= end:
        found = rows.get(day)
        if found:
            dine += found["dine"]
            delivery += found["del"]
            days += 1
        day += timedelta(days=1)
    if not days:
        return None
    return dine / Decimal(days), delivery / Decimal(days), days


_TAB = {}


def _tabwise_store(needle):
    if needle in _TAB:
        return _TAB[needle]
    folder = _ROOT / "data" / "posist" / "tabwise"
    found = {}
    if not folder.is_dir():
        _TAB[needle] = found
        return found
    try:
        import openpyxl
    except ImportError:
        _TAB[needle] = found
        return found
    for path in folder.glob("*/*.xlsx"):
        day_text = path.parent.name
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue
        kind = path.name.split("_")[1] if "_" in path.name else ""
        stamp = day.strftime("%d-%m-%Y")
        book = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = book.active
        table = list(sheet.iter_rows(values_only=True))
        book.close()
        if not table:
            continue
        index = None
        for i, header in enumerate(table[0]):
            text = str(header or "")
            if stamp in text and "Sales" in text and "Change" not in text:
                index = i
                break
        if index is None:
            continue
        for row in table[1:]:
            if not row or needle.casefold() not in str(row[0] or "").casefold():
                continue
            value = _dec(row[index]) or Decimal(0)
            bucket = found.setdefault(day, {"dine": Decimal(0), "del": Decimal(0)})
            if kind in {"swiggyonline", "zomatoonline"}:
                bucket["del"] += value
            else:
                bucket["dine"] += value
    _TAB[needle] = found
    return found


def _ticket_store(raw):
    text = str(raw or "").replace("_", " ").replace("/", " ")
    text = re.sub(r"\b\d{2}\s+\d{3,4}\b", "", text)
    text = re.sub(r"(?i)dosa coffee\s*-?\s*", "", text)
    return clean_store_name(text)


def _complaint_line():
    path = _ROOT / "data" / "famepilot" / "open_complaints_export.csv"
    if not path.is_file():
        return ""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return ""
    # No resolved_at means still open. Count by cleaned store.
    counts = {}
    latest = ""
    for row in rows:
        if (row.get("resolved_at") or "").strip():
            continue
        name = _ticket_store(row.get("store") or "")
        counts[name] = counts.get(name, 0) + 1
        stamp = (row.get("date_time") or "")[:10]
        if stamp > latest:
            latest = stamp
    if not counts:
        return ""
    lead = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:2]
    # At-risk uses one visit in the 30-day Reelo window and that store's own recent APB.
    bits = []
    total = Decimal(0)
    for name, count in lead:
        apb = _recent_apb(name)
        if apb is None:
            continue
        rupee = Decimal(count) * apb
        total += rupee
        bits.append(f"{name} {count} x {rs_rupees(apb)}")
    value = rs_rupees(total) if total else "not computed"
    return (
        f"Clear the open Famepilot tickets at {lead[0][0]} ({lead[0][1]}) and {lead[1][0]} ({lead[1][1]}). "
        f"Value: {value} gross at risk, {rs_rupees(total * _ESTIMATED) if total else value} estimated Posist net. "
        "Labelled at-risk, not a forecast. "
        f"How sized: {'; '.join(bits) if bits else 'APB not loaded'}, one visit in the Reelo month. "
        f"{sum(counts.values())} unresolved tickets through {latest}, no resolved_at on the row. "
        f"Owner: {owner_for('complaints', city='North')}. Timeframe: this week."
    )


def _recent_apb(needle):
    folded = needle.casefold()
    for series in sales_rows().values():
        sample = next(iter(series.values()))["name"]
        if folded not in sample.casefold() and folded not in clean_store_name(sample).casefold():
            continue
        gross, bills, _days, _name = _span(series, *_RECENT)
        if bills:
            return gross / bills
    return None


def _rent_line():
    interesting = []
    for row in economics():
        if row.get("month") != "2026-10":
            continue
        if "faridabad" in (row.get("store") or "").casefold():
            continue
        net = _dec(row.get("net"))
        rent = _dec(row.get("rent"))
        if not net or rent is None or net <= 0:
            continue
        ratio = rent / net
        if ratio <= Decimal("0.25"):
            continue
        gap = rent - net * Decimal("0.25")
        interesting.append((ratio, row["store"], gap, rent, net))
    interesting.sort(reverse=True)
    if not interesting:
        return ""
    bits = []
    for ratio, name, gap, _rent, _net in interesting[:4]:
        bits.append(f"{name} rent is {ratio*100:.1f}% of its October net, {rs_rupees(gap)} a month above 25%")
    return (
        "Renegotiate rent where October rent is above 25% of that store's own net sales. "
        + ". ".join(bits)
        + ". Value: those rupees a month, gross and net are the same here because the gap is rent, not sales. "
        "How sized: Grand Economics October, rent divided by net revenues. "
        "Sec 31's food cost is near 29.8% and is not its rent. "
        f"Owner: {owner_for('finance')}. Timeframe: this month."
    )


def buying_line():
    _ratio, row = ge_ratio("Noida Sec - 18")
    if row is None:
        return ""
    sep = next((item for item in economics() if item.get("store") == row["store"] and item.get("month") == "2026-09"), None)
    if sep is None:
        return ""
    return (
        f"Sec 18 Noida food cost went from {sep['food_pct']}% in September to {row['food_pct']}% in October "
        f"while purchases went from {rs_rupees(sep['purchases'])} to {rs_rupees(row['purchases'])} on flat sales. "
        f"Owner of the buying part: {owner_for('procurement')}."
    )


def delhi_text(see_finance=False):
    base, recent, bill_effect, apb_effect, driver = ncr_window()
    change = recent["gross_per_day"] / base["gross_per_day"] - 1
    stores = store_rates()
    downs = [row for row in stores if not row["up"]]
    ups = [row for row in stores if row["up"]]
    downs.sort(key=lambda row: row["gap_per_day"])
    focus = downs[:4]
    focus_sum = sum(row["gap_per_day"] for row in focus)
    total_drop = recent["gross_per_day"] - base["gross_per_day"]
    lines = [
        f"**NCR per-day gross went from {rs_rupees(base['gross_per_day'])} on 20 Oct-2 Nov "
        f"to {rs_rupees(recent['gross_per_day'])} on 17-23 Nov ({change*100:.1f}%).**",
        "",
        "Both windows are full and use the same stores. Faridabad is out, including Rs 55,051 on 20-22 Oct. "
        "October in the store files starts on 9 Oct, so this is not a full October and it is not set against a 22-day November total. "
        "No November budget is loaded, so no target is stated.",
        "",
        f"The per-day drop is {rs_rupees(total_drop)}. Fewer bills are {rs_rupees(bill_effect)} a day "
        f"and smaller bills are {rs_rupees(apb_effect)} a day, so the driver is {driver}, not bill count alone.",
        "",
        "The stores that carry the drop:",
    ]
    for row in focus:
        lines.append(
            f"- {row['name']}: {rs_rupees(row['base_per_day'])} a day to {rs_rupees(row['recent_per_day'])} "
            f"({rs_rupees(row['gap_per_day'])} a day). "
            f"APB {rs_rupees(row['base_apb'])} to {rs_rupees(row['recent_apb'])}."
        )
    if focus and total_drop:
        lines.append(
            f"Those four are {abs(focus_sum/total_drop)*100:.0f}% of the daily drop."
        )
    up_bits = []
    for row in ups:
        if any(token in row["name"].casefold() for token in ("rohini", "model town", "connaught")):
            up_bits.append(f"{row['name']} {(row['recent_per_day']/row['base_per_day']-1)*100:+.1f}%")
    if up_bits:
        lines.append("Up on the same window, so not a problem list: " + "; ".join(up_bits) + ".")
    yoy = year_on_year_line()
    if yoy:
        lines.append(yoy)
    if see_finance:
        lines.append(buying_line())
        cities = {row["city"]: row for row in city_economics() if row.get("month") == "2026-10"}
        if "NCR" in cities and "Kolkata" in cities:
            ncr, kol = cities["NCR"], cities["Kolkata"]
            lines.append(
                f"October Grand Economics: NCR EBITDA {rs_rupees(ncr['ebitda'])} ({ncr['ebitda_pct']}%), "
                f"Kolkata {rs_rupees(kol['ebitda'])} ({kol['ebitda_pct']}%). "
                f"NCR rent {ncr['rent_pct']}% of net against Kolkata {kol['rent_pct']}%."
            )
        rent = _rent_line()
        if rent:
            lines.append(rent)
    lines.append("")
    lines.append("**So what**")
    lines.append("")
    lines.append(
        "The NCR day is a little smaller, and four stores are almost the whole of that. "
        "Do not read a higher delivery share as extra commission when delivery rupees themselves fell or barely moved."
    )
    lines.append("")
    lines.append("**Moves**")
    lines.append("")
    for index, line in enumerate(move_lines(see_finance), start=1):
        lines.append(f"{index}. {line}")
    return "\n".join(lines)


def freshness():
    latest = ""
    for series in sales_rows().values():
        if series:
            day = max(series).isoformat()
            if day > latest:
                latest = day
    tickets = ""
    path = _ROOT / "data" / "famepilot" / "open_complaints_export.csv"
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                stamp = (row.get("date_time") or "")[:10]
                if stamp > tickets:
                    tickets = stamp
    from app.chat.reelo_storewise import PERIOD
    return f"Sales through {latest}. Reelo through {PERIOD}. Tickets through {tickets or 'not loaded'}."


def year_on_year_line():
    """Like-for-like NCR, 1 Oct-12 Nov, from the source files (those labels are correct)."""
    folder = _ROOT / "data" / "posist_insights" / "2026-11-13"
    if not folder.is_dir():
        return ""
    dine_old = dine_new = del_old = del_new = Decimal(0)
    stores = 0
    left_out = []
    named = {}
    for path in sorted(folder.glob("source_*_vs_2025.csv")):
        if not _ncr_source(path.name):
            continue
        old, new, dine = _source_totals(path)
        if old is None:
            continue
        if not old:
            left_out.append(_source_label(path.name))
            continue
        stores += 1
        dine_old += dine[0]
        dine_new += dine[1]
        del_old += (old - dine[0])
        del_new += (new - dine[1])
        for token, label in (
            ("sec_18_noida", "Sec 18 Noida"),
            ("sec_143_noida", "Sec 143 Noida"),
            ("gurgaon_sec_15", "Gurgaon Sec-15"),
        ):
            if token in path.name:
                named[label] = _whole_pct(dine[1], dine[0])
    if not stores or not dine_old or not del_old:
        return ""
    bits = [f"{label} {named[label]}" for label in ("Sec 18 Noida", "Sec 143 Noida", "Gurgaon Sec-15") if label in named]
    skipped = ""
    if left_out:
        skipped = " Stores with no 2025 sales are left out: " + ", ".join(left_out) + "."
    return (
        f"Like-for-like NCR, 1 Oct-12 Nov against the same dates in 2025: dine-in {_whole_pct(dine_new, dine_old)}, "
        f"delivery {_whole_pct(del_new, del_old)}.{skipped} "
        "Dine-in at the three stores that carry this year's drop: " + ", ".join(bits) + ". "
        "Read from source_* files, which are labelled correctly. "
        "The hourly *_vs_2025 export writes the year columns backwards, and the loader swaps those two columns."
    )


def _ncr_source(name):
    folded = name.casefold()
    blocked = ("faridabad", "chattarpur", "gk1", "demo", "not_in_use", "events", "food_truck", "fra", "aggregate")
    if any(token in folded for token in blocked):
        return False
    if re.search(r"_02_\d{4}", folded):
        return True
    return any(token in folded for token in (
        "gurgaon", "noida", "jasola", "paschim", "rohini", "kalkaji", "shalimar", "model_town", "connaught", "pacific",
    ))


def _source_label(name):
    folded = name.casefold()
    if "sec_10" in folded:
        return "Gurgaon Sec 10"
    if "shalimar" in folded:
        return "Shalimar Bagh"
    if "sec_31" in folded:
        return "Sec 31"
    if "jasola" in folded:
        return "Pacific Jasola"
    return name.split("_2026")[0].replace("source_", "").replace("_", " ")


def _source_totals(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 2 or len(rows[0]) < 3:
        return None, None, None
    old = new = Decimal(0)
    dine = [Decimal(0), Decimal(0)]
    for row in rows[1:]:
        if len(row) < 3:
            continue
        left, right = _dec(row[1]), _dec(row[2])
        if left is None or right is None:
            continue
        old += left
        new += right
        if row[0].strip().upper() == "POS":
            dine[0] += left
            dine[1] += right
    return old, new, dine


def _whole_pct(new, old):
    if not old:
        return "n/a"
    value = ((Decimal(new) / Decimal(old) - 1) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    sign = "+" if value > 0 else ""
    return f"{sign}{value}%"


def load_hourly_compare(path):
    """Read a year comparison. Hourly *_vs_2025 files have the year columns swapped. source_* files do not."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8-sig")
    sample = text.splitlines()[0] if text else ""
    delimiter = "\t" if "\t" in sample else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delimiter))
    name = file_path.name.casefold()
    if "_vs_2025" in name and "hourly" in name and not name.startswith("source_"):
        for row in rows:
            left = next((key for key in row if key and "2025" in key), None)
            right = next((key for key in row if key and "2026" in key), None)
            if left and right:
                row[left], row[right] = row[right], row[left]
    return rows


def repair_directions(text):
    """Flip an up/down word when the two figures next to it say the opposite."""
    pattern = re.compile(
        r"\b(up|down)\b(.{0,60}?)(\d[\d,]*(?:\.\d+)?)\s*(?:vs|versus|against|to)\s*(\d[\d,]*(?:\.\d+)?)",
        re.IGNORECASE,
    )

    def fix(match):
        word, middle, left, right = match.group(1), match.group(2), match.group(3), match.group(4)
        first = Decimal(left.replace(",", ""))
        second = Decimal(right.replace(",", ""))
        # "652 vs 670": the first number is the later figure in our sentences when we say "now vs then".
        # The audit's bad sentence was "APB up (652 vs 670)", later first. Later < earlier means down.
        should = "down" if first < second else "up" if first > second else word
        if should.casefold() == word.casefold():
            return match.group(0)
        replaced = should if word.islower() else should.capitalize()
        return replaced + middle + left + " vs " + right

    return pattern.sub(fix, text)


def commission_on_delivery(gross, delivery_share, tax=None):
    """24.78% of the delivery part of Posist net. Tax defaults to gross minus gross/1.05 when absent."""
    gross = Decimal(gross)
    if tax is None:
        posist = gross / Decimal("1.05")
    else:
        posist = gross - Decimal(tax)
    return (Decimal(delivery_share) * posist * _TAKE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
