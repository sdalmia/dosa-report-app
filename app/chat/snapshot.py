"""Compact figures cached in memory.

A question reads this snapshot. CSVs are parsed again only when a file changes.
Replacing data/store_health/sales_pred_vs_actual_summary.json, or the daily
sales files, is enough for the next answer to see them. No code change.
"""

import json
from datetime import timedelta
from pathlib import Path

from app.access import is_owner
from app.chat.reelo_storewise import PERIOD as REELO_PERIOD
from app.chat.reelo_storewise import load_storewise
from app.food_courts import is_mall_food_court
from app.store_health.contract import load_feeds
from app.store_health.day_notes import FARIDABAD_CLOSED_FROM

_CACHE = {"stamp": None, "data": None}
_ROOT = Path(__file__).resolve().parents[2]


def summary_path():
    return _ROOT / "data" / "store_health" / "sales_pred_vs_actual_summary.json"


def _mtime(path):
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _stamp():
    names = [
        summary_path(),
        _ROOT / "data" / "store_health" / "posist_daily.csv",
        _ROOT / "data" / "store_health" / "sales_pred_vs_actual.csv",
        _ROOT / "data" / "store_health" / "famepilot.csv",
        _ROOT / "data" / "store_health" / "mystery_audit.csv",
        _ROOT / "data" / "store_health" / "keka.csv",
        _ROOT / "data" / "reelo" / "reelo_storewise_latest.csv",
        _ROOT / "data" / "finance" / "grand_economics" / "summary.json",
        _ROOT / "data" / "procurement" / "procurement_summary.json",
    ]
    return tuple(_mtime(path) for path in names)


def _out_of_base(store, day):
    text = (store or "").casefold()
    if "chattarpur" in text or "gk1" in text or "gk 1" in text:
        return True
    if "faridabad" in text and day is not None and day >= FARIDABAD_CLOSED_FROM:
        return True
    return False


def procurement_path():
    return _ROOT / "data" / "procurement" / "procurement_summary.json"


