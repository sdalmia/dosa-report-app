"""Checks that a figure matches the file it came from.

Nothing here is a remembered total. Network net is read from
sales_pred_vs_actual.csv. A variance week is counted only when that file
says so. A Posist day is loaded only when its _DONE marker is present.
"""

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_COUNT_HINTS = ("stock_count", "physical_count", "counted", "count_flag", "has_stock_count", "physical")
_COUNTED_VALUES = {"1", "true", "yes", "y", "counted"}


def network_net_rows(path=None):
    """Date to the file's own actual-net text. Blank actuals are left out."""
    file_path = Path(path) if path else _ROOT / "data" / "posist" / "sales_pred_vs_actual.csv"
    found = {}
    if not file_path.is_file():
        return found
    with file_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            day = str(row.get("date") or "")[:10]
            raw = str(row.get("actual_net_L") or "").strip()
            if not day or not raw:
                continue
            found[day] = raw
    return found


def network_net_on(day, path=None):
    rows = network_net_rows(path)
    return rows.get(str(day)[:10])


def network_net_window(start, end, path=None):
    """Sum of daily actual net between two ISO dates, inclusive.

    Returns (total Decimal or None, list of missing ISO dates, raw cells).
    """
    rows = network_net_rows(path)
    if not start or not end:
        return None, [], {}
    try:
        first = datetime.strptime(str(start)[:10], "%Y-%m-%d").date()
        last = datetime.strptime(str(end)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None, [], {}
    missing = []
    cells = {}
    total = Decimal("0")
    day = first
    from datetime import timedelta
    while day <= last:
        key = day.isoformat()
        raw = rows.get(key)
        if raw is None:
            missing.append(key)
        else:
            try:
                total += Decimal(raw)
            except InvalidOperation:
                missing.append(key)
            else:
                cells[key] = raw
        day += timedelta(days=1)
    if missing:
        return None, missing, cells
    return total, [], cells


def net_lakh(raw):
    """The file's own decimals, labelled network net in Rs L."""
    text = str(raw).strip()
    if not text:
        return ""
    return f"Rs {text} L network net"


def gross_label(amount_lakh):
    return f"Rs {amount_lakh} L gross"


def variance_basis(row):
    """Counted only when the variance row itself carries a stock-count flag."""
    if not isinstance(row, dict) or not row:
        return "uncounted"
    for key, value in row.items():
        token = str(key or "").strip().casefold().replace(" ", "_")
        if not any(hint in token for hint in _COUNT_HINTS):
            continue
        flag = str(value or "").strip().casefold()
        if flag in _COUNTED_VALUES:
            return "counted"
        return "uncounted"
    return "uncounted"


def variance_label(basis):
    if basis == "counted":
        return "true food cost (physical stock count)"
    return "recipe use + booked wastage, no stock count"


def like_for_like(left, right):
    """Two weeks compare only when both were physically counted."""
    return left == "counted" and right == "counted"


def day_is_loaded(day, root=None):
    """A Posist day is in only when daily_sales has _DONE_<date>."""
    base = Path(root) if root else _ROOT
    stamp = str(day)[:10]
    return (base / "data" / "posist" / "daily_sales" / f"_DONE_{stamp}").is_file()


def day_status(day, root=None):
    if day_is_loaded(day, root):
        return ""
    return f"{str(day)[:10]} isn't in yet."


def drop_pending(day, root=None):
    """A daily_sales file is present for this day, and the _DONE marker is not.

    Days that never had a daily_sales drop stay on the historical file.
    A drop without its marker is not a loaded day.
    """
    base = Path(root) if root else _ROOT
    folder = base / "data" / "posist" / "daily_sales"
    stamp = str(day)[:10]
    if not folder.is_dir() or not any(folder.glob("_DONE_*")):
        return False
    names = (f"sales_{stamp}.csv", f"network_{stamp}.csv", f"channel_{stamp}.csv")
    if not any((folder / name).is_file() for name in names):
        return False
    return not (folder / f"_DONE_{stamp}").is_file()


def quoted_day_net(day, path=None, root=None):
    """Network net for one date, or a clear 'not in yet' when the drop is partial."""
    stamp = str(day)[:10]
    if drop_pending(stamp, root):
        return f"{day_status(stamp, root)} No partial number from that day is used."
    raw = network_net_on(stamp, path)
    if not raw:
        return ""
    return f"{stamp} {net_lakh(raw)}, from sales_pred_vs_actual.csv."


def reconciles(parts, total, tolerance="0.02"):
    try:
        left = sum(Decimal(str(part)) for part in parts)
        right = Decimal(str(total))
    except (InvalidOperation, TypeError):
        return False
    return abs(left - right) <= Decimal(str(tolerance))


def reconcile_note(parts, total):
    if reconciles(parts, total):
        return ""
    return "doesn't reconcile"


def channel_exceeds_gross(channel_total, store_gross):
    try:
        return Decimal(str(channel_total)) > Decimal(str(store_gross))
    except (InvalidOperation, TypeError):
        return False


def accountant_flags(root=None):
    base = Path(root) if root else _ROOT
    path = base / "data" / "flags" / "accountant.csv"
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [row for row in csv.DictReader(handle) if (row.get("title") or "").strip()]
    except OSError:
        return []


def provisional_line(role, owner=False, root=None):
    from app.chat.guard import can_see_pl

    if not can_see_pl(role, owner):
        return ""
    rows = accountant_flags(root)
    if not rows:
        return ""
    lead = rows[0]
    note = (lead.get("detail") or "").strip()
    title = (lead.get("title") or "").strip()
    extra = f" {note}" if note else ""
    return f"Provisional: {title}.{extra}"


def tracker_through_line():
    """Last stock-entry date in the ingredient tracker. Blank when it is not loaded."""
    try:
        from flask import has_app_context
        if not has_app_context():
            return "Ingredient tracker stock-entry date is not loaded."
        from app.extensions import db
        from app.models import IngredientPrice
        last = db.session.query(db.func.max(IngredientPrice.date)).scalar()
    except Exception:
        return "Ingredient tracker stock-entry date is not loaded."
    if not last:
        return "Ingredient tracker stock-entry date is not loaded."
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"Stock entries run through {last.day} {months[last.month - 1]} {last.year}."


def data_footer(data, question=""):
    windows = (data or {}).get("sales_windows") or {}
    summary = (data or {}).get("summary") or {}
    latest = str(windows.get("latest") or summary.get("as_of_date") or summary.get("actuals_through") or "")[:10]
    if latest:
        try:
            day = datetime.strptime(latest, "%Y-%m-%d")
            months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
            through = f"{day.day} {months[day.month - 1]} {day.year}"
        except ValueError:
            through = latest
    else:
        through = "not loaded"
    folded = " ".join((question or "").casefold().split())
    sources = []
    if any(token in folded for token in ("sale", "week", "yesterday", "forecast", "pace", "net", "bill", "gross", "target", "behind", "attention")):
        sources.append("sales_pred_vs_actual.csv (network net)")
        sources.append("Posist daily gross")
    if any(token in folded for token in ("price", "pay", "paneer", "milk", "cheese", "daal", "bought")):
        sources.append("procurement summary")
        sources.append("ingredient tracker")
    if "tally" in folded or "what did we pay" in folded:
        sources.append("Tally day book")
    if not sources:
        sources.append("loaded files for this question")
    pending = day_status(latest) if latest else ""
    line = f"Data through {through} | Sources: {', '.join(sources)}."
    if pending:
        line += " " + pending
    return line


def network_net_sentence(data, path=None):
    """Authoritative network net for the loaded sales week and its last day."""
    windows = (data or {}).get("sales_windows") or {}
    start = windows.get("week_start")
    end = windows.get("latest")
    total, missing, cells = network_net_window(start, end, path)
    if not end:
        return ""
    if drop_pending(end):
        return f"{day_status(end)} No partial network net is shown."
    if not day_is_loaded(end):
        return f"{end} isn't in yet. No partial network net is shown."
    end_raw = network_net_on(end, path)
    pending = [day for day in cells if drop_pending(day)]
    if pending:
        notes = " ".join(day_status(day) for day in pending)
        return f"{notes} No partial network net is shown. Store rows are gross, not net."
    if missing or total is None or not end_raw:
        missing_text = ", ".join(missing) if missing else end
        return f"Network net doesn't reconcile for {missing_text}. Store rows stay gross, not net."
    end_text = net_lakh(end_raw)
    total_text = net_lakh(f"{total:.2f}")
    check = reconcile_note(list(cells.values()), total)
    note = f" {check}." if check else ""
    return (
        f"{end} {end_text}, from sales_pred_vs_actual.csv. "
        f"{start} to {end} {total_text}, the sum of those daily actual nets.{note} "
        "Store rows are gross, not net."
    )
