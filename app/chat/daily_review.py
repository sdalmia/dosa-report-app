"""The ten-question daily review.

Store targets are Tony's November rows in store_targets.csv: Posist net,
monthly figure divided by 30, no channel split. The budget workbook is only
a cross-check. A store's own net column is used when Alfred has filled it.
Until then the store line is gross times that store's 17-23 Nov net/gross
ratio, or 90% of gross when that week has no net, and it is labelled
estimated net. A filled net that drifts more than 0.5 points from the week
ratio is flagged.
"""

import csv
import re
import statistics
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from app.chat.names import indian_digits
from app.targets import canonical_store_code

_ROOT = Path(__file__).resolve().parents[2]
_MONTH_DAYS = Decimal(30)
_FALLBACK = Decimal("0.90")
_DRIFT = Decimal("0.005")
_TAKE = Decimal("0.2478")
_BASE = (date(2026, 10, 20), date(2026, 11, 2))
_WEEK = (date(2026, 11, 17), date(2026, 11, 23))
_OPS = "Sanjoy Roy / Anup Ghosh"
_NCR = "Sumit Singh"
_BUY = "Sailesh"
_AUDIT = "Anup Ghosh / Sanjoy Roy"
_HR = "Prasmita"
_LOYALTY = "Logan"


def section_id(question):
    """Which daily-review section a question is, or '' when it is not one."""
    folded = " ".join((question or "").casefold().split())
    if any(phrase in folded for phrase in ("daily review", "how did we do")):
        return "all"
    checks = (
        ("target", ("vs sales target", "mtd vs budget", "yesterday vs target", "against the sales target")),
        ("growth", ("de-growing", "degrowing", "bills effect", "apc effect", "growing or")),
        ("outlets", ("underperforming", "recovery plan")),
        ("channel", ("channel performance",)),
        ("marketing", ("marketing planned", "marketing is planned", "campaign impact", "marketing plans")),
        ("reelo", ("new enrolment", "new enrollment", "reelo enrol")),
        ("quality", ("guest complaint", "hygiene")),
        ("cost", ("wastage", "opex")),
        ("people", ("manpower", "stock-out", "stock out", "pending maintenance")),
        ("actions", ("key action", "yesterday's commitment", "commitments closed")),
    )
    for name, phrases in checks:
        if any(phrase in folded for phrase in phrases):
            return name
    return ""


def answer_text(question, see_finance=False, see_hr=False, root=None, now=None):
    built = build(root or _ROOT, see_finance, see_hr, now)
    wanted = section_id(question)
    sections = built["sections"]
    if wanted and wanted != "all":
        sections = [row for row in sections if row["id"] == wanted]
    return _render(built["note"], sections)


def report_tables(question, see_finance=False, see_hr=False, root=None, now=None):
    built = build(root or _ROOT, see_finance, see_hr, now)
    wanted = section_id(question)
    sections = built["sections"]
    if wanted and wanted != "all":
        sections = [row for row in sections if row["id"] == wanted]
    tables = []
    for section in sections:
        rows = section.get("full_rows") or section["rows"]
        tables.append({
            "name": section["title"],
            "coverage": section["coverage"],
            "columns": section["columns"],
            "rows": rows or [["Not on file", section["owner"]]],
        })
    return tables


def build(root, see_finance=False, see_hr=False, now=None):
    root = Path(root)
    day, note = resolve_day(root, now)
    if day is None:
        missing = _pending_sections(note)
        return {"note": note, "day": None, "sections": missing}
    sales = _sales(root)
    targets = _targets(root, "2026-11")
    ratios = _week_ratios(sales)
    sections = [
        _target(root, day, sales, targets, ratios, see_finance),
        _growth(root, day, sales),
        _outlets(root, day, sales, targets, ratios, see_finance),
        _channel(root, day, sales),
        _marketing(root, day, see_finance),
        _reelo(root),
        _quality(root),
        _cost(root, sales, see_finance),
        _people(see_hr),
        _actions(root),
    ]
    return {"note": note, "day": day, "sections": sections}


def resolve_day(root, now=None):
    """Latest closed Posist day. A missing _DONE is not filled from a partial file."""
    from app.chat.correctness import day_is_loaded, latest_expected_day

    expected = latest_expected_day(now)
    if day_is_loaded(expected, root):
        return expected, ""
    loaded = []
    folder = Path(root) / "data" / "posist" / "daily_sales"
    if folder.is_dir():
        for path in folder.glob("_DONE_*"):
            try:
                found = date.fromisoformat(path.name.replace("_DONE_", ""))
            except ValueError:
                continue
            if found <= expected:
                loaded.append(found)
    if not loaded:
        return None, "yesterday's numbers land by 8:50 AM"
    latest = max(loaded)
    note = (
        f"{expected.isoformat()} isn't in yet. Yesterday's numbers land by 8:50 AM. "
        f"This review is the latest closed day, {latest.isoformat()}."
    )
    return latest, note