def _load_procurement():
    """One file. A daily load replaces it. Every field is optional."""
    path = procurement_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_summary():
    path = summary_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _num(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").replace("₹", ""))
    except (TypeError, ValueError):
        return None


def _movers(feeds):
    grouped = {}
    for (store, day), row in (feeds.get("posist") or {}).items():
        if _out_of_base(store, day):
            continue
        gross = row.get("gross")
        if gross is None:
            continue
        grouped.setdefault(store, []).append((day, float(gross)))
    found = []
    for store, points in grouped.items():
        points.sort()
        last_day, last_gross = points[-1]
        prior_day = last_day - timedelta(days=7)
        prior = next((gross for day, gross in points if day == prior_day), None)
        if prior in (None, 0):
            continue
        pct = (last_gross - prior) / prior * 100
        note = ""
        if "rosedale" in store.casefold():
            note = "Partially operational, not unexplained softness"
        found.append({
            "store": store,
            "date": last_day.isoformat(),
            "prior_date": prior_day.isoformat(),
            "gross": round(last_gross, 2),
            "prior_gross": round(prior, 2),
            "pct": round(pct, 1),
            "note": note,
        })
    found.sort(key=lambda row: row["pct"])
    return found


def _forecast_gaps(feeds, summary):
    wanted = summary.get("actuals_through") or summary.get("as_of_date")
    rows = []
    for (store, day), row in (feeds.get("calendar") or {}).items():
        if wanted and day.isoformat() != wanted:
            continue
        if _out_of_base(store, day):
            continue
        actual = _num(row.get("actual_gross"))
        mid = _num(row.get("pred_mid"))
        if actual is None or mid in (None, 0):
            continue
        gap = (actual - mid) / mid * 100
        rows.append({
            "store": store,
            "date": day.isoformat(),
            "actual": round(actual, 2),
            "mid": round(mid, 2),
            "pct": round(gap, 1),
        })
    if rows:
        rows.sort(key=lambda row: row["pct"])
        return rows
    # Deeper fallback: latest day that has both figures.
    best = {}
    for (store, day), row in (feeds.get("calendar") or {}).items():
        if _out_of_base(store, day):
            continue
        actual = _num(row.get("actual_gross"))
        mid = _num(row.get("pred_mid"))
        if actual is None or mid in (None, 0):
            continue
        current = best.get(store)
        if current is None or day > current[0]:
            best[store] = (day, actual, mid)
    built = []
    for store, (day, actual, mid) in best.items():
        built.append({
            "store": store,
            "date": day.isoformat(),
            "actual": round(actual, 2),
            "mid": round(mid, 2),
            "pct": round((actual - mid) / mid * 100, 1),
        })
    built.sort(key=lambda row: row["pct"])
    return built


def _famepilot(feeds):
    rows = []
    for store, group in (feeds.get("famepilot_by_store") or {}).items():
        if isinstance(group, dict):
            row = group
        elif isinstance(group, (list, tuple)) and group:
            row = group[-1]
        else:
            continue
        rating = _num(row.get("rating"))
        if rating is None:
            continue
        rows.append({
            "store": store,
            "rating": rating,
            "reviews": _num(row.get("review_count")),
        })
    rows.sort(key=lambda row: row["rating"])
    return rows[:8]


def _audit(feeds):
    rows = []
    for store, row in (feeds.get("audit_by_store") or {}).items():
        if not row:
            continue
        score = _num(str(row.get("avg_score") or "").replace("%", ""))
        if score is None:
            continue
        rows.append({
            "store": store,
            "period": (row.get("period") or "").strip(),
            "score": score,
        })
    rows.sort(key=lambda row: row["score"])
    return rows[:8]


def _finance():
    path = _ROOT / "data" / "finance" / "grand_economics" / "summary.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cards = payload.get("cards") if isinstance(payload, dict) else None
    if not isinstance(cards, list):
        return []
    kept = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        label = str(card.get("label") or "")
        if "EBITDA" not in label:
            continue
        kept.append({
            "kicker": str(card.get("kicker") or ""),
            "value": str(card.get("value") or ""),
            "label": label,
        })
    return kept


def _aliases():
    from app.store_master import get_index

    pairs = []
    for row in get_index().rows:
        code = (row.get("posist_code") or "").strip()
        if not code:
            continue
        names = [
            row.get("posist_name"),
            row.get("display_name"),
            row.get("reelo_name"),
            row.get("famepilot_name"),
            row.get("keka_location"),
            code,
        ]
        notes = row.get("notes") or ""
        if "Known names:" in notes:
            names.extend(part.strip() for part in notes.split("Known names:", 1)[1].split("|"))
        for name in names:
            text = " ".join(str(name or "").split())
            if text:
                pairs.append((text, code, row))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    return pairs


def _food_index():
    try:
        from app.procurement.food_cost import build_food_cost, store_key
        from app.procurement.loader import load_procurement

        view = build_food_cost(load_procurement())
    except Exception:
        return {}
    found = {}
    for store in view.get("stores") or []:
        pct = (store.get("food_cost_pct") or {}).get("value")
        text = (store.get("food_cost_pct") or {}).get("text") or ""
        found[store.get("key") or ""] = {
            "name": store.get("posist_name") or store.get("name") or "",
            "pct": pct,
            "text": text,
            "period": view.get("week_label") or view.get("period_label") or "",
        }
    return found


def _one(rows, store):
    for row in rows or []:
        if row.get("store") == store:
            return row
    return None


def _dossiers(feeds, movers, forecast, reviews, audit, reelo):
    import re

    from app.procurement.food_cost import store_key

    food = _food_index()
    by_name = {}
    dossiers = {}
    aliases = []
    for name, code, master in _aliases():
        posist = (master.get("posist_name") or name).strip()
        if code not in dossiers:
            mover = _one(movers, posist)
            gap = _one(forecast, posist)
            review = _one(reviews, posist)
            audited = _one(audit, posist)
            reelo_name = (master.get("reelo_name") or "").casefold()
            reelo_row = next((row for row in reelo if row["store"].casefold() == reelo_name), None) if reelo_name else None
            hr_rows = (feeds.get("keka_by_store") or {}).get(posist)
            if isinstance(hr_rows, dict):
                hr = hr_rows
            elif isinstance(hr_rows, (list, tuple)) and hr_rows:
                hr = hr_rows[-1]
            else:
                hr = None
            food_row = food.get(store_key(posist))
            dossiers[code] = {
                "code": code,
                "name": (master.get("display_name") or posist).strip(),
                "posist": posist,
                "sales": mover,
                "forecast": gap,
                "review": review,
                "audit": audited,
                "reelo": reelo_row,
                "food": food_row,
                "hr": {
                    "lead": (hr.get("primary_lead") or "").strip(),
                    "headcount": hr.get("headcount"),
                } if isinstance(hr, dict) else None,
            }
        aliases.append((name, code))
        by_name[name.casefold()] = code
    return {"by_code": dossiers, "aliases": aliases, "_re": re}


def named_store(question, data):
    """Longest store name or code that appears in the question."""
    import re

    folded = " ".join((question or "").casefold().split())
    best = None
    for name, code in data.get("aliases") or []:
        token = " ".join(name.casefold().split())
        if len(token) < 3:
            continue
        if len(token) < 5:
            if not re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", folded):
                continue
        elif token not in folded:
            continue
        if best is None or len(token) > best[0]:
            best = (len(token), code)
    if not best:
        return None
    return (data.get("dossiers") or {}).get(best[1])


def _build():
    summary = _load_summary()
    try:
        feeds = load_feeds()
    except Exception:
        feeds = {}
    reelo = load_storewise()
    movers = _movers(feeds)
    forecast = _forecast_gaps(feeds, summary)
    reviews = _famepilot(feeds)
    audit = _audit(feeds)
    joined = _dossiers(feeds, movers, forecast, reviews, audit, reelo)
    return {
        "summary": summary,
        "movers": movers,
        "forecast": forecast,
        "reviews": reviews,
        "audit": audit,
        "finance": _finance(),
        "reelo": reelo,
        "reelo_period": REELO_PERIOD,
        "reelo_loaded": bool(reelo),
        "sales_loaded": bool(summary) or bool(feeds.get("posist")),
        "procurement": _load_procurement(),
        "dossiers": joined["by_code"],
        "aliases": joined["aliases"],
    }


def snapshot():
    """The in-memory snapshot. Rebuilt only when a source file changes."""
    stamp = _stamp()
    if _CACHE["stamp"] == stamp and _CACHE["data"] is not None:
        return _CACHE["data"]
    data = _build()
    _CACHE["stamp"] = stamp
    _CACHE["data"] = data
    return data


def reset_snapshot():
    _CACHE["stamp"] = None
    _CACHE["data"] = None


def view_for(email=None, role=None):
    """Accounts for finance or owner. HR for HR or owner. Everyone else gets ops."""
    if role is None:
        role = "owner" if is_owner(email) else "ops"
    data = snapshot()
    out = dict(data)
    dossiers = {}
    for code, row in (data.get("dossiers") or {}).items():
        copy = dict(row)
        if role not in {"owner", "hr"}:
            copy["hr"] = None
        dossiers[code] = copy
    out["dossiers"] = dossiers
    if role not in {"owner", "finance"}:
        out["finance"] = []
    out["role"] = role
    return out
