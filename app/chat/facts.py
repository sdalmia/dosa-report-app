"""Crisp answers from the snapshot. Numbers come from the files, not the model."""

from datetime import datetime

from app.chat.snapshot import named_store
from app.chat.suggestions import FINANCE, PROCUREMENT, REELO, SALES
from app.chat.visuals import chart_block, table_block, verify_block, allowed_numbers

_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _as_of(iso):
    text = str(iso or "").strip()
    try:
        day = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{day.day} {_MONTHS[day.month]} {day.year}"


def _lakh(value):
    number = float(value)
    return f"₹{number:.2f}L"


def _rupee(value):
    number = float(value)
    sign = "-" if number < 0 else ""
    whole = int(round(abs(number)))
    text = f"{whole:,}"
    return f"{sign}₹{text}"


def _pct(value):
    number = float(value)
    sign = "-" if number < 0 else ""
    return f"{sign}{abs(number):.1f}%"


def _region(summary, name):
    regions = summary.get("regional_mtd") if isinstance(summary.get("regional_mtd"), dict) else {}
    row = regions.get(name) if isinstance(regions.get(name), dict) else {}
    return row


def _followups(topic, question, owner):
    pools = {
        "sales": SALES,
        "finance": FINANCE if owner else (),
        "procurement": PROCUREMENT,
        "reelo": REELO,
    }
    chosen = []
    for item in pools.get(topic, SALES):
        if item.casefold() == question.casefold():
            continue
        if item in FINANCE and not owner:
            continue
        chosen.append(item)
        if len(chosen) == 3:
            break
    if len(chosen) < 2:
        for item in SALES:
            if item.casefold() == question.casefold() or item in chosen:
                continue
            chosen.append(item)
            if len(chosen) == 3:
                break
    if "action plan" not in (question or "").casefold():
        chosen = [item for item in chosen if item != "Make an action plan"]
        chosen = chosen[:2] + ["Make an action plan"]
    return chosen[:3]


def _pack(text, as_of, topic, question, owner, table=None, chart=None, source=None):
    allowed = allowed_numbers(source if source is not None else {"text": text})
    return {
        "text": text,
        "as_of": as_of,
        "table": verify_block(table, allowed),
        "chart": verify_block(chart, allowed),
        "followups": _followups(topic, question, owner),
        "topic": topic,
        "source": source if source is not None else {"text": text},
    }


def _pace(data, question, owner):
    summary = data.get("summary") or {}
    pace = summary.get("target_pace_pct")
    if pace is None:
        return None
    as_of = _as_of(summary.get("as_of_date"))
    actual = summary.get("mtd_actual_L")
    east = _region(summary, "East").get("pace_pct")
    north = _region(summary, "North").get("pace_pct")
    bits = [f"November pace is {_pct(pace).replace('-', '')}."]
    if actual is not None:
        bits[0] = f"November pace is {_pct(pace).replace('-', '')} on {_lakh(actual)} net."
    if east is not None and north is not None:
        bits.append(f"East {_pct(east).replace('-', '')}. North {_pct(north).replace('-', '')}.")
    if north is not None and float(north) < 90:
        bits.append("Next: look at the North stores behind pace.")
    elif float(pace) < 90:
        bits.append("Next: look at the stores behind this month's pace.")
    series = []
    if east is not None:
        series.append({"label": "East", "value": float(east)})
    if north is not None:
        series.append({"label": "North", "value": float(north)})
    series.append({"label": "Network", "value": float(pace)})
    chart = chart_block("November target pace", series, "%")
    return _pack(" ".join(bits), as_of, "sales", question, owner, chart=chart, source=summary)


