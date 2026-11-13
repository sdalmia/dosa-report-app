"""Finance, procurement, Posist fixes, growth, trends, and the sales calendar.

Every rupee comes from a file. A thin series is skipped. Finance stays on
owner and finance roles.
"""

import csv
import re
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FINANCE_LINES = (
    "ebitda", "fnb_cost", "gross_revenue", "net_revenue", "rent", "salary",
    "ads", "purchases", "electricity", "gas", "commission", "wastage",
)
_CLOSED = ("chattarpur", "gk1", "gk 1")
_FARIDABAD_OUT = date(2026, 10, 23)
_ROSEDALE_OUT = date(2026, 11, 1)


def _num(value):
    text = str(value or "").strip().replace(",", "").replace("%", "").replace("₹", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _day(value):
    text = str(value or "").strip()
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _inr(value):
    if value is None:
        return ""
    number = float(value)
    sign = "-" if number < 0 else ""
    whole = int(round(abs(number)))
    return f"{sign}₹{whole:,}"


def _read(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _closed_name(name):
    text = (name or "").casefold()
    return any(token in text for token in _CLOSED)


def _skip_day(store, day, region=""):
    if day is None:
        return True
    if _closed_name(store):
        return True
    text = (store or "").casefold()
    if "faridabad" in text and day >= _FARIDABAD_OUT:
        return True
    if "rosedale" in text and day >= _ROSEDALE_OUT:
        return True
    return False


def _pack(text, as_of, topic, question, owner, table=None, chart=None, calendar=None):
    from app.chat.facts import _pack as pack

    result = pack(text, as_of, topic, question, owner, table=table, chart=chart, source={"text": text})
    if calendar:
        result["calendar"] = calendar
    return result


def finance_text(question, role):
    if role not in {"owner", "finance"}:
        return "Finance: not included for this role."
    path = _ROOT / "data" / "finance" / "grand_economics" / "grand_economics_tidy.csv"
    if not path.is_file():
        return "Finance: Grand Economics tidy file is not loaded."
    folded = (question or "").casefold()
    wanted_lines = [line for line in _FINANCE_LINES if line.replace("_", " ") in folded or line in folded]
    if "food cost" in folded:
        wanted_lines.append("fnb_cost")
    if "p&l" in folded or "p and l" in folded or not wanted_lines:
        wanted_lines = list(_FINANCE_LINES[:8])
    city = "ncr" if any(token in folded for token in ("ncr", "delhi", "north")) else ""
    if "kolkata" in folded or "east" in folded:
        city = "kolkata"
    rows = []
    latest = ""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            month = raw.get("month") or ""
            if month > latest:
                latest = month
            if (raw.get("level") or "") != "city" and (raw.get("store") or "").strip():
                if city and city not in (raw.get("city") or "").casefold() and city not in (raw.get("store") or "").casefold():
                    continue
            if wanted_lines and (raw.get("line") or "") not in wanted_lines:
                continue
            if city and city not in (raw.get("city") or "").casefold():
                continue
            if month < "2026-07":
                continue
            rows.append(raw)
    rows = [row for row in rows if not (row.get("store") or "").strip()]
    rows.sort(key=lambda row: (row.get("month") or "", row.get("city") or "", row.get("line") or ""))
    tail = rows[-24:]
    lines = [
        f"Grand Economics tidy file. Latest month on file: {latest or 'unknown'}. October 2026 is not in this file.",
        "NCR recipe cost is higher by design (3 chutneys versus 1). Compare a city only with itself.",
        "August and September Kolkata advertising was booked in October, so those months understate ads.",
        "city | month | line | value",
    ]
    for row in tail:
        lines.append(" | ".join([
            row.get("city") or "",
            row.get("month") or "",
            row.get("line") or "",
            row.get("value") or "",
        ]))
    if not tail:
        lines.append("(no rows matched)")
    return "\n".join(lines)


def _asks_finance(question):
    folded = (question or "").casefold()
    if "profit" in folded and "company" in folded:
        return False
    return any(token in folded for token in (
        "grand economics", "p&l", "p and l", "rent ratio", "ebitda by", "line item",
    ))


def _recipe_rows(question):
    path = _ROOT / "data" / "procurement" / "menu_item_cost.csv"
    if not path.is_file():
        path = _ROOT / "data" / "procurement" / "recipe_cost_by_item.csv"
    if not path.is_file():
        return "Recipe cost file is not loaded.", []
    folded = (question or "").casefold()
    words = [word for word in re.findall(r"[a-z]{4,}", folded) if word not in {
        "what", "recipe", "cost", "plate", "item", "store", "with", "this", "that", "from", "have", "does",
    }]
    picked = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            name = (raw.get("item_name") or raw.get("menu_item") or "").strip()
            if not name:
                continue
            if words and not all(word in name.casefold() for word in words[:3]):
                continue
            cost = _num(raw.get("cost_per_portion_avg") or raw.get("cost_per_unit_avg_price"))
            picked.append((cost or 0, name, raw.get("city") or raw.get("outlet") or "", cost, raw.get("ingredient_count") or ""))
            if not words and len(picked) > 4000:
                break
    picked.sort(key=lambda item: item[0], reverse=True)
    lines = [f"Recipe cost from {path.name}. A blank selling price means the file has no price. Compare a city only with itself."]
    table = []
    for _sort, name, city, cost, ingredients in picked[:12]:
        lines.append(f"{city} | {name} | plate cost {_inr(cost) if cost is not None else 'blank'} | ingredients {ingredients}")
        table.append([city, name, _inr(cost) if cost is not None else "", str(ingredients)])
    if len(lines) == 1:
        lines.append("No recipe row matched that item.")
    return "\n".join(lines), table


def _procurement_text(question):
    folded = (question or "").casefold()
    root = _ROOT / "data" / "procurement"
    if any(token in folded for token in ("recipe", "plate cost", "costing")):
        text, _table = _recipe_rows(question)
        return text
    if any(token in folded for token in ("short", "reconcil", "po vs", "purchase order", "missed")):
        path = root / "po_coverage.csv"
        if not path.is_file():
            return "PO coverage file is not loaded."
        rows = _read(path)
        rows.sort(key=lambda row: _num(row.get("pct_lines_with_po")) or 0)
        lines = [
            "PO versus receipts. Period is the one on each row. A low percent means fewer lines carried a PO quantity.",
            "Many warehouse receipts in this drop have blank PO fields, so short delivery often cannot be measured.",
            "city | supplier | received_value | pct_lines_with_po | first | last",
        ]
        for row in rows[:10]:
            lines.append(" | ".join([
                row.get("city") or "",
                row.get("supplier") or "",
                row.get("received_value") or "",
                row.get("pct_lines_with_po") or "",
                row.get("first_date") or "",
                row.get("last_date") or "",
            ]))
        return "\n".join(lines)
    if "wastage" in folded:
        path = root / "store_item_wastage_top.csv"
        if not path.is_file():
            return "Wastage file is not loaded."
        rows = _read(path)
        rows.sort(key=lambda row: _num(row.get("total_wastage_amt")) or 0, reverse=True)
        lines = ["Wastage by store and item. Amounts are from the wastage file, not estimated.", "store | item | wastage_amt"]
        for row in rows[:10]:
            lines.append(" | ".join([
                row.get("store") or row.get("deployment") or "",
                row.get("item_name") or "",
                row.get("total_wastage_amt") or "",
            ]))
        return "\n".join(lines)
    if any(token in folded for token in ("vendor", "supplier")):
        path = root / "supplier_summary.csv"
        if not path.is_file():
            return "Supplier file is not loaded."
        rows = _read(path)
        rows.sort(key=lambda row: _num(row.get("total_value")) or 0, reverse=True)
        lines = [
            "Suppliers from grn lines, 9 Sep–8 Oct 2026. Share is of that city's line total, excluding freight.",
            "city | supplier | total_value | share_pct | first | last",
        ]
        for row in rows[:10]:
            lines.append(" | ".join([
                row.get("city") or "",
                row.get("supplier") or "",
                row.get("total_value") or "",
                row.get("share_of_city_spend_pct") or "",
                row.get("first_date") or "",
                row.get("last_date") or "",
            ]))
        return "\n".join(lines)
    path = root / "grn_lines_warehouses.csv"
    if not path.is_file():
        return "Procurement detail files are not loaded."
    return (
        "Procurement files cover warehouse GRN 9 Sep–8 Oct 2026, recipe cost, PO coverage, and wastage. "
        "Ask for a vendor, an item, wastage, or short delivery to pull that slice."
    )


def _asks_procurement(question):
    folded = (question or "").casefold()
    if any(token in folded for token in ("ticket", "famepilot", "commission", "24.78")):
        return False
    return any(token in folded for token in (
        "recipe cost", "plate cost", "costing", "short-deliver", "short deliver",
        "po vs", "reconciliation", "wastage", "which vendor", "vendors short",
    ))


def _impact_rupee(text):
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)", str(text or ""))
    if not match:
        return None
    return _num(match.group(1))


def posist_fixes_text():
    folder = _ROOT / "data" / "posist_fixes"
    chosen = None
    if folder.is_dir():
        dated = sorted(path for path in folder.iterdir() if path.is_dir() and (path / "issues.csv").is_file())
        if dated:
            chosen = dated[-1] / "issues.csv"
    if chosen is None:
        return "Posist fixes: no issues.csv is loaded."
    rows = _read(chosen)
    ranked = sorted(rows, key=lambda row: _impact_rupee(row.get("rupee_impact_if_known")) or 0, reverse=True)
    lines = [
        f"Posist fixes from {chosen.parent.name}. Primary list is the issues file. Blank rupee impact stays blank.",
        "Delhi recipe variance is not covered yet.",
        "store | item | impact | since | fix | owner",
    ]
    for row in ranked:
        lines.append(" | ".join([
            row.get("store") or "",
            row.get("item_or_area") or "",
            row.get("rupee_impact_if_known") or "",
            row.get("since") or "",
            row.get("fix") or "",
            row.get("owner") or "",
        ]))
    lines.append(_automated_menu_gaps())
    return "\n".join(lines)


def _automated_menu_gaps():
    """Items with sales and no recipe-cost name. Labelled so they are not the 12 Nov list."""
    menu = _ROOT / "data" / "menu"
    mixes = sorted(menu.glob("menu_mix_*.csv")) if menu.is_dir() else []
    recipe = _ROOT / "data" / "procurement" / "recipe_cost_by_item.csv"
    if not mixes or not recipe.is_file():
        return "Automated check: recipe-cost file or menu mix is not both loaded, so no extra gap is stated."
    names = set()
    with recipe.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            item = (raw.get("menu_item") or raw.get("item_name") or "").strip().casefold()
            if item:
                names.add(item)
    dated = [path for path in mixes if "2026-11-12" in path.name] or mixes
    path = dated[-1]
    missing = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            item = (raw.get("item") or "").strip()
            gross = _num(raw.get("gross") or raw.get("total_sales"))
            if not item or gross is None:
                continue
            if item.casefold() in names:
                continue
            missing.append((gross, item, raw.get("store") or ""))
    missing.sort(reverse=True)
    if not missing:
        return "Automated check: every menu-mix item name is on the recipe-cost file."
    lines = ["Automated check, not the 12 Nov issues file: menu-mix items with no recipe-cost name, largest gross first."]
    for gross, item, store in missing[:5]:
        lines.append(f"{store} | {item} | gross {_inr(gross)}")
    return "\n".join(lines)


def _asks_fixes(question):
    folded = (question or "").casefold()
    return any(token in folded for token in ("posist fix", "fix on posist", "what can we fix", "data can we fix"))


def _span(start, end):
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    if start.month == end.month and start.year == end.year:
        return f"{start.day}–{end.day} {months[start.month - 1]}"
    if start.year == end.year:
        return f"{start.day} {months[start.month - 1]}–{end.day} {months[end.month - 1]}"
    return f"{start.isoformat()}–{end.isoformat()}"


def _display_store(name):
    text = re.sub(r"\s*\([^)]*\)", "", name or "")
    text = re.sub(r"(?i)^dosa coffee\s*-\s*", "", text).strip()
    return " ".join(word[:1].upper() + word[1:] if word else "" for word in text.split())


def _lakh(value):
    number = abs(float(value))
    if number >= 10000000:
        return f"₹{number / 10000000:.2f}Cr"
    if number >= 100000:
        return f"₹{number / 100000:.2f}L"
    return f"₹{number:,.0f}"


def _navratri_days():
    path = _ROOT / "data" / "posist" / "sales_pred_vs_actual.csv"
    found = set()
    if not path.is_file():
        return found
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            blob = " ".join([raw.get("tier") or "", raw.get("drivers") or "", raw.get("notes") or ""]).casefold()
            if "navratri" not in blob:
                continue
            day = _day(raw.get("date"))
            if day:
                found.add(day)
    return found


def _north(store, region):
    if (region or "").casefold() in {"north", "ncr", "delhi"}:
        return True
    return bool(re.search(r"\(02/", store or ""))


def _sales_by_store():
    """Store gross by day. Dated daily_sales files override the cumulative file."""
    by_store = {}
    regions = {}
    daily = _ROOT / "data" / "store_health" / "posist_daily.csv"
    if daily.is_file():
        with daily.open(newline="", encoding="utf-8-sig") as handle:
            for raw in csv.DictReader(handle):
                day = _day(raw.get("date"))
                store = (raw.get("store") or "").strip()
                gross = _num(raw.get("gross"))
                if day is None or not store or gross is None:
                    continue
                by_store.setdefault(store, {})[day] = gross
                regions[store] = raw.get("region") or ""
    folder = _ROOT / "data" / "posist" / "daily_sales"
    latest = None
    if folder.is_dir():
        for path in folder.glob("sales_*.csv"):
            stamp = _day(path.stem.replace("sales_", ""))
            if stamp and (latest is None or stamp > latest):
                latest = stamp
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for raw in csv.DictReader(handle):
                    day = _day(raw.get("date")) or stamp
                    store = (raw.get("store") or "").strip()
                    gross = _num(raw.get("gross"))
                    if day is None or not store or gross is None:
                        continue
                    by_store.setdefault(store, {})[day] = gross
    return by_store, regions, latest


def _weekly_gaps():
    by_store, regions, latest = _sales_by_store()
    if not by_store or latest is None:
        return [], ""
    end = latest
    recent_start = end - timedelta(days=6)
    prior_end = recent_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=6)
    festive = _navratri_days()
    present = set()
    for points in by_store.values():
        present.update(points)
    missing = [
        day for offset in range(7)
        if (day := recent_start + timedelta(days=offset)) not in present
    ]
    gaps = []
    for store, points in by_store.items():
        region = regions.get(store) or ""
        recent_sum = 0.0
        prior_sum = 0.0
        pairs = 0
        for offset in range(7):
            recent_day = recent_start + timedelta(days=offset)
            prior_day = prior_start + timedelta(days=offset)
            if recent_day not in points or prior_day not in points:
                continue
            if _skip_day(store, recent_day) or _skip_day(store, prior_day):
                continue
            if _north(store, region) and (recent_day in festive or prior_day in festive):
                continue
            recent_sum += points[recent_day]
            prior_sum += points[prior_day]
            pairs += 1
        if pairs < 3:
            continue
        gaps.append({
            "store": store,
            "display": _display_store(store),
            "region": region,
            "recent": recent_sum,
            "prior": prior_sum,
            "gap": recent_sum - prior_sum,
            "days": pairs,
        })
    gaps.sort(key=lambda row: abs(row["gap"]), reverse=True)
    label = f"{_span(recent_start, end)} vs {_span(prior_start, prior_end)}"
    if missing:
        names = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
        if len({day.month for day in missing}) == 1:
            left = ", ".join(str(day.day) for day in missing) + f" {names[missing[0].month - 1]}"
        else:
            left = ", ".join(f"{day.day} {names[day.month - 1]}" for day in missing)
        label = f"{label}; {left} not in the file"
    return gaps, label