def money(value):
    """₹1.61 Cr, ₹9.85 L, or a grouped rupee amount."""
    number = Decimal(str(value or 0))
    sign = "-" if number < 0 else ""
    amount = abs(number)
    if amount >= Decimal(10000000):
        shown = (amount / Decimal(10000000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{sign}₹{shown} Cr"
    if amount >= Decimal(100000):
        shown = (amount / Decimal(100000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{sign}₹{shown} L"
    return f"{sign}₹{indian_digits(amount, 0)}"


def _pct(value):
    number = Decimal(str(value))
    sign = "+" if number > 0 else ""
    shown = (number * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{sign}{shown}%"


def _way(change, up="ahead", down="behind"):
    if change > 0:
        return up
    if change < 0:
        return down
    return "flat"


def _render(note, sections):
    parts = ["# Daily review", ""]
    if note:
        parts.extend([note, ""])
    for section in sections:
        parts.append(f"## {section['title']}")
        parts.append("")
        parts.append(f"**{section['verdict']}**")
        parts.append("")
        if section["rows"]:
            parts.append("| " + " | ".join(section["columns"]) + " |")
            parts.append("| " + " | ".join("---" for _ in section["columns"]) + " |")
            for row in section["rows"]:
                parts.append("| " + " | ".join(str(cell) for cell in row) + " |")
            parts.append("")
        parts.append(f"Why: {section['why']}")
        parts.append(f"Action: {section['action']} Owner: {section['owner']}.")
        parts.append(f"Coverage: {section['coverage']}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _pending_sections(note):
    titles = (
        ("target", "1. Yesterday vs sales target"),
        ("growth", "2. Growing or de-growing"),
        ("outlets", "3. Underperforming outlets"),
        ("channel", "4. Channel performance"),
        ("marketing", "5. Marketing"),
        ("reelo", "6. Reelo"),
        ("quality", "7. Quality and complaints"),
        ("cost", "8. Food cost, wastage, inventory"),
        ("people", "9. Manpower, stock-outs, maintenance"),
        ("actions", "10. Today's actions"),
    )
    rows = []
    for name, title in titles:
        if name in {"target", "growth", "channel"}:
            verdict = note or "yesterday's numbers land by 8:50 AM"
            owner = _NCR
        else:
            verdict = "Not on file — owner: " + _OPS
            owner = _OPS
        rows.append({
            "id": name,
            "title": title,
            "verdict": verdict,
            "columns": ["Note"],
            "rows": [],
            "why": "The day's _DONE marker is not in yet, so a partial file is not used.",
            "action": "Wait for Alfred's drop.",
            "owner": owner,
            "coverage": "not loaded",
        })
    return rows


def _dec(value):
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception:
        return None


def _closed(name, code):
    blob = f"{name} {code}".casefold()
    return any(token in blob for token in ("faridabad", "chattarpur", "gk1", "gk 1"))


def _mall(name):
    folded = (name or "").casefold()
    return "manisquare" in folded or "mani square" in folded or ("forum" in folded and "rangoli" not in folded)


def _rosedale(name):
    return "rosedale" in (name or "").casefold()


def _sales(root):
    folder = Path(root) / "data" / "posist" / "daily_sales"
    found = {}
    if not folder.is_dir():
        return found
    for path in folder.glob("sales_*.csv"):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                code = canonical_store_code(raw.get("store_code"))
                try:
                    day = date.fromisoformat(str(raw.get("date") or "")[:10])
                except ValueError:
                    continue
                gross = _dec(raw.get("gross"))
                if not code or gross is None:
                    continue
                found.setdefault(code, {})[day] = {
                    "gross": gross,
                    "net": _dec(raw.get("net")),
                    "bills": _dec(raw.get("bills")) or Decimal(0),
                    "name": (raw.get("store") or code).strip(),
                }
    return found


def _targets(root, month):
    path = Path(root) / "data" / "targets" / "store_targets.csv"
    rows = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            if (raw.get("month") or "").strip() != month:
                continue
            amount = _dec(raw.get("target_net"))
            code = canonical_store_code(raw.get("store_code"))
            if amount is None or not code or not amount:
                continue
            rows.append({
                "code": code,
                "name": (raw.get("budget_outlet_name") or code).strip(),
                "month": amount,
                "region": "North" if code.startswith("02") else "East",
            })
    return rows


def _week_ratios(sales):
    ratios = {}
    for code, series in sales.items():
        gross = net = Decimal(0)
        day = _WEEK[0]
        while day <= _WEEK[1]:
            row = series.get(day)
            if row and row.get("net") is not None and row["gross"]:
                gross += row["gross"]
                net += row["net"]
            day += timedelta(days=1)
        ratios[code] = (net / gross) if gross else None
    return ratios


def _store_net(gross, explicit, ratio):
    """Real net when the column is filled. Otherwise estimated net."""
    if explicit is not None:
        label = "posist net"
        if ratio is not None and gross:
            got = explicit / gross
            if abs(got - ratio) > _DRIFT:
                label = f"posist net, drift {(got - ratio) * 100:.1f} pts vs the 17-23 Nov ratio"
        return explicit, label
    if ratio is not None:
        amount = (gross * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return amount, "estimated net"
    amount = (gross * _FALLBACK).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return amount, "estimated net"


def _span(series, start, end):
    gross = bills = Decimal(0)
    days = 0
    name = ""
    day = start
    while day <= end:
        row = series.get(day)
        if row and not _closed(row["name"], ""):
            gross += row["gross"]
            bills += row["bills"]
            days += 1
            name = row["name"]
        day += timedelta(days=1)
    if not days:
        return None
    return {"gross": gross, "bills": bills, "days": days, "name": name, "per_gross": gross / days, "per_bills": bills / days}


def _network_on(root, day):
    path = Path(root) / "data" / "posist" / "daily_sales" / f"network_{day.isoformat()}.csv"
    found = {}
    if not path.is_file():
        return found
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            region = (raw.get("region") or "").strip()
            net = _dec(raw.get("net"))
            if region and net is not None:
                found[region] = {"net": net, "gross": _dec(raw.get("gross")) or Decimal(0), "bills": _dec(raw.get("bills")) or Decimal(0)}
    return found


def _month_net(root, start, end):
    """Posist net by day. The network file wins. The prediction file fills a gap."""
    found = {}
    folder = Path(root) / "data" / "posist" / "daily_sales"
    if folder.is_dir():
        for path in folder.glob("network_*.csv"):
            try:
                day = date.fromisoformat(path.stem.replace("network_", ""))
            except ValueError:
                continue
            if start <= day <= end:
                regions = _network_on(root, day)
                if "Total" in regions:
                    found[day] = regions
    pred = Path(root) / "data" / "posist" / "sales_pred_vs_actual.csv"
    if pred.is_file():
        with pred.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                try:
                    day = date.fromisoformat(str(raw.get("date") or "")[:10])
                except ValueError:
                    continue
                if day < start or day > end or day in found:
                    continue
                lakhs = _dec(raw.get("actual_net_L"))
                if lakhs is None:
                    continue
                found[day] = {"Total": {"net": lakhs * Decimal(100000), "gross": Decimal(0), "bills": Decimal(0)}}
    return found


def _budget_rows(root):
    path = Path(root) / "data" / "targets" / "nov_2026_store_sales_budget.xlsx"
    if not path.is_file():
        return []
    try:
        import openpyxl
    except ImportError:
        return []
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = book["Monthly Input"] if "Monthly Input" in book.sheetnames else book.active
    rows = []
    for index, raw in enumerate(sheet.iter_rows(values_only=True)):
        if index < 5 or not raw or raw[0] is None:
            continue
        stamp = raw[0]
        if not isinstance(stamp, datetime) or stamp.year != 2026 or stamp.month != 11:
            continue
        amount = _dec(raw[4])
        rows.append({
            "region": str(raw[2] or ""),
            "store": str(raw[3] or ""),
            "net": amount if amount is not None else Decimal(0),
        })
    book.close()
    return rows


def _cross_check(targets, budget):
    """Tony's file is the source. The workbook only confirms it."""
    by_name = {row["name"].casefold(): row for row in targets}
    unmatched = []
    mismatches = []
    for row in budget:
        label = row["store"].split("/")[-1].strip()
        if not row["net"]:
            unmatched.append(f"{label} (₹0, not in the 29)")
            continue
        hit = by_name.get(label.casefold())
        if hit is None:
            unmatched.append(label)
            continue
        if abs(hit["month"] - row["net"]) > 1:
            mismatches.append(f"{label} {money(hit['month'])} vs workbook {money(row['net'])}")
    return unmatched, mismatches


def _target(root, day, sales, targets, ratios, see_finance):
    title = "1. Yesterday vs sales target"
    coverage = f"network_{day.isoformat()}.csv; store_targets.csv month 2026-11; sales through {day.isoformat()}"
    if not targets:
        return _blank(title, "target", "November store targets are not on file.", _OPS, coverage)
    regions = _network_on(root, day)
    total = regions.get("Total")
    month_target = sum(row["month"] for row in targets)
    daily = month_target / _MONTH_DAYS
    start = date(day.year, day.month, 1)
    month = _month_net(root, start, day)
    mtd = sum(item["Total"]["net"] for item in month.values())
    mtd_target = month_target * Decimal(len(month) or 1) / _MONTH_DAYS
    if total is None:
        verdict = f"Not on file — owner: {_NCR}. {day.isoformat()} network net is not on file."
        rows = []
        why = "City pace needs the network file. Store gross is not used as net."
    else:
        gap = total["net"] - daily
        pace = mtd / mtd_target if mtd_target else Decimal(0)
        verdict = (
            f"{_way(gap).capitalize()}: {day.isoformat()} network Posist net {money(total['net'])} "
            f"against a daily target of {money(daily)} ({_pct(gap / daily) if daily else 'n/a'})."
        )
        if not see_finance:
            verdict = (
                f"{day.isoformat()} network Posist net is {money(total['net'])}. "
                "The November sales budget is on the owner login."
            )
        rows = []
        if see_finance:
            for region in ("East", "North"):
                part = regions.get(region)
                region_target = sum(row["month"] for row in targets if row["region"] == region) / _MONTH_DAYS
                if part is None:
                    rows.append([region, "Not on file", money(region_target), ""])
                    continue
                rows.append([
                    region,
                    money(part["net"]),
                    money(region_target),
                    _way(part["net"] - region_target),
                ])
            rows.append(["Network MTD", money(mtd), money(mtd_target), f"{pace * 100:.1f}% of pro-rata"])
        why = (
            f"MTD is {len(month)} days, the same day count as the pro-rata of the monthly budget, not a full month against a partial one. "
            f"At this pace the month lands near {money(mtd / Decimal(len(month) or 1) * _MONTH_DAYS)}. "
            f"The remaining target needs {money((month_target - mtd) / max(_MONTH_DAYS - Decimal(len(month)), 1))} a day."
        )
    store_rows = []
    ratio_missing = 0
    for target in targets:
        series = sales.get(target["code"]) or {}
        row = series.get(day)
        if row is None or _closed(row["name"], target["code"]):
            continue
        amount, label = _store_net(row["gross"], row.get("net"), ratios.get(target["code"]))
        if label == "estimated net" and ratios.get(target["code"]) is None:
            ratio_missing += 1
        daily_target = target["month"] / _MONTH_DAYS
        store_rows.append((amount - daily_target, [
            target["name"], money(row["gross"]), money(amount), money(daily_target), _way(amount - daily_target), label,
        ]))
    store_rows.sort(key=lambda item: item[0])
    short = [item[1] for item in store_rows[:8]]
    full = [item[1] for item in store_rows]
    unmatched, mismatches = _cross_check(targets, _budget_rows(root))
    if see_finance and ratio_missing:
        why += (
            f" {ratio_missing} store lines are estimated net at 90% of gross, because the 17-23 Nov net column is blank "
            "and that store's own week ratio cannot be read yet. A filled net column replaces this, and a drift over 0.5 points is flagged."
        )
    elif see_finance:
        why += " Store lines use each store's own 17-23 Nov net/gross ratio and are labelled estimated net until the net column is filled."
    if not see_finance:
        why = "Target rupees are on the owner login. " + why
        short, full = [], []
    elif unmatched:
        why += " Workbook rows not in Tony's 29: " + ", ".join(unmatched) + "."
    if see_finance and mismatches:
        why += " Workbook mismatches: " + "; ".join(mismatches) + "."
    columns = ["Store", "Gross", "Net", "Daily target", "Versus target", "Basis"]
    if not see_finance:
        columns = ["Note"]
    return {
        "id": "target",
        "title": title,
        "verdict": verdict,
        "columns": columns if see_finance else ["Region", "Posist net"],
        "rows": short if see_finance else [[region, money(regions[region]["net"])] for region in ("East", "North", "Total") if region in regions],
        "full_rows": full if see_finance else None,
        "why": why,
        "action": "Sumit sends the store net column with the next drop so these lines stop being estimated." if see_finance else "Ask the owner login for the budget comparison.",
        "owner": _NCR,
        "coverage": coverage + "; no November channel split on the target",
    }


def _growth(root, day, sales):
    title = "2. Growing or de-growing"
    base = _pool(sales, *_BASE, malls=False)
    latest = _pool_day(sales, day, malls=False)
    week = _pool(sales, *_WEEK, malls=False)
    if not base or not latest:
        return _blank(title, "growth", "A baseline week or the review day is not on file.", _NCR, f"sales through {day.isoformat()}")
    gross_change = latest["gross"] - base["per_gross"]
    bill_effect = (latest["bills"] - base["per_bills"]) * base["apc"]
    apc_effect = latest["bills"] * (latest["apc"] - base["apc"])
    verdict = (
        f"{_way(gross_change, 'Growing', 'De-growing')}: {day.isoformat()} gross {money(latest['gross'])} "
        f"versus the 20 Oct-2 Nov per day {money(base['per_gross'])} ({_pct(gross_change / base['per_gross'])})."
    )
    rows = [[
        "Network ex malls",
        money(gross_change),
        money(bill_effect),
        money(apc_effect),
        _way(bill_effect, "up", "down"),
        _way(apc_effect, "up", "down"),
    ]]
    store_bits = []
    for code, series in sales.items():
        sample = next(iter(series.values()))
        if _closed(sample["name"], code) or _mall(sample["name"]) or _rosedale(sample["name"]):
            continue
        window = _span(series, *_BASE)
        today = series.get(day)
        if not window or today is None or not window["per_bills"]:
            continue
        base_apc = window["per_gross"] / window["per_bills"]
        change = today["gross"] - window["per_gross"]
        bills_effect = (today["bills"] - window["per_bills"]) * base_apc
        price_effect = today["bills"] * ((today["gross"] / today["bills"]) - base_apc) if today["bills"] else Decimal(0)
        store_bits.append((change, sample["name"], bills_effect, price_effect))
    store_bits.sort(key=lambda item: item[0])
    for change, name, bills_effect, price_effect in store_bits[:5]:
        rows.append([
            name, money(change), money(bills_effect), money(price_effect),
            _way(bills_effect, "up", "down"), _way(price_effect, "up", "down"),
        ])
    brief = Path(root) / "data" / "posist" / f"brief_{day.isoformat()}.md"
    if brief.is_file():
        reason = " ".join(brief.read_text(encoding="utf-8").split())[:400]
    else:
        reason = f"No reason is recorded. posist/brief_{day.isoformat()}.md is not on file."
    week_line = ""
    if week and base["per_gross"]:
        week_change = week["per_gross"] - base["per_gross"]
        week_line = (
            f" Full week per day, 17-23 Nov versus 20 Oct-2 Nov, is {_way(week_change, 'up', 'down')} "
            f"{money(week_change)} a day ({_pct(week_change / base['per_gross'])})."
        )
    yoy = _yoy(root)
    return {
        "id": "growth",
        "title": title,
        "verdict": verdict,
        "columns": ["Store", "Gross vs own baseline", "Bills effect", "APC effect", "Bills", "APC"],
        "rows": rows,
        "why": (
            "Gross change splits into a bills effect and an APC effect against the store's own 20 Oct-2 Nov per day. "
            "Manisquare and Forum bills and APC are left out; their gross still sits in the sales total. "
            "Rosedale is partly open and is not listed."
            + week_line + " " + reason + " " + yoy
        ),
        "action": "Walk the stores whose bills effect and APC effect are both down.",
        "owner": _NCR,
        "coverage": f"sales_{day.isoformat()}.csv; baseline 20 Oct-2 Nov; brief coverage is the file date or not on file",
    }


def _pool(sales, start, end, malls):
    gross = bills = Decimal(0)
    days = set()
    for code, series in sales.items():
        sample = next(iter(series.values()))
        if _closed(sample["name"], code):
            continue
        if not malls and _mall(sample["name"]):
            continue
        day = start
        while day <= end:
            row = series.get(day)
            if row:
                gross += row["gross"]
                bills += row["bills"]
                days.add(day)
            day += timedelta(days=1)
    if not days or not bills:
        return None
    count = Decimal(len(days))
    return {"gross": gross, "bills": bills, "per_gross": gross / count, "per_bills": bills / count, "apc": gross / bills}


def _pool_day(sales, day, malls):
    gross = bills = Decimal(0)
    seen = False
    for code, series in sales.items():
        row = series.get(day)
        if not row or _closed(row["name"], code):
            continue
        if not malls and _mall(row["name"]):
            continue
        gross += row["gross"]
        bills += row["bills"]
        seen = True
    if not seen or not bills:
        return None
    return {"gross": gross, "bills": bills, "apc": gross / bills}


def _yoy(root):
    folder = Path(root) / "data" / "posist_insights" / "2026-11-13"
    if not folder.is_dir() or Path(root).resolve() != _ROOT.resolve():
        return "Year-on-year is not on file — owner: " + _NCR + "."
    from app.chat.sizing import year_on_year_line
    return year_on_year_line()


def _outlets(root, day, sales, targets, ratios, see_finance):
    title = "3. Underperforming outlets"
    bits = []
    for code, series in sales.items():
        sample = next(iter(series.values()))
        if _closed(sample["name"], code) or _rosedale(sample["name"]) or _mall(sample["name"]):
            continue
        window = _span(series, *_BASE)
        recent = _span(series, *_WEEK)
        if not window or not recent:
            continue
        gap = recent["per_gross"] - window["per_gross"]
        if gap >= 0:
            continue
        bits.append((gap, sample["name"], code, window["per_gross"], recent["per_gross"]))
    bits.sort(key=lambda item: item[0])
    rows = []
    for gap, name, code, base, recent in bits[:4]:
        target = next((row for row in targets if row["code"] == code), None)
        versus = "Not on file"
        if target and see_finance:
            today = (sales.get(code) or {}).get(day)
            if today:
                amount, label = _store_net(today["gross"], today.get("net"), ratios.get(code))
                versus = f"{_way(amount - target['month'] / _MONTH_DAYS)} {label}"
        elif target:
            versus = "budget on the owner login"
        rows.append([name, money(base), money(recent), money(gap), versus])
    email = _ops_email(root)
    if not bits:
        verdict = f"No outlet is below its own 20 Oct-2 Nov per day. {email}"
    else:
        verdict = f"Behind: {len(bits)} outlets are below their own baseline. The largest is {bits[0][1]} at {money(bits[0][0])} a day."
    return {
        "id": "outlets",
        "title": title,
        "verdict": verdict,
        "columns": ["Store", "Baseline / day", "17-23 Nov / day", "Gap / day", "Versus target"],
        "rows": rows,
        "why": "Ranked on gross per day, 17-23 Nov against 20 Oct-2 Nov. " + email,
        "action": "No recovery plan is written here. The Ops email is the plan.",
        "owner": _OPS,
        "coverage": "sales files 20 Oct-2 Nov and 17-23 Nov; Ops email file or not on file",
    }


def _ops_email(root):
    found = []
    for folder in (Path(root) / "data" / "posist", Path(root) / "data" / "chat"):
        if folder.is_dir():
            found.extend(folder.glob("ops_email*"))
    if not found:
        return f"Not on file — owner: {_OPS}. No Ops email is on file, so whether Sanjoy replied is not known."
    text = found[-1].read_text(encoding="utf-8", errors="replace")
    replied = "Sanjoy replied" if "sanjoy" in text.casefold() and "reply" in text.casefold() else "No Sanjoy reply is in the file"
    return f"{found[-1].name}: {replied}. " + " ".join(text.split())[:300]


def _channel(root, day, sales):
    title = "4. Channel performance"
    today = _channel_day(root, day)
    if not today:
        return _blank(
            title, "channel",
            "Not on file — owner: " + _NCR + ". No store channel file for this day. Nothing is on file for 1-9 Oct.",
            _NCR, "channel file missing",
        )
    gross = sum(today.values())
    rows = []
    for name in ("Dine-in", "Takeaway", "Swiggy", "Zomato", "Other"):
        amount = today.get(name) or Decimal(0)
        if name == "Other" and not amount:
            continue
        share = amount / gross if gross else Decimal(0)
        net = "n/a"
        if name in {"Swiggy", "Zomato"}:
            net = "net after 24.78% needs store Posist net, which is blank"
        rows.append([name, money(amount), f"{share * 100:.1f}%", net])
    delivery = (today.get("Swiggy") or Decimal(0)) + (today.get("Zomato") or Decimal(0))
    share = delivery / gross if gross else Decimal(0)
    verdict = f"Delivery is {share * 100:.1f}% of {day.isoformat()} channel gross ({money(delivery)} of {money(gross)})."
    return {
        "id": "channel",
        "title": title,
        "verdict": verdict,
        "columns": ["Channel", "Gross", "Share", "Net after 24.78%"],
        "rows": rows,
        "why": (
            "Swiggy and Zomato are the aggregator cut. The 24.78% is not applied to gross, and store Posist net is blank, "
            "so the net-after-cut column is not stated. There is no channel file for 1-9 Oct. "
            "November targets have no dine-in or aggregator split."
        ),
        "action": "Read the cut off Posist net once the store net column is in the drop.",
        "owner": _NCR,
        "coverage": f"channel_{day.isoformat()}.csv",
    }


def _channel_day(root, day):
    path = Path(root) / "data" / "posist" / "daily_sales" / f"channel_{day.isoformat()}.csv"
    if not path.is_file():
        return {}
    found = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            name = raw.get("store") or ""
            if "ALL" in name.upper() or not (raw.get("store_code") or "").strip():
                continue
            if _closed(name, raw.get("store_code") or ""):
                continue
            amount = _dec(raw.get("sales"))
            if amount is None:
                continue
            source = (raw.get("source") or "").upper()
            if "SWIGGY" in source:
                key = "Swiggy"
            elif "ZOMATO" in source:
                key = "Zomato"
            elif "TAKE" in source:
                key = "Takeaway"
            elif source in {"DINEIN", "POS"}:
                key = "Dine-in"
            else:
                key = "Other"
            found[key] = found.get(key, Decimal(0)) + amount
    return found


def _marketing(root, day, see_finance=False):
    title = "5. Marketing"
    lifts = _marketing_lift(root)
    activities = _marketing_activities(root)
    plans = _marketing_plans(root)
    rows = []
    full = []
    if lifts:
        verdict = "No measurable lift yet."
        if any(row["verdict"].casefold() == "within noise" for row in lifts):
            verdict = "No measurable lift yet. One comparison is within noise."
        for row in lifts:
            attributed = "—"
            if row["reelo"]:
                attributed = f"{money(row['reelo'])} Reelo-attributed, not measured lift"
            rows.append([row["activity"], row["posist"] or "—", attributed, row["verdict"]])
        full.extend(rows)
    elif plans["status"] == "lift":
        verdict = f"Lift is on file: {plans['summary']}"
        rows = plans["rows"]
        full = list(rows)
    else:
        verdict = "Impact not measured yet."
        rows = plans["rows"]
        full = list(rows)
    why = []
    if activities and see_finance:
        why.append(_budget_sentence(activities))
        for head in activities["heads"]:
            october = head["october"]
            full.append([
                head["name"],
                money(head["november"]),
                money(october) + " October" if october is not None else "October not on this row",
                "budget, not a measured lift",
            ])
    elif activities:
        why.append("Marketing spend is on the owner login.")
    for item in (activities or {}).get("activities") or []:
        if item["month"] != "2026-11":
            continue
        when = item["start"] or "date not on the row"
        full.append([item["name"], when, item["where"], _status_label(item["status"])])
    if not lifts:
        why.append(plans["summary"])
    why.append(
        "No dated store and channel plan is on file. Asked of Sanjoy and Nikita, due 27 Nov. "
        "Aggregator Ads ROAS is not on file. "
        "Siddhant's approval of the November budget is not on file. "
        "Every other activity needs an exact go-live date per store."
    )
    if not activities and not lifts:
        why = [plans["summary"], "Ads ROAS is not on file."]
    return {
        "id": "marketing",
        "title": title,
        "verdict": verdict,
        "columns": ["Item", "Posist gross", "Reelo-attributed", "Verdict"],
        "rows": rows[:8] or full[:8],
        "full_rows": full or rows,
        "why": " ".join(why),
        "action": "Sanjoy and Nikita send the store, channel and go-live date by 27 Nov.",
        "owner": "Sanjoy Roy / Nikita Mittal",
        "coverage": "marketing activity file through 24 Nov; Tony's lift file versus Posist gross",
    }


def _status_label(value):
    text = (value or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Not on file"


def _marketing_lift(root):
    path = Path(root) / "data" / "marketing" / "marketing_lift.csv"
    if not path.is_file():
        return []
    found = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            found.append({
                "activity": (raw.get("activity") or "").strip(),
                "posist": " ".join(
                    part for part in (
                        (raw.get("posist") or "").strip(),
                        (raw.get("comparison") or "").strip(),
                        (raw.get("note") or "").strip(),
                    ) if part
                ),
                "reelo": _dec(raw.get("reelo_attributed_inr")),
                "verdict": (raw.get("verdict") or "").strip(),
            })
    return [row for row in found if row["activity"]]


def _head_name(name):
    text = (name or "").split("–")[0].split("(")[0].strip()
    if len(text) <= 42:
        return text
    return text[:42].rsplit(" ", 1)[0]


def _october_from_note(note):
    folded = note or ""
    if "nil in october" in folded.casefold():
        return Decimal(0)
    match = re.search(r"October budget ₹\s*([\d,.]+)\s*L\b", folded, re.I)
    if match:
        return (Decimal(match.group(1).replace(",", "")) * Decimal(100000)).quantize(Decimal("1"))
    match = re.search(r"October budget ₹\s*([\d,]+)", folded, re.I)
    if match:
        return Decimal(match.group(1).replace(",", ""))
    return None


def _marketing_activities(root):
    path = Path(root) / "data" / "marketing" / "marketing_activities.csv"
    if not path.is_file():
        return None
    heads = []
    activities = []
    november = october = None
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            kind = (raw.get("record_type") or "").strip()
            month = (raw.get("month") or "").strip()
            amount = _dec(raw.get("budget_inr"))
            name = (raw.get("activity_name") or "").strip()
            if kind == "budget" and month == "2026-11" and (raw.get("type") or "") == "budget_total":
                november = amount
                continue
            if kind == "budget" and month == "2026-10" and (raw.get("type") or "") == "budget_total":
                october = amount
                continue
            if kind == "budget" and month == "2026-11":
                heads.append({
                    "name": _head_name(name),
                    "november": amount or Decimal(0),
                    "october": _october_from_note(raw.get("expected_or_notes") or ""),
                })
                continue
            if kind == "activity":
                activities.append({
                    "month": month,
                    "name": name[:64],
                    "start": (raw.get("start_date") or "").strip(),
                    "where": (raw.get("stores_or_city") or "").strip()[:40],
                    "status": (raw.get("status") or "").strip(),
                })
    return {"november": november, "october": october, "heads": heads, "activities": activities}


def _budget_sentence(activities):
    november = activities.get("november")
    october = activities.get("october")
    if november is None:
        return "The November marketing budget total is not on file."
    text = f"November marketing budget {money(november)}"
    if october is not None:
        text += f" versus October {money(october)}"
    bits = []
    for head in activities["heads"]:
        if head["october"] is None:
            bits.append(f"{head['name']} {money(head['november'])}")
        else:
            bits.append(f"{head['name']} {money(head['november'])} against October {money(head['october'])}")
    if bits:
        text += ". By head: " + "; ".join(bits) + "."
    return text


def _marketing_plans(root):
    paths = [
        Path(root) / "data" / "reelo" / "marketing_plans.csv",
        Path(root) / "data" / "marketing" / "marketing_plans.csv",
    ]
    path = next((item for item in paths if item.is_file()), None)
    if path is None:
        return {
            "status": "missing",
            "summary": "Impact not measured yet. marketing_plans.csv (activity, store, start, end, channel, and a lift column when Tony has measured it) is not on file.",
            "rows": [],
            "coverage": "marketing_plans.csv not on file",
        }
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = [name.casefold() for name in (reader.fieldnames or [])]
        lift_name = next((name for name in (reader.fieldnames or []) if "lift" in name.casefold()), None)
        rows = []
        measured = False
        for raw in reader:
            lift = (raw.get(lift_name) or "").strip() if lift_name else ""
            if lift:
                measured = True
            rows.append([
                raw.get("activity") or raw.get("Activity") or "",
                raw.get("store") or raw.get("Store") or "",
                raw.get("channel") or raw.get("Channel") or "",
                lift or "impact not measured yet",
            ])
    if "activity" not in fields and "store" not in fields:
        return {
            "status": "missing",
            "summary": "marketing_plans.csv is on file but has no activity and store columns.",
            "rows": [],
            "coverage": path.name,
        }
    if measured:
        return {"status": "lift", "summary": f"{sum(1 for row in rows if row[3] != 'impact not measured yet')} activities have a lift.", "rows": rows[:8], "coverage": path.name}
    return {
        "status": "open",
        "summary": "Impact not measured yet. The plan file has no lift column filled.",
        "rows": rows[:8],
        "coverage": path.name,
    }


def _reelo(root):
    title = "6. Reelo"
    path = Path(root) / "data" / "reelo" / "reelo_storewise_latest.csv"
    if not path.is_file():
        return _blank(title, "reelo", "Not on file — owner: " + _LOYALTY, _LOYALTY, "reelo_storewise_latest.csv")
    new = repeat = Decimal(0)
    shares = []
    phones = []
    ratings = []
    redemptions = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            new += _dec(raw.get("New Customers")) or Decimal(0)
            repeat += _dec(raw.get("Repeat Customers")) or Decimal(0)
            share = _dec(raw.get("Derived repeat customer share (%)"))
            phone = _dec(raw.get("%"))
            rating = _dec(raw.get("avg_rating"))
            redeem = _dec(raw.get("redemption_rate_in_percentage"))
            if share is not None:
                shares.append(float(share))
            if phone is not None:
                phones.append(float(phone))
            if rating is not None:
                ratings.append(float(rating))
            if redeem is not None:
                redemptions.append(float(redeem))
    median = statistics.median(shares) if shares else None
    verdict = f"On file: {int(new)} new customers and {int(repeat)} repeat customers across {len(shares)} stores."
    if median is not None:
        verdict += f" Median repeat share {median:.2f}%."
    rows = [[
        int(new), int(repeat), f"{median:.2f}%" if median is not None else "",
        f"{statistics.median(phones):.1f}%" if phones else "Not on file",
        f"{statistics.median(ratings):.2f}" if ratings else "Not on file",
        f"{statistics.median(redemptions):.1f}%" if redemptions else "Not on file",
    ]]
    campaign = list((Path(root) / "data" / "reelo").glob("campaign_results*.csv")) if (Path(root) / "data" / "reelo").is_dir() else []
    conversions = "Campaign conversions are not on file. Logan's first result is 30 Nov." if not campaign else f"{campaign[0].name} is on file."
    return {
        "id": "reelo",
        "title": title,
        "verdict": verdict,
        "columns": ["New", "Repeat", "Median repeat share", "Median phone capture", "Median rating", "Median redemption"],
        "rows": rows,
        "why": conversions + " Store aggregates only.",
        "action": "Logan files campaign conversions next to reelo_storewise_latest.csv.",
        "owner": _LOYALTY,
        "coverage": "reelo_storewise_latest.csv only",
    }


def _quality(root):
    title = "7. Quality and complaints"
    ratings = Path(root) / "data" / "store_health" / "famepilot.csv"
    tickets = Path(root) / "data" / "famepilot" / "open_complaints_export.csv"
    audit = Path(root) / "data" / "store_health" / "mystery_audit.csv"
    rows = []
    open_count = resolved = 0
    emergency = 0
    if tickets.is_file():
        with tickets.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                if (raw.get("resolved_at") or "").strip():
                    resolved += 1
                else:
                    open_count += 1
                blob = " ".join(raw.get(key) or "" for key in raw).casefold()
                if "emergency" in blob:
                    emergency += 1
    rating_line = "Not on file"
    if ratings.is_file():
        scores = []
        with ratings.open(encoding="utf-8-sig", newline="") as handle:
            table = list(csv.DictReader(handle))
        for raw in table:
            score = _dec(raw.get("rating"))
            if score is not None:
                scores.append(score)
        if scores:
            rating_line = f"median {statistics.median(scores):.2f} across {len(scores)} locations"
        if table and "negative" not in ",".join(table[0]).casefold():
            negative = "Negative % is not on file — owner: " + _AUDIT
        else:
            negative = "Negative % is in the ratings file."
    else:
        negative = "Not on file — owner: " + _AUDIT
    audit_line = "Not on file — owner: " + _AUDIT
    if audit.is_file():
        with audit.open(encoding="utf-8-sig", newline="") as handle:
            first = next(csv.DictReader(handle), None)
        if first:
            audit_line = f"{first.get('store')} {first.get('period')} {first.get('avg_score')}"
    verdict = f"Open tickets {open_count}, resolved {resolved}."
    if emergency:
        verdict += f" Emergencies {emergency}."
    else:
        verdict += " No emergency row is on file."
    rows.append(["Famepilot rating", rating_line])
    rows.append(["Negative %", negative])
    rows.append(["Tickets", f"{open_count} open, {resolved} resolved"])
    rows.append(["Mystery audit", audit_line])
    return {
        "id": "quality",
        "title": title,
        "verdict": verdict,
        "columns": ["Source", "What is on file"],
        "rows": rows,
        "why": "Counts come from the export rows. A blank resolved_at is open.",
        "action": "Clear the open tickets at the stores with the most rows.",
        "owner": _NCR,
        "coverage": "open_complaints_export.csv; famepilot.csv; mystery_audit.csv",
    }


def _cost(root, sales, see_finance):
    title = "8. Food cost, wastage, inventory and opex"
    summary = Path(root) / "data" / "procurement" / "procurement_summary.json"
    flags = Path(root) / "data" / "flags" / "procurement.csv"
    variance = list((Path(root) / "data" / "procurement").glob("kolkata_variance_weekly_*.csv")) if (Path(root) / "data" / "procurement").is_dir() else []
    rows = []
    if summary.is_file():
        import json
        payload = json.loads(summary.read_text(encoding="utf-8"))
        cities = payload.get("yesterday_grn") or {}
        for city, block in cities.items():
            if isinstance(block, dict) and block.get("value") is not None:
                rows.append([city, "receipts", money(block["value"]), str(block.get("date") or payload.get("as_of") or "")])
    else:
        rows.append(["Purchases", "Not on file — owner: " + _BUY, "", ""])
    if flags.is_file():
        with flags.open(encoding="utf-8-sig", newline="") as handle:
            flag_rows = list(csv.DictReader(handle))
        price = [row for row in flag_rows if "90" in (row.get("title") or "") or "90-day" in (row.get("detail") or "")]
        holds = [row for row in flag_rows if "hold" in ((row.get("title") or "") + (row.get("detail") or "")).casefold()]
        rows.append(["90-day price", f"{len(price)} rows" if price else "Not on file — owner: " + _BUY, "", flag_rows[0].get("as_of") if flag_rows else ""])
        rows.append(["Holds", f"{len(holds)} rows" if holds else "Not on file — owner: " + _BUY, "", ""])
    if variance:
        rows.append(["Kolkata variance", variance[-1].name, "", ""])
    else:
        rows.append(["Kolkata variance", "Not on file — owner: " + _BUY, "", ""])
    rows.append(["Delhi store variance", "Not on file — owner: " + _BUY, "", ""])
    rows.append(["Packaging", "Not split out in the wastage file", "", ""])
    wastage = _wastage(root, sales)
    rows.extend(wastage["rows"])
    if see_finance:
        rent = _owner_cost(root)
        rows.extend(rent)
    else:
        rows.append(["Opex and rent", "On the owner login", "", ""])
        rows.append(["Accountant flags", "On the owner login", "", ""])
    verdict = "Receipts are on file. Food-cost variance for this week is not on file — owner: " + _BUY + "."
    return {
        "id": "cost",
        "title": title,
        "verdict": verdict,
        "columns": ["Item", "Figure", "Amount", "Coverage"],
        "rows": rows[:12],
        "full_rows": rows,
        "why": wastage["why"] + " Food cost is (raw + semi consumption) / Posist gross for the same dates. Packaging is separate and is not in that file.",
        "action": "Sailesh files the Monday Kolkata variance and the Delhi store variance.",
        "owner": _BUY,
        "coverage": "procurement_summary.json; flags/procurement.csv; store_consumption_wastage.csv",
    }


def _wastage(root, sales):
    path = Path(root) / "data" / "procurement" / "store_consumption_wastage.csv"
    if not path.is_file():
        return {"rows": [["Wastage", "Not on file — owner: " + _BUY, "", ""]], "why": "Wastage by store is not on file."}
    grouped = {}
    period = ""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            period = period or (raw.get("period") or "")
            name = raw.get("deployment") or raw.get("store") or ""
            if _closed(name, ""):
                continue
            code = ""
            if "(" in name and ")" in name:
                code = canonical_store_code(name[name.rfind("(") + 1:name.rfind(")")])
            bucket = grouped.setdefault(code or name, {"name": name, "raw": Decimal(0), "semi": Decimal(0), "waste": Decimal(0)})
            bucket["raw"] += _dec(raw.get("consumption_amt_raw")) or Decimal(0)
            bucket["semi"] += _dec(raw.get("consumption_amt_semi")) or Decimal(0)
            bucket["waste"] += _dec(raw.get("wastage_amt_all")) or Decimal(0)
    start, end = _period(period)
    rows = []
    ranked = sorted(grouped.values(), key=lambda item: item["waste"], reverse=True)
    for bucket in ranked[:5]:
        gross = Decimal(0)
        if start and end:
            code = canonical_store_code(bucket["name"][bucket["name"].rfind("(") + 1:bucket["name"].rfind(")")]) if "(" in bucket["name"] else ""
            series = sales.get(code) or {}
            day = start
            while day <= end:
                row = series.get(day)
                if row:
                    gross += row["gross"]
                day += timedelta(days=1)
        if gross:
            food = f"{((bucket['raw'] + bucket['semi']) / gross) * 100:.1f}%"
        else:
            food = "gross for this period not matched"
        rows.append([bucket["name"][:40], f"waste {money(bucket['waste'])}; food cost {food}", money(bucket["raw"] + bucket["semi"]), period])
    return {"rows": rows, "why": f"Wastage file period is {period or 'not dated'}. "}


def _period(text):
    parts = (text or "").split(" to ")
    if len(parts) != 2:
        return None, None
    try:
        return date.fromisoformat(parts[0].strip()), date.fromisoformat(parts[1].strip())
    except ValueError:
        return None, None


def _owner_cost(root):
    econ = Path(root) / "data" / "finance" / "store_month_net.csv"
    rows = []
    if econ.is_file() and Path(root).resolve() == _ROOT.resolve():
        from app.chat.sizing import _rent_line
        line = _rent_line()
        rows.append(["October rent", line[:180] if line else "Not on file", "", "Grand Economics October"])
    else:
        rows.append(["October rent", "Not on file — owner: Shilajit", "", ""])
    flags = Path(root) / "data" / "flags" / "accountant.csv"
    if flags.is_file():
        with flags.open(encoding="utf-8-sig", newline="") as handle:
            count = sum(1 for _ in csv.DictReader(handle))
        rows.append(["Accountant flags", f"{count} rows, owner only", "", "flags/accountant.csv"])
    else:
        rows.append(["Accountant flags", "Not on file — owner: Shilajit", "", ""])
    compare = Path(root) / "data" / "finance" / "OCT_vs_SEP_store_economics.csv"
    if not compare.is_file():
        rows.append(["October vs September economics", "Not on file — owner: Shilajit", "", ""])
    return rows


def _people(see_hr):
    title = "9. Manpower, stock-outs, maintenance"
    if not see_hr:
        return {
            "id": "people",
            "title": title,
            "verdict": "Manpower is on the owner login. Stock-outs are not tracked yet.",
            "columns": ["Item", "Status"],
            "rows": [
                ["Manpower", "On the owner login"],
                ["Stock-outs", "not tracked yet. Restroworks shows receipts only."],
                ["Maintenance", f"Not on file — owner: {_OPS}"],
            ],
            "why": "HR aggregates stay on the owner and HR logins.",
            "action": "Prasmita files the manpower aggregate when it exists.",
            "owner": _HR,
            "coverage": "HR file not shown on this login",
        }
    return {
        "id": "people",
        "title": title,
        "verdict": f"Not on file — owner: {_HR}. Stock-outs are not tracked yet.",
        "columns": ["Item", "Status"],
        "rows": [
            ["Manpower", f"Not on file — owner: {_HR}"],
            ["Stock-outs", "not tracked yet. Restroworks shows receipts only."],
            ["Maintenance", f"Not on file — owner: {_OPS}"],
            ["Training", f"Not on file — owner: Aparnita"],
        ],
        "why": "data/gaps/hr.csv has no rows. No maintenance note is on file.",
        "action": "Prasmita files headcount gaps. Stock-outs stay untracked until Restroworks records them.",
        "owner": _HR,
        "coverage": "data/gaps/hr.csv header only",
    }


def _actions(root):
    title = "10. Today's actions"
    email = _ops_email(root)
    logged = _action_log()
    verdict = "No commitment is logged as closed or open."
    if "Not on file" not in email and "No Wizard" not in logged:
        verdict = "On file: see the Ops email and the Wizard log."
    return {
        "id": "actions",
        "title": title,
        "verdict": verdict,
        "columns": ["Source", "Status"],
        "rows": [
            ["Ops email", email[:180]],
            ["Wizard action log", logged],
        ],
        "why": "Today's list is the previous day's Ops asks and the Send-to-Grok-Bot statuses. Nothing is invented.",
        "action": "Sanjoy replies on the Ops email when it is on file.",
        "owner": _OPS,
        "coverage": "ops_email file; ChiefRequest log",
    }


def _action_log():
    try:
        from app.chat.extras import ChiefRequest
        rows = ChiefRequest.query.order_by(ChiefRequest.id.desc()).limit(5).all()
    except Exception:
        rows = []
    if not rows:
        return "No Wizard action is logged."
    return "; ".join(f"{row.status}: {(row.request or '')[:80]}" for row in rows)


def _blank(title, name, verdict, owner, coverage):
    return {
        "id": name,
        "title": title,
        "verdict": verdict if verdict.startswith("Not on file") or "8:50" in verdict else f"Not on file — owner: {owner}. {verdict}",
        "columns": ["Note"],
        "rows": [],
        "why": verdict,
        "action": "Load the file named in the coverage line.",
        "owner": owner,
        "coverage": coverage,
    }
