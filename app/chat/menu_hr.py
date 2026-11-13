"""October menu mix and the 12 Nov Keka counts.

Menu answers use gross when net is blank and keep each row's own dates.
People counts are owner and HR only. Names and employee numbers are not in these files.
"""

import csv
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


def newest_menu():
    """The mix with the latest date_to. Older files stay available for category."""
    best = None
    best_end = ""
    for path in _menu_files():
        rows = _read(path)
        end = max((row.get("date_to") or row.get("period_end") or "") for row in rows) if rows else ""
        if best is None or end > best_end:
            best = (path, rows)
            best_end = end
    return best


def menu_packet(question):
    folded = (question or "").casefold()
    if not any(token in folded for token in ("menu", "item", "dosa", "best sell", "contribution", "mix")):
        return ""
    picked = newest_menu()
    if not picked:
        return "Menu mix: no menu_mix file is loaded."
    path, rows = picked
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
    net_blank = all(row["net"] is None for row in pool)
    lines = [
        f"Menu mix from {path.name}.",
        "Net sales are blank, so these figures are Posist gross." if net_blank else "Net is used where the row has it. Otherwise the figure is gross.",
        "Each row keeps its own period. Category on this file is blank where the source had none.",
        "store | item | gross | qty | from | to | basis",
    ]
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