def growth_text():
    gaps, label = _weekly_gaps()
    if not gaps:
        return "Growth plan: not enough daily sales to compare two full weeks. No monthly estimate is invented."
    lines = [
        "Growth plan from Posist daily gross. Mall bill counts are not used.",
        f"Window: {label}.",
        "Assumption, stated as an illustration and not a forecast: the paired-day gap times 30/7 is the monthly rupee if that same gap repeated. A day missing from the files is left out of both weeks, not treated as zero. NCR Navratri days are excluded. Rosedale from 1 Nov (partly open; closed 10 Nov), Faridabad from 23 Oct, and closed stores are excluded.",
        "Delivery versus dine-in is not given a rupee here: channel files are gross, and the 24.78% rule needs net.",
        "store | paired-day gap | illustrated month",
    ]
    for row in gaps[:5]:
        month = row["gap"] * 30 / 7
        direction = "down" if row["gap"] < 0 else "up"
        lines.append(f"{row['display']} | {direction} {_lakh(row['gap'])} | {direction} {_lakh(month)}")
    lines.append("One action each: check the largest drop before adding a discount or a new site. No rent or volume elasticity was assumed.")
    from app.chat.reelo_deep import winback_line

    lines.append(winback_line())
    return "\n".join(lines)


def _asks_growth(question):
    folded = (question or "").casefold()
    return any(token in folded for token in ("increase sales", "grow sales", "growth plan", "how do we grow"))


