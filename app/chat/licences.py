"""Store licences. Status is recomputed from the expiry date.

The CSV status is the extract's own label. Answers use the expiry compared
with the day of the question. Licence numbers stay in the file and are
included only when the question asks for a number. Closed stores are left out.
"""

import csv
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CLOSED = ("chattarpur", "gk1", "gk 1", "faridabad")
_NUMBER_ASK = ("number", "licence no", "license no", "licence number", "license number")
_NCR_NOTE = "NCR dates come from certificates. A dated NCR tracker is pending."


def directory():
    override = os.getenv("COMPLIANCE_DATA_DIR")
    if override:
        return Path(override)
    return _ROOT / "data" / "compliance"


def _parse_day(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def newest_file():
    base = directory()
    if not base.is_dir():
        return None
    dated = []
    for path in base.iterdir():
        if path.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name):
            candidate = path / "licences.csv"
            if candidate.is_file():
                dated.append((path.name, candidate))
    if dated:
        return max(dated)[1]
    direct = base / "licences.csv"
    return direct if direct.is_file() else None


def status_on(expiry, file_status, as_of):
    """Recompute from the expiry. Blank expiries keep missing or unknown."""
    if expiry is None:
        token = str(file_status or "").strip().casefold()
        if token == "missing":
            return "missing"
        return "unknown"
    if expiry < as_of:
        return "expired"
    if expiry <= as_of + timedelta(days=30):
        return "expiring_30d"
    if expiry <= as_of + timedelta(days=90):
        return "expiring_90d"
    return "valid"


def _closed(store):
    text = (store or "").casefold()
    return any(token in text for token in _CLOSED)


def load(as_of=None):
    """Rows with status recomputed. A missing file is an empty list."""
    as_of = as_of or date.today()
    path = newest_file()
    if path is None:
        return []
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            store = (raw.get("store") or "").strip()
            if not store or _closed(store):
                continue
            expiry = _parse_day(raw.get("expiry"))
            rows.append({
                "store": store,
                "city": (raw.get("city") or "").strip(),
                "licence_type": (raw.get("licence_type") or "").strip(),
                "licence_no": (raw.get("licence_no") or "").strip(),
                "issued": (raw.get("issued") or "").strip(),
                "expiry": expiry.isoformat() if expiry else "",
                "status": status_on(expiry, raw.get("status"), as_of),
                "notes": (raw.get("notes") or "").strip(),
                "source_file": (raw.get("source_file") or "").strip(),
            })
    return rows


def summary(as_of=None):
    rows = load(as_of)
    counts = {"expired": 0, "expiring_30d": 0, "expiring_90d": 0, "missing": 0, "unknown": 0, "valid": 0}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"loaded": bool(rows), "rows": len(rows), "as_of": (as_of or date.today()).isoformat(), **counts}


def _wants_number(question):
    folded = (question or "").casefold()
    return any(token in folded for token in _NUMBER_ASK)


def _slice(question, rows, as_of):
    """Expired plus anything due inside 30, 60, or 90 days. None means the whole file."""
    folded = (question or "").casefold()
    if "missing" in folded and "expir" not in folded:
        return [row for row in rows if row["status"] == "missing"]
    if "expired" in folded and "expir" not in folded.replace("expired", ""):
        return [row for row in rows if row["status"] == "expired"]
    days = None
    if "90" in folded:
        days = 90
    elif "60" in folded:
        days = 60
    elif "30" in folded or "expir" in folded:
        days = 30
    if days is None:
        return rows
    horizon = as_of + timedelta(days=days)
    picked = []
    for row in rows:
        if row["status"] == "expired":
            picked.append(row)
            continue
        expiry = _parse_day(row["expiry"])
        if expiry is not None and as_of <= expiry <= horizon:
            picked.append(row)
    return picked


def relevant(question):
    folded = (question or "").casefold()
    return any(token in folded for token in ("licence", "license", "fssai", "compliance", "expir"))


def allowed(role):
    return (role or "ops") in {"owner", "ops"}


def packet(question, role, as_of=None):
    """Text for the model and the offline answer. Empty when this role cannot see it."""
    if not allowed(role):
        return ""
    as_of = as_of or date.today()
    rows = load(as_of)
    if not rows:
        return "Licences: no licences.csv is loaded."
    picked = _slice(question, rows, as_of)
    show_no = _wants_number(question)
    folded = (question or "").casefold()
    if "ncr" in folded or "delhi" in folded:
        picked = [row for row in picked if row["city"].casefold() == "ncr"]
    elif "kolkata" in folded:
        picked = [row for row in picked if row["city"].casefold() == "kolkata"]
    store_token = ""
    for row in rows:
        name = row["store"].casefold()
        if len(name) > 4 and name in folded:
            store_token = name
            break
    if store_token:
        picked = [row for row in picked if row["store"].casefold() == store_token]
    picked.sort(key=lambda row: (row["expiry"] or "9999", row["store"], row["licence_type"]))
    lines = [
        f"Licences as of {as_of.isoformat()}. Status is recomputed from the expiry date, not copied from the file.",
        _NCR_NOTE,
        "Closed stores (Chattarpur, GK1, Faridabad Sec-15) are excluded.",
        "Columns: store | city | type | expiry | status" + (" | licence_no" if show_no else ""),
    ]
    shown = picked[:40]
    if not shown:
        lines.append("(none in this slice)")
    for row in shown:
        cells = [row["store"], row["city"], row["licence_type"], row["expiry"] or "blank", row["status"]]
        if show_no:
            cells.append(row["licence_no"] or "blank")
        lines.append(" | ".join(cells))
    if len(picked) > len(shown):
        lines.append(f"{len(picked) - len(shown)} more rows are in the file and were left out of this slice.")
    counts = summary(as_of)
    lines.append(
        f"Counts: {counts['expired']} expired, {counts['expiring_30d']} expiring within 30 days, "
        f"{counts['missing']} missing, {counts['unknown']} unknown, {counts['valid']} valid."
    )
    return "\n".join(lines)


def red_flags(as_of=None):
    """Expired and due within 30 days. For the owner red-flag list and the home card."""
    as_of = as_of or date.today()
    rows = [row for row in load(as_of) if row["status"] in {"expired", "expiring_30d"}]
    rows.sort(key=lambda row: (0 if row["status"] == "expired" else 1, row["expiry"] or "9999", row["store"]))
    return rows


def home_card(role, as_of=None):
    if not allowed(role):
        return None
    counts = summary(as_of)
    if not counts["loaded"]:
        return None
    if counts["expired"] == 0 and counts["expiring_30d"] == 0:
        return None
    return {
        "kind": "licences",
        "title": "Licences",
        "line": f"{counts['expired']} licences expired, {counts['expiring_30d']} expire in 30 days",
        "question": "Which licences expire in the next 30 days?",
    }
