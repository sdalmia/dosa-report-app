"""Read the precomputed Grand Economics files. Nothing here parses a workbook."""

import csv
import json
import os
from pathlib import Path

_CACHE = {}


def directory():
    override = os.environ.get("GRAND_ECONOMICS_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data" / "finance" / "grand_economics"


def _stamp(path):
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _read_json(name):
    path = directory() / name
    stamp = _stamp(path)
    cached = _CACHE.get(name)
    if cached and cached[0] == stamp:
        return cached[1]
    if stamp is None:
        payload = None
    else:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
    _CACHE[name] = (stamp, payload)
    return payload


def summary():
    payload = _read_json("summary.json")
    if not isinstance(payload, dict):
        return {"coverage": [], "threats": [], "cards": [], "ready": False}
    payload = dict(payload)
    payload["ready"] = True
    return payload


def home_finance():
    """One row per city, plus a handful of loss flags. Not the full tables."""
    payload = summary()
    if not payload.get("ready"):
        return None
    home = payload.get("home") if isinstance(payload.get("home"), dict) else {}
    rows = [row for row in (home.get("rows") or []) if isinstance(row, dict)]
    if not rows:
        return None
    flags = []
    for threat in payload.get("threats") or []:
        pct = str(threat.get("pct") or "").replace("%", "").strip()
        try:
            number = float(pct)
        except ValueError:
            number = None
        red = (number is not None and number <= -10) or "L" in str(threat.get("value") or "")
        flags.append({
            "store": threat.get("store") or "",
            "city": threat.get("city") or "",
            "month": threat.get("month") or "",
            "value": threat.get("value") or "",
            "pct": threat.get("pct") or "",
            "tone": "red" if red else "amber",
        })
    flags.sort(key=lambda item: (0 if item["tone"] == "red" else 1, item["city"], item["store"]))
    return {"month": home.get("month") or "", "rows": rows, "flags": flags[:5]}


def stores():
    payload = _read_json("stores.json")
    if not isinstance(payload, dict):
        return {"cities": []}
    return payload


def detail(anchor):
    payload = _read_json("details.json")
    if not isinstance(payload, dict):
        return None
    found = payload.get(anchor)
    if not isinstance(found, dict):
        return None
    return found


def _ledger_path():
    named = os.environ.get("TALLY_LEDGER_FILE")
    if named:
        return Path(named)
    folder = os.environ.get("TALLY_DATA_DIR")
    if folder:
        return Path(folder) / "ledger_entries.csv"
    return Path(__file__).resolve().parents[2] / "data" / "tally" / "ledger_entries.csv"


def _slug(text):
    import re

    lowered = str(text or "").lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


def _rupee(value):
    text = str(value or "").strip()
    if not text:
        return ""
    cleaned = text.replace("₹", "").replace(",", "")
    try:
        number = float(cleaned)
    except ValueError:
        return text
    sign = "-" if number < 0 else ""
    whole, _, frac = f"{abs(number):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while head:
            parts.append(head[-2:])
            head = head[:-2]
        whole = ",".join(reversed(parts)) + "," + tail
    shown = f"{sign}₹{whole}"
    if frac != "00":
        shown = f"{shown}.{frac}"
    return shown


def ledger_for(city, store, month_key):
    """Rows for this city, store, and month. A missing file returns nothing."""
    path = _ledger_path()
    stamp = _stamp(path)
    cached = _CACHE.get("ledger")
    if cached and cached[0] == stamp:
        rows = cached[1]
    else:
        rows = []
        if stamp is not None:
            try:
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    rows = list(csv.DictReader(handle))
            except OSError:
                rows = []
        _CACHE["ledger"] = (stamp, rows)
    if not rows or not month_key:
        return []
    city_key = str(city or "").casefold()
    store_name = str(store or "").strip()
    store_key = store_name.casefold()
    store_slug = _slug(store_name)
    found = []
    for raw in rows:
        if str(raw.get("city") or "").strip().casefold() != city_key:
            continue
        if str(raw.get("date") or "").strip()[:7] != month_key:
            continue
        row_store = str(raw.get("store") or "").strip()
        if not store_name:
            if row_store:
                continue
        elif row_store.casefold() != store_key and _slug(row_store) != store_slug:
            continue
        found.append({
            "date": str(raw.get("date") or "").strip(),
            "ledger": str(raw.get("ledger") or "").strip(),
            "voucher": str(raw.get("voucher") or "").strip(),
            "party": str(raw.get("party") or "").strip(),
            "amount": _rupee(raw.get("amount")),
        })
    return found
