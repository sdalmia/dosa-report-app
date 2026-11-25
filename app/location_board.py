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
    misses = [row for row in payload.get("backtest") or [] if row.get("miss")]
    misses.sort(key=lambda row: -float(row.get("decile_gap") or 0))
    names = [public_name(row.get("store")) for row in misses[:3]]
    names = [name for name in names if name]
    named = ", ".join(names[:-1]) + (" and " + names[-1] if len(names) > 1 else (names[0] if names else ""))
    note = (
        f"Model {version} is proposed, not approved, so a new pin still uses the prior weights. "
        "Model accuracy: moderate; treat as a shortlist."
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
    """Two labelled outlines. Pins are numbered in the same order as the list."""
    ncr = {"lat": (28.25, 28.95), "lon": (76.70, 77.55), "ox": 8, "oy": 18, "w": 78, "h": 70}
    kol = {"lat": (22.40, 22.70), "lon": (88.20, 88.55), "ox": 112, "oy": 28, "w": 76, "h": 52}
    bits = [
        '<svg class="loc-map" viewBox="0 0 200 100" role="img" aria-label="Delhi NCR and Kolkata candidate areas">',
        '<path class="loc-land" d="M18 24 L62 16 L84 34 L78 62 L48 78 L16 64 Z"/>',
        '<path class="loc-land" d="M124 36 L168 30 L186 48 L176 72 L132 76 L118 54 Z"/>',
        '<text class="loc-label" x="28" y="14">Delhi NCR</text>',
        '<text class="loc-label" x="124" y="24">Kolkata</text>',
    ]
    for index, row in enumerate(rows, start=1):
        lat, lon = row.get("lat"), row.get("lon")
        city = (row.get("city") or "").casefold()
        box = kol if "kolkata" in city or (isinstance(lat, (int, float)) and lat < 26) else ncr
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        lat0, lat1 = box["lat"]
        lon0, lon1 = box["lon"]
        x = box["ox"] + (min(max(lon, lon0), lon1) - lon0) / (lon1 - lon0) * box["w"]
        y = box["oy"] + (lat1 - min(max(lat, lat0), lat1)) / (lat1 - lat0) * box["h"]
        bits.append(
            f'<g class="loc-pin"><circle cx="{x:.1f}" cy="{y:.1f}" r="7"></circle>'
            f'<text x="{x:.1f}" y="{y + 2.4:.1f}">{index}</text>'
            f"<title>{index}. {row['area']}</title></g>"
        )
    bits.append("</svg>")
    return "".join(bits)


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