def trend_rows():
    gaps, label = _weekly_gaps()
    rows = []
    for row in gaps:
        if abs(row["gap"]) < 1:
            continue
        rows.append({
            "store": row["store"],
            "display": row["display"],
            "impact": row["gap"],
            "label": label,
            "direction": "down" if row["gap"] < 0 else "up",
        })
    rows.sort(key=lambda row: abs(row["impact"]), reverse=True)
    return rows[:5]


def trends_text():
    rows = trend_rows()
    if not rows:
        return "Trends: the daily file does not have two comparable weeks, so no trend is stated."
    lines = [
        "Top sales trends by rupee impact of the latest 7 days versus the previous 7. Correlation only, not a cause.",
        "Closed stores, Faridabad from 23 Oct, and Rosedale from 1 Nov (partly open; closed 10 Nov) are excluded. Bills at Manisquare and Forum are not used.",
    ]
    from app.chat.reelo_deep import monthly_customers

    months = monthly_customers()
    if len(months) >= 2:
        last, prior = months[-1], months[-2]
        lines.append(
            f"All-store Reelo repeat share {last.get('repeat_customers_percentage')}% in {last.get('period')} "
            f"versus {prior.get('repeat_customers_percentage')}% in {prior.get('period')}. "
            "That is every Reelo store together, not one store's baseline. NPS is not in the file."
        )
    for row in rows:
        lines.append(
            f"{row['display']} {row['direction']} {_lakh(row['impact'])} across {row['label']}. "
            "Likely driver is not assigned without a second series on the same days."
        )
    return "\n".join(lines)