def _yesterday(data, question, owner):
    summary = data.get("summary") or {}
    gaps = data.get("forecast") or []
    as_of = _as_of(summary.get("as_of_date") or (gaps[0]["date"] if gaps else ""))
    if not gaps:
        actual = summary.get("mtd_actual_L")
        mid = summary.get("mtd_pred_mid_L")
        if actual is None or mid is None:
            return _pack("No forecast comparison is loaded for the latest day.", as_of, "sales", question, owner)
        return _pack(
            f"Month-to-date net is {_lakh(actual)} versus a mid forecast of {_lakh(mid)}.",
            as_of,
            "sales",
            question,
            owner,
            source=summary,
        )
    day = _as_of(gaps[0]["date"])
    worst = gaps[0]
    best = gaps[-1]
    text = (
        f"On {day}, {worst['store']} is the softest versus forecast "
        f"({_pct(worst['pct'])}, {_rupee(worst['actual'])} vs mid {_rupee(worst['mid'])})."
    )
    chart = chart_block(
        f"Versus forecast, {day}",
        [{"label": row["store"].split("(")[0].strip()[:18], "value": row["pct"]} for row in (gaps[:3] + gaps[-2:])],
        "%",
    )
    return _pack(text, as_of or day, "sales", question, owner, chart=chart, source={"rows": gaps})


def _wow(data, question, owner):
    movers = list(data.get("movers") or [])
    if not movers:
        return _pack("No week-on-week sales comparison is loaded.", "", "sales", question, owner)
    drops = movers[:3]
    gains = list(reversed(movers[-3:]))
    lead = drops[0]
    text = (
        f"{lead['store']} dropped the most, {_pct(lead['pct'])} gross "
        f"({_rupee(lead['gross'])} vs {_rupee(lead['prior_gross'])})."
    )
    if lead.get("note"):
        text = f"{text} {lead['note']}."
    rows = []
    seen = set()
    for row in drops + gains:
        if row["store"] in seen:
            continue
        seen.add(row["store"])
        rows.append({
            "Store": row["store"].split("(")[0].strip(),
            "Gross": _rupee(row["gross"]),
            "Prior week": _rupee(row["prior_gross"]),
            "Change": _pct(row["pct"]),
        })
    table = table_block(["Store", "Gross", "Prior week", "Change"], rows, "Week on week gross")
    as_of = _as_of(lead["date"])
    return _pack(text, as_of, "sales", question, owner, table=table, source={"rows": movers[:10]})


def _profit(data, question, owner):
    if not owner:
        return _pack("Company profit is only on the owner login.", "", "finance", question, owner)
    cards = data.get("finance") or []
    if not cards:
        return _pack("Company profit isn't loaded yet.", "", "finance", question, owner)
    parts = []
    for card in cards[:2]:
        parts.append(f"{card['kicker']} {card['value']}")
    return _pack(
        "Latest EBITDA: " + ". ".join(parts) + ".",
        cards[0]["kicker"],
        "finance",
        question,
        owner,
        source={"cards": cards[:2]},
    )


def _phones(data, question, owner):
    rows = [row for row in (data.get("reelo") or []) if row.get("phone_capture") is not None]
    if not rows:
        return _pack("Reelo phone capture isn't loaded yet.", "", "reelo", question, owner)
    rows.sort(key=lambda row: row["phone_capture"])
    lead = rows[0]
    shown = [{
        "Store": row["store"],
        "Phone capture": f"{row['phone_capture']:.2f}%",
        "Orders": int(row["orders"]) if row.get("orders") is not None else "",
    } for row in rows[:8]]
    table = table_block(["Store", "Phone capture", "Orders"], shown, "Lowest phone capture")
    text = (
        f"{lead['store']} captured phones on {lead['phone_capture']:.2f}% of orders."
    )
    return _pack(text, data.get("reelo_period") or "", "reelo", question, owner, table=table, source={"rows": rows[:8]})


def _repeat(data, question, owner):
    rows = [row for row in (data.get("reelo") or []) if row.get("repeat_share") is not None]
    if not rows:
        return _pack("Reelo repeat share isn't loaded yet.", "", "reelo", question, owner)
    rows.sort(key=lambda row: row["repeat_share"])
    lead = rows[0]
    shown = [{
        "Store": row["store"],
        "Repeat share": f"{row['repeat_share']:.2f}%",
    } for row in rows[:8]]
    table = table_block(["Store", "Repeat share"], shown, "Lowest repeat share")
    text = f"{lead['store']} repeat share is {lead['repeat_share']:.2f}%."
    return _pack(text, data.get("reelo_period") or "", "reelo", question, owner, table=table, source={"rows": rows[:8]})


