"""Newest menu mix and the 12 Nov Keka counts.

The menu file refreshes on Fridays. The newest menu_mix_*.csv wins, and its
meta names the window. Net, channel, and category stay blank when the source
has them blank. People counts are owner and HR only.
"""

import csv
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _num(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _menu_files():
    folder = _ROOT / "data" / "menu"
    if not folder.is_dir():
        return []
    found = []
    for path in folder.glob("menu_mix_*.csv"):
        found.append(path)
    return found


def _read(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _file_stamp(path):
    days = re.findall(r"\d{4}-\d{2}-\d{2}", path.name)
    if days:
        return max(days)
    months = re.findall(r"\d{4}-\d{2}", path.name)
    if months:
        return max(months) + "-01"
    return ""


def _meta_for(path):
    meta_path = path.with_name(path.stem + ".meta.json")
    if not meta_path.is_file():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def newest_menu():
    """Newest Friday drop, by the date in the filename, with its meta."""
    best = None
    best_stamp = ""
    for path in _menu_files():
        stamp = _file_stamp(path)
        if best is None or stamp > best_stamp:
            best = path
            best_stamp = stamp
    if best is None:
        return None
    return best, _read(best), _meta_for(best)


def menu_packet(question):
    folded = (question or "").casefold()
    if not any(token in folded for token in ("menu", "item", "dosa", "best sell", "contribution", "mix")):
        return ""
    picked = newest_menu()
    if not picked:
        return "Menu mix: no menu_mix file is loaded."
    path, rows, meta = picked
    usable = []
    for row in rows:
        gross = _num(row.get("gross") if "gross" in row else row.get("total_sales"))
        net = _num(row.get("net_sales"))
        qty = _num(row.get("qty") if "qty" in row else row.get("total_orders"))
        usable.append({
            "store": (row.get("store") or "").strip(),
            "item": (row.get("item") or "").strip(),
            "gross": gross,
            "net": net,
            "qty": qty,
            "start": (row.get("date_from") or row.get("period_start") or "").strip(),
            "end": (row.get("date_to") or row.get("period_end") or "").strip(),
            "basis": (row.get("sales_basis") or "").strip() or ("gross" if net is None and gross is not None else ""),
            "category": (row.get("category") or "").strip(),
        })
    named = [row for row in usable if row["store"] and row["store"].casefold() in folded]
    pool = named or usable
    if any(token in folded for token in ("item", "dosa", "best", "top", "sell")):
        pool = sorted(pool, key=lambda row: row["gross"] or 0, reverse=True)[:12]
    else:
        pool = pool[:12]
    net_blank = all(row["net"] is None for row in pool) or meta.get("net_sales_filled") is False
    window = meta.get("period_label") or ""
    start = meta.get("period_date_from") or ""
    end = meta.get("period_date_to") or ""
    lines = [
        f"Menu mix from {path.name}.",
        f"Window: {window}" if window else f"Window: {start} to {end}.",
        "Net sales are blank, so these figures are Posist gross." if net_blank else "Net is used where the row has it. Otherwise the figure is gross.",
        "Category and channel are blank on this file." if meta.get("category_filled") is False or meta.get("channel_filled") is False else "Each row keeps its own category and channel when the file has them.",
    ]
    for note in meta.get("notes") or []:
        if "Rosedale" in note or "cannot export" in note:
            lines.append(note)
    if any(token in folded for token in ("channel", "source", "swiggy", "zomato")) and "ticket" not in folded:
        lines.append(
            "Posist Insights cannot export item sales by source, so there is no item-level channel split. "
            "The fallback is store-level channel totals."
        )
        lines.append(_channel_fallback(named or pool))
    lines.append("store | item | gross | qty | from | to | basis")
    for row in pool:
        lines.append(
            " | ".join([
                row["store"],
                row["item"],
                "" if row["gross"] is None else f"{row['gross']:.2f}",
                "" if row["qty"] is None else f"{row['qty']:.0f}",
                row["start"],
                row["end"],
                row["basis"],
            ])
        )
    return "\n".join(line for line in lines if line)


def _channel_fallback(item_rows):
    folder = _ROOT / "data" / "posist" / "daily_sales"
    files = sorted(folder.glob("channel_*.csv")) if folder.is_dir() else []
    if not files:
        return "No store-level channel file is loaded."
    wanted = {row["store"].casefold() for row in item_rows if row.get("store")}
    lines = [f"Store-level channel gross from {files[-1].name}."]
    shown = 0
    with files[-1].open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            store = (raw.get("store") or "").strip()
            if wanted and not any(name in store.casefold() or store.casefold() in name for name in wanted):
                continue
            lines.append(" | ".join([
                store,
                raw.get("source") or "",
                raw.get("sales") or "",
                raw.get("orders") or "",
            ]))
            shown += 1
            if shown >= 8:
                break
    if shown == 0:
        lines.append("No channel row matched that store.")
    return "\n".join(lines)


def _hr_dir():
    folder = _ROOT / "data" / "hr"
    if not folder.is_dir():
        return None
    dated = sorted(path for path in folder.iterdir() if path.is_dir() and len(path.name) == 10)
    return dated[-1] if dated else None


def hr_packet(question, role):
    folded = (question or "").casefold()
    if not any(token in folded for token in ("keka", "headcount", "attrition", "abscond", "joiner", "on notice", "staff")):
        return ""
    if role not in {"owner", "hr"}:
        return "People: not included for this role."
    folder = _hr_dir()
    if folder is None:
        return "People: no Keka aggregate folder is loaded."
    path = folder / "location_headcount.csv"
    if not path.is_file():
        return "People: location headcount is not loaded."
    lines = [
        f"Keka counts as of {folder.name}. November is 1–12 Nov only. Blank is not zero.",
        "Unmatched Keka locations stay unmatched. No names or employee numbers are in this file.",
        "keka_location | posist_store | match | active | on_notice | relieved_ytd",
    ]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    rows.sort(key=lambda row: int(row.get("active") or 0), reverse=True)
    for row in rows[:20]:
        lines.append(
            " | ".join([
                row.get("keka_location") or "",
                row.get("posist_store") or "",
                row.get("match_status") or "",
                row.get("active") or "",
                row.get("on_notice") or "",
                row.get("relieved_ytd") or "",
            ])
        )
    attrition = folder / "attrition_30_90.csv"
    if attrition.is_file():
        lines.append("Attrition windows (exits / (on roll + exits in the window)):")
        with attrition.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                lines.append(
                    f"{row.get('window')} {row.get('start')} to {row.get('end')}: "
                    f"{row.get('exits')} exits, {row.get('attrition_pct')}%"
                )
    return "\n".join(lines)