def trend_cards():
    cards = []
    for row in trend_rows()[:3]:
        direction = "down" if row["impact"] < 0 else "up"
        window = row["label"]
        cards.append({
            "kind": "sales",
            "title": row["display"],
            "line": f"Sales {direction} {_lakh(row['impact'])} vs the week before ({window})",
            "question": f"Why are {row['display']} sales {direction} versus the week before?",
        })
    return cards


def _asks_trends(question):
    folded = (question or "").casefold()
    return any(token in folded for token in ("what trends", "give me insights", "today's insights", "todays insights"))


def _forecast_rows():
    path = _ROOT / "data" / "store_health" / "sales_pred_vs_actual.csv"
    if not path.is_file():
        return []
    rows = []
    for raw in _read(path):
        day = _day(raw.get("date"))
        store = raw.get("store") or ""
        if _skip_day(store, day):
            continue
        rows.append({
            "store": store,
            "date": day,
            "weekday": raw.get("weekday") or "",
            "tier": raw.get("tier") or "",
            "pred": _num(raw.get("pred_mid")),
            "actual": _num(raw.get("actual_gross")),
        })
    return rows


def _asks_forecast(question):
    folded = (question or "").casefold()
    if "yesterday" in folded:
        return False
    return any(token in folded for token in (
        "predicted", "sales calendar", "forecast been", "forecast accuracy", "mape", "this weekend",
    ))