def _missing_reelo(data, question, owner):
    if not data.get("reelo_loaded"):
        return _pack("Reelo isn't loaded yet.", "", "reelo", question, owner)
    return _pack("Stores missing from Reelo are left out on purpose.", data.get("reelo_period") or "", "reelo", question, owner)


def _store_view(question, data, owner):
    store = named_store(question, data)
    if store is None:
        return None
    bits = [store["name"] + "."]
    source_rows = []
    sales = store.get("sales")
    if sales:
        bits.append(
            f"Gross {_pct(sales['pct'])} week on week "
            f"({_rupee(sales['gross'])} on {_as_of(sales['date'])} vs {_rupee(sales['prior_gross'])})."
        )
        if sales.get("note"):
            bits.append(sales["note"] + ".")
        source_rows.append(sales)
    else:
        bits.append("Sales has no week-on-week row for this store.")
    gap = store.get("forecast")
    if gap:
        bits.append(
            f"Versus forecast on {_as_of(gap['date'])}: {_rupee(gap['actual'])} vs mid {_rupee(gap['mid'])} ({_pct(gap['pct'])})."
        )
        source_rows.append(gap)
    else:
        bits.append("Forecast has no row for this store.")
    review = store.get("review")
    if review:
        reviews = int(review["reviews"]) if review.get("reviews") is not None else None
        extra = f" from {reviews} reviews" if reviews is not None else ""
        bits.append(f"Public rating {review['rating']:.2f}{extra}.")
        source_rows.append(review)
    else:
        bits.append("Reviews have no row for this store.")
    reelo = store.get("reelo")
    if reelo and reelo.get("phone_capture") is not None:
        repeat = f", repeat share {reelo['repeat_share']:.2f}%" if reelo.get("repeat_share") is not None else ""
        bits.append(f"Reelo phone capture {reelo['phone_capture']:.2f}%{repeat}.")
        source_rows.append(reelo)
    else:
        bits.append("Reelo has no row for this store.")
    audit = store.get("audit")
    if audit:
        bits.append(f"Mystery audit {audit['score']:.1f}% ({audit['period']}).")
        source_rows.append(audit)
    else:
        bits.append("Mystery audit has no row for this store.")
    food = store.get("food")
    if food and food.get("pct") is not None:
        bits.append(f"Food cost {food.get('text') or _pct(food['pct'])} ({food.get('period') or 'loaded period'}).")
        source_rows.append({"pct": food["pct"]})
    else:
        bits.append("Food cost has no row for this store.")
    if sales and sales.get("pct") is not None and float(sales["pct"]) <= -10:
        bits.append("Next: check this store before the next rush.")
    elif review and review.get("rating") is not None and float(review["rating"]) < 4:
        bits.append("Next: read the latest public reviews.")
    if data.get("role") in {"owner", "hr"} and store.get("hr"):
        lead = store["hr"].get("lead") or "no lead on file"
        bits.append(f"Staff lead {lead}.")
    table_rows = []
    if sales:
        table_rows.append(["Sales vs last week", _pct(sales["pct"]), _as_of(sales["date"])])
    if gap:
        table_rows.append(["Versus forecast", _pct(gap["pct"]), _as_of(gap["date"])])
    if reelo and reelo.get("phone_capture") is not None:
        table_rows.append(["Phone capture", f"{reelo['phone_capture']:.2f}%", data.get("reelo_period") or ""])
    if audit:
        table_rows.append(["Mystery audit", f"{audit['score']:.1f}%", audit["period"]])
    table = table_block(["Source", "Figure", "Period"], table_rows, store["name"]) if table_rows else None
    as_of = _as_of((sales or gap or {}).get("date")) or (data.get("reelo_period") or "")
    return _pack(" ".join(bits), as_of, "sales", question, owner, table=table, source={"rows": source_rows})


