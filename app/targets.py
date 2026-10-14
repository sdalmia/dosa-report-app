"""October sales against the ops-budget net target.

Tony's store_targets.csv is the source of truth. The pace file is gross for
1–13 Oct set against a pro-rated net target, so every store row is labelled
as a rough guide. Network net is shown only for the days that have it.
"""

import csv
import calendar
from datetime import date, timedelta
from pathlib import Path

from app.store_health.present import format_owner_rupee
from app.store_health.stores import store_from_label
from app.store_master import find_store, is_closed_status, store_status
from app.view_filters import CITY_REGION

PACE_DAYS = 13


def targets_path():
    return Path(__file__).resolve().parents[1] / "data" / "targets" / "store_targets.csv"


def pace_path():
    folder = targets_path().parent
    files = sorted(folder.glob("store_targets_pace_mtd_*.csv"))
    return files[-1] if files else None


def network_directory():
    return Path(__file__).resolve().parents[1] / "data" / "posist" / "daily_sales"


def canonical_store_code(raw):
    """Budget codes are region/store. A bare code in this file is East, 01/."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if "/" in text:
        region, number = text.split("/", 1)
        return f"{int(region):02d}/{int(number):04d}"
    return f"01/{int(text):04d}"


def _number(value):
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _read_dicts(path):
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _visible_name(posist_name, display_name):
    text = str(posist_name or "").strip()
    prefix = "dosa coffee - "
    if text.casefold().startswith(prefix):
        text = text[len(prefix):]
    text = " ".join(text.split())
    return text or (display_name or "").strip() or str(posist_name or "").strip()


def load_targets(path=None):
    rows = []
    for raw in _read_dicts(path or targets_path()):
        amount = _number(raw.get("target_net"))
        code = canonical_store_code(raw.get("store_code"))
        if amount is None or not code:
            continue
        master = find_store(code)
        if master is not None and is_closed_status(store_status(master)):
            continue
        posist_name = (master or {}).get("posist_name") or ""
        display = (master or {}).get("display_name") or (raw.get("budget_outlet_name") or "").strip()
        rows.append({
            "code": code,
            "month": (raw.get("month") or "").strip(),
            "budget_name": (raw.get("budget_outlet_name") or "").strip(),
            "target_net": amount,
            "dinein": _number(raw.get("target_net_dinein")),
            "aggregator": _number(raw.get("target_net_aggregator")),
            "posist_name": posist_name,
            "name": _visible_name(posist_name, display),
            "region": (master or {}).get("region") or "",
            "status": store_status(master) if master else "",
            "mapped": master is not None,
        })
    return rows


def load_pace(path=None):
    path = Path(path) if path else pace_path()
    paced = {}
    if path is None:
        return paced, None
    as_of = _pace_date(path)
    for raw in _read_dicts(path):
        code = canonical_store_code(raw.get("store_code"))
        if not code:
            continue
        paced[code] = {
            "gross": _number(raw.get("mtd_gross_1_13oct_GROSS_NOT_NET")),
            "days": _number(raw.get("days")),
            "prorata": _number(raw.get("prorata_13d")),
            "pct": _number(raw.get("gross_vs_prorata_pct")),
        }
    return paced, as_of


def _pace_date(path):
    token = path.stem.replace("store_targets_pace_mtd_", "")
    try:
        return date.fromisoformat(token)
    except ValueError:
        return None


def load_network(directory=None):
    directory = Path(directory) if directory else network_directory()
    days = {}
    if not directory.is_dir():
        return days
    for path in sorted(directory.glob("network_*.csv")):
        for raw in _read_dicts(path):
            try:
                day = date.fromisoformat((raw.get("date") or "").strip())
            except ValueError:
                continue
            region = (raw.get("region") or "").strip()
            if not region:
                continue
            days.setdefault(day, {})[region] = {
                "gross": _number(raw.get("gross")),
                "net": _number(raw.get("net")),
            }
    return days


def build_board(posist, today, targets=None, store_label="", city=""):
    """One row per store, furthest behind first."""
    empty = {
        "ready": False,
        "title": "Against target",
        "period": "",
        "pace": "",
        "network": "",
        "note": "",
        "rows": [],
        "empty": "No sales on file." if not posist else "No target for this month.",
    }
    if not posist:
        return empty
    rows = list(targets) if targets is not None else load_targets()
    months = {row["month"] for row in rows}
    month = _active_month(today, months)
    if not month:
        return empty
    pace, as_of = load_pace()
    start = _month_start(month)
    region = CITY_REGION.get((city or "").strip(), "")
    if city and not region:
        region = city
    presented = []
    for row in rows:
        if row["month"] != month:
            continue
        if store_label and row["posist_name"] != store_label:
            continue
        if not store_label and region and row["region"] != region:
            continue
        presented.append(_present(row, pace.get(row["code"])))
    presented.sort(key=lambda row: (
        0 if row["pct_value"] is not None else 1,
        row["pct_value"] if row["pct_value"] is not None else 0,
        row["name"].casefold(),
    ))
    if store_label and not presented:
        empty["empty"] = "No target for this store."
        return empty
    if not presented:
        empty["empty"] = "No target for this city." if city else "No target for this month."
        return empty
    period = ""
    if as_of:
        period = f"{start.strftime('%B %Y')}, through {as_of.day} {as_of.strftime('%b')}"
    network = ""
    pace_line = ""
    if not store_label:
        scoped = [row for row in rows if row["month"] == month and (not region or row["region"] == region)]
        network = _network_line(scoped, month, start, region, city)
        pace_line = _pace_totals(presented, as_of)
    return {
        "ready": True,
        "title": "Against target",
        "period": period,
        "pace": pace_line,
        "network": network,
        "note": "Rough guide (gross vs net target).",
        "rows": presented,
        "empty": "",
    }


def _month_start(token):
    year, month = token.split("-")
    return date(int(year), int(month), 1)


def _active_month(today, months):
    started = []
    for token in months:
        try:
            start = _month_start(token)
        except ValueError:
            continue
        if start <= today:
            started.append(token)
    return max(started) if started else ""


def _present(row, pace):
    pace = pace or {}
    gross = pace.get("gross")
    prorata = pace.get("prorata")
    pct = pace.get("pct")
    days = pace.get("days")
    tag = row["status"] if row["status"].casefold().startswith("closing") else ""
    if not gross:
        line = "No sales on file"
    else:
        line = f"Gross {format_owner_rupee(gross)} of {format_owner_rupee(prorata)}"
        if pct is not None:
            line = f"{line} · {pct:.1f}%"
        if days is not None and int(days) != PACE_DAYS:
            line = f"{line} · {int(days)} days on file"
    if row["target_net"]:
        line = f"{line} · month {format_owner_rupee(row['target_net'])}"
    return {
        "name": row["name"],
        "store": row["posist_name"],
        "code": row["code"],
        "budget_name": row["budget_name"],
        "tag": tag,
        "href": "/store-health/" + store_from_label(row["posist_name"]).id if row["posist_name"] else "",
        "line": line,
        "pct_value": pct,
        "pct_label": f"{pct:.1f}%" if pct is not None else "",
    }


def _pace_totals(rows, as_of):
    """Gross and pro-rata are recovered from the pace file, not the label."""
    pace, _as_of = load_pace()
    codes = {row["code"] for row in rows}
    gross_values = []
    prorata_values = []
    for code in codes:
        slot = pace.get(code) or {}
        if slot.get("gross") is not None:
            gross_values.append(slot["gross"])
        if slot.get("prorata") is not None:
            prorata_values.append(slot["prorata"])
    if not gross_values or not prorata_values:
        return ""
    gross = sum(gross_values)
    prorata = sum(prorata_values)
    pct = gross / prorata * 100 if prorata else None
    end = as_of.day if as_of else PACE_DAYS
    month = as_of.strftime("%b") if as_of else "Oct"
    body = f"1–{end} {month} gross {format_owner_rupee(gross)} of {format_owner_rupee(prorata)}"
    if pct is not None:
        body = f"{body} · {pct:.1f}%"
    return body


def _network_line(rows, month, start, region, city):
    days = load_network()
    if not days:
        return ""
    chosen = []
    nets = []
    for day in sorted(days):
        if day.year != start.year or day.month != start.month:
            continue
        amount = _region_net(days[day], region)
        if amount is None:
            continue
        chosen.append(day)
        nets.append(amount)
    target = sum(row["target_net"] for row in rows if row["month"] == month)
    if not chosen or not target:
        return ""
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    prorata = target * len(chosen) / days_in_month
    total = sum(nets)
    pct = total / prorata * 100 if prorata else None
    who = (city or "").strip() or "Network"
    span = _span(chosen)
    line = f"{who} net, {span}: {format_owner_rupee(total)} of {format_owner_rupee(prorata)}"
    if pct is not None:
        line = f"{line} · {pct:.1f}% of pro-rata"
    return line


def _region_net(regions, region):
    if region:
        slot = regions.get(region)
        if not slot or slot.get("net") is None:
            return None
        return slot["net"]
    total = regions.get("Total")
    if total and total.get("net") is not None:
        return total["net"]
    parts = []
    for name in ("East", "North"):
        slot = regions.get(name)
        if slot and slot.get("net") is not None:
            parts.append(slot["net"])
    if not parts:
        return None
    return sum(parts)


def _span(days):
    if len(days) == 1:
        return f"{days[0].day} {days[0].strftime('%b')}"
    first, last = days[0], days[-1]
    contiguous = last - first == timedelta(days=len(days) - 1)
    if contiguous and first.month == last.month and first.year == last.year:
        return f"{first.day}–{last.day} {first.strftime('%b')}"
    return f"{first.day} {first.strftime('%b')}–{last.day} {last.strftime('%b')}"