def forecast_answer(question, owner):
    rows = _forecast_rows()
    if not rows:
        return _pack("No sales calendar is loaded.", "", "sales", question, owner)
    folded = (question or "").casefold()
    store_rows = rows
    named = ""
    for store in sorted({row["store"] for row in rows}, key=len, reverse=True):
        token = store.split("(")[0].strip().casefold()
        if len(token) > 4 and token in folded:
            named = store
            break
    if named:
        store_rows = [row for row in rows if row["store"] == named]
    end = max(row["date"] for row in store_rows)
    if "weekend" in folded:
        shown = [row for row in store_rows if row["weekday"] in {"Saturday", "Sunday"} and row["date"] >= end - timedelta(days=3)]
        if not shown:
            shown = [row for row in store_rows if row["weekday"] in {"Saturday", "Sunday"}][-2:]
    elif "november" in folded or "calendar" in folded:
        shown = [row for row in store_rows if row["date"].month == 11 and row["date"].year == 2026]
    else:
        shown = [row for row in store_rows if row["date"] >= end - timedelta(days=6)]
    shown = sorted(shown, key=lambda row: (row["date"], row["store"]))[:16]
    paired = [row for row in store_rows if row["actual"] not in (None, 0) and row["pred"] not in (None, 0)]
    paired = [row for row in paired if row["date"] >= end - timedelta(days=28)]
    mape = None
    if len(paired) >= 4:
        mape = statistics.fmean(abs(row["actual"] - row["pred"]) / abs(row["actual"]) * 100 for row in paired)
    title = named or "Network sample"
    lines = [
        f"Sales calendar for {title}. Predicted is pred_mid. Actual is Posist gross. Basis is the store calendar file through {end.isoformat()}.",
        "Faridabad from 23 Oct, Rosedale from 1 Nov (partly open; closed 10 Nov), Chattarpur, and GK1 are excluded.",
    ]
    if mape is None:
        lines.append("Forecast accuracy: fewer than 4 days have both an actual and a prediction in the last 28 days, so MAPE is not stated.")
    else:
        lines.append(f"MAPE on {len(paired)} days in the last 28 that have both figures: {mape:.1f}%.")
    calendar = {"title": title, "days": []}
    for row in shown:
        gap = None
        if row["actual"] not in (None, 0) and row["pred"] not in (None, 0):
            gap = (row["actual"] - row["pred"]) / abs(row["pred"]) * 100
        lines.append(
            f"{row['date'].isoformat()} {row['weekday']} {row['tier']}: pred {_inr(row['pred'])}"
            + (f", actual {_inr(row['actual'])}, gap {gap:.1f}%" if gap is not None else ", actual not in yet")
        )
        calendar["days"].append({
            "date": row["date"].isoformat(),
            "weekday": row["weekday"],
            "tier": row["tier"],
            "pred": None if row["pred"] is None else round(row["pred"]),
            "actual": None if row["actual"] is None else round(row["actual"]),
            "gap": None if gap is None else round(gap, 1),
        })
    return _pack("\n".join(lines), end.isoformat(), "sales", question, owner, calendar=calendar)