def actions_from_data(data, owner):
    """Up to five actions. Every why cites a figure already in the snapshot."""
    actions = []
    summary = data.get("summary") or {}
    north = None
    regions = summary.get("regional_mtd") if isinstance(summary.get("regional_mtd"), dict) else {}
    if isinstance(regions.get("North"), dict):
        north = regions["North"].get("pace_pct")
    if north is not None and float(north) < 90:
        actions.append({
            "what": "Look at North stores behind November pace.",
            "why": f"North pace is {_pct(north).replace('-', '')}.",
            "owner": "Sanjoy / Anup / Vikas",
            "urgency": "high" if float(north) < 85 else "medium",
        })
    movers = data.get("movers") or []
    if movers:
        lead = movers[0]
        actions.append({
            "what": f"Check the drop at {lead['store'].split('(')[0].strip()}.",
            "why": f"Gross {_pct(lead['pct'])} on {_as_of(lead['date'])}.",
            "owner": "Sanjoy / Anup / Vikas",
            "urgency": "high" if lead["pct"] <= -20 else "medium",
        })
    gaps = data.get("forecast") or []
    if gaps and gaps[0]["pct"] <= -15:
        row = gaps[0]
        actions.append({
            "what": f"Compare {row['store'].split('(')[0].strip()} with its forecast.",
            "why": f"{_pct(row['pct'])} versus mid on {_as_of(row['date'])}.",
            "owner": "Sanjoy / Anup / Vikas",
            "urgency": "high",
        })
    reelo = [row for row in (data.get("reelo") or []) if row.get("phone_capture") is not None]
    if reelo:
        reelo.sort(key=lambda row: row["phone_capture"])
        low = reelo[0]
        if low["phone_capture"] < 70:
            actions.append({
                "what": f"Raise phone capture at {low['store']}.",
                "why": f"Phone capture is {low['phone_capture']:.2f}%.",
                "owner": "Sanjoy / Anup / Vikas",
                "urgency": "medium",
            })
    if owner and (data.get("finance") or []):
        card = data["finance"][0]
        actions.append({
            "what": f"Review {card['kicker']} profit.",
            "why": f"EBITDA is {card['value']}.",
            "owner": "Shilajit",
            "urgency": "medium",
        })
    return actions[:5]


