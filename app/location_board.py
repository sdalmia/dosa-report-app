"""Owner view of candidate areas. The November model file is read, not approved."""

import json
from pathlib import Path

from app.owner_names import hidden_store, public_name
from app.site_pattern import load_board

_ROOT = Path(__file__).resolve().parents[1]
_MODEL = _ROOT / "data" / "location" / "proposed" / "v2026-11.json"


def _model_note():
    if not _MODEL.is_file():
        return "The November location model is not on file.", ""
    payload = json.loads(_MODEL.read_text(encoding="utf-8"))
    version = payload.get("version") or "v2026-11"
    spearman = payload.get("spearman")
    misses = [row for row in payload.get("backtest") or [] if row.get("miss")]
    misses.sort(key=lambda row: -float(row.get("decile_gap") or 0))
    names = [public_name(row.get("store")) for row in misses[:3]]
    names = [name for name in names if name]
    named = ", ".join(names[:-1]) + (" and " + names[-1] if len(names) > 1 else (names[0] if names else ""))
    note = (
        f"Model {version} is proposed, not approved, so a new pin still uses the prior weights. "
        f"On {payload.get('n') or 27} open stores the rank match is {spearman}. "
        "A typical leave-one-out miss is about a fifth of the ranking."
    )
    if named:
        note += f" {named} are the big misses."
    return note, version


def _why(row):
    brands = [part.strip() for part in (row.get("brands") or "").split(",") if part.strip()][:3]
    brand_bit = ", ".join(brands) if brands else "few known brands"
    nearest = public_name(row.get("nearest")) or "no open store"
    km = row.get("nearest_km")
    distance = f"{km:.1f} km from {nearest}" if isinstance(km, (int, float)) else nearest
    return f"{row.get('brand_count') or 0} brands nearby ({brand_bit}). {distance}."


def _map(rows):
    points = [row for row in rows if row.get("lat") is not None and row.get("lon") is not None]
    if len(points) < 2:
        return ""
    lats = [row["lat"] for row in points]
    lons = [row["lon"] for row in points]
    lat_span = max(lats) - min(lats) or 1
    lon_span = max(lons) - min(lons) or 1
    bits = []
    for row in points:
        x = 8 + (row["lon"] - min(lons)) / lon_span * 84
        y = 8 + (max(lats) - row["lat"]) / lat_span * 84
        bits.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2"><title>{row["area"]}</title></circle>')
    return (
        '<svg class="loc-map" viewBox="0 0 100 100" role="img" aria-label="Candidate areas">'
        + "".join(bits)
        + "</svg>"
    )


def location_home():
    board = load_board()
    rows = []
    for row in board.get("candidates") or []:
        if row.get("airport"):
            continue
        blob = f"{row.get('area') or ''} {row.get('nearest') or ''}"
        if hidden_store(blob):
            continue
        score = row.get("score")
        if score is None:
            continue
        rows.append({
            "area": row.get("area") or "Area",
            "city": row.get("city") or "",
            "score": score,
            "why": _why(row),
            "lat": row.get("lat"),
            "lon": row.get("lon"),
        })
    rows.sort(key=lambda item: (-item["score"], item["area"].casefold()))
    top = rows[:8]
    note, version = _model_note()
    lead = top[0] if top else None
    return {
        "version": version or "v2026-11",
        "note": note,
        "lead": lead,
        "count": len(rows),
        "rows": top,
        "map": _map(top),
    }