def domain_text(question, role):
    """Extra packet text. Empty when the question is not one of these domains."""
    parts = []
    if _asks_finance(question):
        parts.append(finance_text(question, role))
    if _asks_procurement(question):
        parts.append(_procurement_text(question))
    if _asks_fixes(question):
        parts.append(posist_fixes_text())
    if _asks_growth(question):
        parts.append(growth_text())
    if _asks_trends(question):
        parts.append(trends_text())
    if _asks_forecast(question):
        answer = forecast_answer(question, role in {"owner", "finance"})
        parts.append(answer.get("text") or "")
    return "\n\n".join(part for part in parts if part)


def try_answer(question, data, owner):
    role = data.get("role") or ("owner" if owner else "ops")
    if _asks_fixes(question):
        return _pack(posist_fixes_text(), "13 Nov 2026", "procurement", question, owner)
    if _asks_growth(question):
        return _pack(growth_text(), "", "sales", question, owner)
    if _asks_trends(question):
        return _pack(trends_text(), "", "sales", question, owner)
    if _asks_forecast(question):
        return forecast_answer(question, owner)
    if _asks_finance(question):
        return _pack(finance_text(question, role), "", "finance", question, owner)
    if _asks_procurement(question):
        text, table_rows = ("", [])
        if any(token in (question or "").casefold() for token in ("recipe", "plate cost", "costing")):
            text, table_rows = _recipe_rows(question)
        else:
            text = _procurement_text(question)
        table = None
        if table_rows:
            from app.chat.visuals import table_block
            table = table_block(["City", "Item", "Plate cost", "Ingredients"], table_rows[:6], "Recipe cost")
        return _pack(text, "", "procurement", question, owner, table=table)
    return None


def persist_trends():
    """Replace the small trend table when a database session is open."""
    try:
        from flask import has_app_context

        from app.chat.trend_model import ChatTrend
        from app.extensions import db
    except Exception:
        return
    if not has_app_context():
        return
    try:
        ChatTrend.query.delete()
        for row in trend_rows():
            db.session.add(ChatTrend(
                store=row["store"][:120],
                impact=row["impact"],
                direction=row["direction"],
                detail=row["label"][:240],
            ))
        db.session.commit()
    except Exception:
        db.session.rollback()