def _buying(data, question, owner):
    """Prices are judged against that city's own baseline, never the other city."""
    pack = data.get("procurement") or {}
    if not pack:
        return _pack("Buying prices aren't loaded yet.", "", "procurement", question, owner)
    as_of = _as_of(pack.get("as_of"))
    folded = question.casefold()
    prices = (pack.get("monthly_prices") or {}) if isinstance(pack.get("monthly_prices"), dict) else {}
    items = prices.get("items") if isinstance(prices.get("items"), list) else []
    if any(word in folded for word in ("milk", "paneer", "cheese")):
        wanted = [word for word in ("milk", "paneer", "cheese") if word in folded] or ["milk", "paneer", "cheese"]
        chosen = []
        for row in items:
            if not isinstance(row, dict):
                continue
            name = str(row.get("item") or "")
            if not any(word in name.casefold() for word in wanted):
                continue
            this = row.get("this_month") if isinstance(row.get("this_month"), dict) else None
            last = row.get("last_month") if isinstance(row.get("last_month"), dict) else None
            if not this or this.get("avg_unit_price") is None or not last or last.get("avg_unit_price") is None:
                continue
            chosen.append(row)
        if not chosen:
            return _pack("Those prices aren't in the loaded buying summary.", as_of, "procurement", question, owner)
        lines = []
        table_rows = []
        for row in chosen[:8]:
            city = row.get("city") or ""
            this = row["this_month"]["avg_unit_price"]
            last = row["last_month"]["avg_unit_price"]
            change = row.get("pct_change")
            change_text = _pct(change) if change is not None else ""
            lines.append(f"{city} {row.get('item')} {_rupee(this)} vs its last month {_rupee(last)} ({change_text}).")
            table_rows.append([city, row.get("item"), _rupee(this), _rupee(last), change_text])
        table = table_block(
            ["City", "Item", "This month", "Last month", "Vs own baseline"],
            table_rows,
            "Each city versus its own last month",
        )
        return _pack(" ".join(lines[:3]), as_of, "procurement", question, owner, table=table, source={"rows": chosen[:8]})
    above = [row for row in (pack.get("above_average") or []) if isinstance(row, dict) and row.get("pct_above") is not None]
    if above and any(word in folded for word in ("above average", "above its", "price spike", "bought above")):
        above.sort(key=lambda row: float(row.get("pct_above") or 0), reverse=True)
        lead = above[0]
        text = (
            f"{lead.get('city')} {lead.get('item')} was {_pct(lead['pct_above']).replace('-', '')} "
            f"above its own baseline (₹{float(lead['price']):.2f} vs ₹{float(lead['baseline_avg']):.2f}"
            f" on {_as_of(lead.get('date'))}). "
            "Next: check that buy before the next order."
        )
        table_rows = []
        for row in above[:8]:
            table_rows.append([
                row.get("city") or "",
                row.get("item") or "",
                f"₹{float(row['price']):.2f}",
                f"₹{float(row['baseline_avg']):.2f}",
                _pct(row["pct_above"]).replace("-", ""),
            ])
        table = table_block(
            ["City", "Item", "Price", "Own baseline", "Above"],
            table_rows,
            "Above each city's own average",
        )
        return _pack(text, as_of, "procurement", question, owner, table=table, source={"rows": above[:8]})
    grn = pack.get("yesterday_grn") if isinstance(pack.get("yesterday_grn"), dict) else {}
    if grn and any(word in folded for word in ("received", "goods", "grn", "warehouse")):
        parts = []
        for city, row in grn.items():
            if not isinstance(row, dict):
                continue
            if row.get("note"):
                parts.append(f"{city}: {row['note']}")
            elif row.get("value") is not None:
                parts.append(f"{city} received {_rupee(row['value'])} on {_as_of(row.get('date'))}.")
        if parts:
            return _pack(" ".join(parts), as_of, "procurement", question, owner, source=grn)
    if "flag" in folded:
        flags = [row for row in (pack.get("flags") or []) if isinstance(row, dict) and row.get("title")]
        if flags:
            title = str(flags[0]["title"]).split(" — ")[0]
            return _pack(title, _as_of(flags[0].get("as_of") or pack.get("as_of")), "procurement", question, owner, source={"flags": flags[:3]})
    matched = _monthly_matches(items, folded)
    if matched:
        lines = []
        table_rows = []
        for row in matched[:8]:
            city = row.get("city") or ""
            this = (row.get("this_month") or {}).get("avg_unit_price")
            last = (row.get("last_month") or {}).get("avg_unit_price") if isinstance(row.get("last_month"), dict) else None
            if this is None:
                continue
            if last is None:
                lines.append(f"{city} {row.get('item')} {_rupee(this)} this month. No last-month baseline is loaded.")
                table_rows.append([city, row.get("item"), _rupee(this), "—", ""])
                continue
            change = row.get("pct_change")
            change_text = _pct(change) if change is not None else ""
            lines.append(f"{city} {row.get('item')} {_rupee(this)} vs its last month {_rupee(last)} ({change_text}).")
            table_rows.append([city, row.get("item"), _rupee(this), _rupee(last), change_text])
        if lines:
            table = table_block(
                ["City", "Item", "This month", "Last month", "Vs own baseline"],
                table_rows,
                "Each city versus its own last month",
            )
            return _pack(" ".join(lines[:3]), as_of, "procurement", question, owner, table=table, source={"rows": matched[:8]})
    tracker = _tracker_line(folded)
    if tracker is not None:
        text, source = tracker
        return _pack(text, as_of, "procurement", question, owner, source=source)
    return _pack("That price isn't in the loaded buying summary.", as_of, "procurement", question, owner)


_PRICE_WORDS = frozenset({
    "what", "which", "when", "where", "this", "that", "last", "month", "week",
    "price", "prices", "paying", "paid", "bought", "above", "average", "versus",
    "against", "city", "baseline", "goods", "received", "warehouse", "flag",
    "flags", "current", "item", "items", "from", "with", "have", "were", "been",
    "into", "than", "each", "only", "about", "their", "there", "much", "many",
})


def _price_tokens(folded):
    tokens = []
    for raw in folded.replace("?", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if len(word) < 4 or word in _PRICE_WORDS:
            continue
        tokens.append(word)
    return tokens


def _monthly_matches(items, folded):
    """Rows whose item name contains the words in the question."""
    tokens = _price_tokens(folded)
    if not tokens or not items:
        return []
    both = [
        row for row in items
        if isinstance(row, dict) and all(token in str(row.get("item") or "").casefold() for token in tokens)
    ]
    if both:
        return both
    tokens = sorted(tokens, key=len, reverse=True)
    for token in tokens:
        hits = [row for row in items if isinstance(row, dict) and token in str(row.get("item") or "").casefold()]
        if hits:
            return hits
    return []


def _tracker_line(folded):
    """Ingredient-tracker rows, only when the buying summary has no matching item."""
    tokens = _price_tokens(folded)
    if not tokens:
        return None
    try:
        from flask import has_app_context
        if not has_app_context():
            return None
        from app.models import IngredientPrice
    except Exception:
        return None
    token = sorted(tokens, key=len, reverse=True)[0]
    rows = (
        IngredientPrice.query
        .filter(IngredientPrice.ingredient_name.ilike("%" + token + "%"))
        .filter(IngredientPrice.unit_price.isnot(None))
        .order_by(IngredientPrice.date.desc())
        .limit(5)
        .all()
    )
    if not rows:
        return None
    latest = rows[0]
    day = latest.date.isoformat() if latest.date else ""
    text = (
        f"{latest.ingredient_name} was {_rupee(latest.unit_price)} "
        f"on {_as_of(day)} in the ingredient tracker."
    )
    return text, {
        "tracker": [{
            "name": latest.ingredient_name,
            "unit_price": latest.unit_price,
            "date": day,
        }]
    }


def _audit_low(data, question, owner):
    rows = [row for row in (data.get("october_audit") or []) if isinstance(row, dict) and row.get("score") is not None]
    if not rows:
        return _pack("October mystery audit isn't loaded yet.", "", "sales", question, owner)
    rows = sorted(rows, key=lambda row: float(row["score"]))
    lead = rows[0]
    period = lead.get("period") or "October"
    text = (
        f"{lead['store']} scored lowest in the {period} mystery audit, {_pct(lead['score'])}. "
        "Next: walk that store before the next audit visit."
    )
    shown = rows[:5]
    table = table_block(
        ["Store", "Score"],
        [[row["store"], _pct(row["score"])] for row in shown],
        f"Lowest scores, {period}",
    )
    return _pack(text, period, "sales", question, owner, table=table, source={"rows": shown})


def _attention(data, question, owner):
    audit = _audit_low(data, question, owner)
    if audit and "isn't loaded" not in audit["text"]:
        return audit
    return _pace(data, question, owner) or _pack("Nothing that needs attention is loaded.", "", "sales", question, owner)


def _readable_ticket_store(name):
    text = " ".join(str(name or "").replace("_", " ").replace("/", " ").replace("-", " ").split())
    marker = "dosa coffee"
    folded = text.casefold()
    if marker in folded:
        text = text[folded.find(marker) + len(marker):]
    return " ".join(text.replace("-", " ").split()) or str(name or "")


def _ticket_match(question, tickets):
    folded = " ".join((question or "").casefold().split())
    best = None
    for row in tickets.get("stores") or []:
        raw = str(row.get("store") or "")
        token = " ".join(raw.casefold().replace("_", " ").replace("/", " ").replace("-", " ").split())
        token = " ".join(token.replace("dosa coffee", " ").split())
        parts = token.split()
        while parts and parts[0].isdigit():
            parts = parts[1:]
        token = " ".join(parts)
        if len(token) < 4 or token not in folded:
            continue
        if best is None or len(token) > best[0]:
            best = (len(token), row)
    return best[1] if best else None


def _channel_rows(pack):
    channels = pack.get("channels") if isinstance(pack.get("channels"), dict) else {}
    order = ["zomato", "swiggy", "google", "other"]
    names = list(order) + [name for name in channels if name not in order]
    rows = []
    for name in names:
        bucket = channels.get(name)
        if not bucket or not bucket.get("tickets"):
            continue
        share = round(bucket["stale"] / bucket["tickets"] * 100, 1) if bucket["tickets"] else None
        rows.append({
            "channel": name.title(),
            "tickets": bucket["tickets"],
            "stale": bucket["stale"],
            "share": share,
        })
    return rows


def _tickets(data, question, owner):
    tickets = data.get("tickets") if isinstance(data.get("tickets"), dict) else {}
    if not tickets or not tickets.get("all"):
        return _pack("Famepilot tickets aren't loaded yet.", "", "sales", question, owner)
    chosen = _ticket_match(question, tickets) or tickets["all"]
    label = _readable_ticket_store(chosen.get("store")) if chosen.get("store") else "All stores"
    share = chosen.get("stale_share")
    channels = _channel_rows(chosen)
    zomato = next((row["tickets"] for row in channels if row["channel"] == "Zomato"), 0)
    swiggy = next((row["tickets"] for row in channels if row["channel"] == "Swiggy"), 0)
    text = (
        f"{label}: {chosen.get('count')} tickets, stale share {_pct(share) if share is not None else 'not loaded'}. "
        f"Zomato {zomato}, Swiggy {swiggy}."
    )
    if tickets.get("older_than_7"):
        text += f" The newest ticket is {_as_of(tickets.get('as_of'))}, more than 7 days ago."
    text += " Next: clear the stale tickets before the next rush."
    table = table_block(
        ["Channel", "Tickets", "Stale", "Stale share"],
        [[
            row["channel"],
            str(row["tickets"]),
            str(row["stale"]),
            _pct(row["share"]) if row["share"] is not None else "",
        ] for row in channels],
        "Zomato and Swiggy",
    )
    return _pack(
        text,
        _as_of(tickets.get("as_of")),
        "sales",
        question,
        owner,
        table=table,
        source={"rows": channels, "count": chosen.get("count"), "stale_share": share},
    )


def answer_from_data(question, data, owner):
    """One short answer. A table or chart is added only when it shows the comparison."""
    text = (question or "").strip()
    folded = text.casefold()
    if not text:
        return _pack("Ask a question.", "", "sales", text, owner)
    if "action plan" in folded:
        actions = actions_from_data(data, owner)
        if not actions:
            return _pack("No action is backed by a loaded figure.", "", "sales", text, owner)
        first = actions[0]
        packed = _pack(f"{first['what']} {first['why']}", "", "sales", text, owner, source={"actions": actions})
        packed["actions"] = actions
        packed["followups"] = [item["what"] for item in actions[1:4]]
        return packed
    if any(word in folded for word in ("ticket", "famepilot", "zomato", "swiggy")):
        return _tickets(data, text, owner)
    store_answer = _store_view(text, data, owner)
    if any(word in folded for word in ("mystery", "audit")) and (
        "lowest" in folded or "october" in folded or store_answer is None
    ):
        return _audit_low(data, text, owner)
    if "attention" in folded and store_answer is None:
        answered = _attention(data, text, owner)
        if answered is not None:
            return answered
    if store_answer is not None:
        return store_answer
    see_finance = (data.get("role") in {"owner", "finance"}) or (data.get("role") is None and owner)
    if any(word in folded for word in ("profit", "ebitda", "tally", "bank payment", "salary")):
        if "phone" not in folded:
            return _profit(data, text, see_finance)
    if "missing" in folded and "reelo" in folded:
        return _missing_reelo(data, text, owner)
    if "repeat" in folded:
        return _repeat(data, text, owner)
    if "phone" in folded or "captur" in folded:
        return _phones(data, text, owner)
    if any(word in folded for word in ("week on week", "week-on-week", "grew", "dropped the most", "drop")):
        return _wow(data, text, owner)
    if any(word in folded for word in ("yesterday", "forecast", "versus the forecast", "vs forecast")):
        return _yesterday(data, text, owner)
    if any(word in folded for word in ("target", "pace", "tracking", "behind")):
        paced = _pace(data, text, owner)
        if paced is not None:
            return paced
    if any(word in folded for word in (
        "milk", "paneer", "cheese", "price", "bought", "above average",
        "goods received", "warehouse", "paying", "pay for", "paid", "flag",
    )):
        return _buying(data, text, owner)
    if data.get("sales_loaded"):
        paced = _pace(data, text, owner)
        if paced is not None:
            return paced
    return _pack("That data isn't available.", "", "sales", text, owner)
