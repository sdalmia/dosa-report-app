"""Partner note for an analytic question, using only loaded figures.

The shape is the one Siddhant asked for: one bold insight, a few numbered
facts, the so-what, ranked moves with a rupee (or the data that would size it),
then the pattern that is easy to miss. A simple lookup stays short.
"""

from datetime import datetime

from app.chat.facts import _as_of, _lakh, _pct, _readable_ticket_store, _region


def _rupee_lakh(value):
    """A rupee total, shown in lakhs. Values already stored in lakhs use _lakh."""
    number = float(value)
    sign = "-" if number < 0 else ""
    return f"{sign}₹{abs(number) / 100000:.2f}L"


def is_analytic(question):
    """A partner note is added for a sales or attention question, not for a lookup."""
    folded = " ".join((question or "").casefold().split())
    if any(token in folded for token in (
        "what did we pay", "pay for", "paid for", "licence", "license",
        "remember", "inbox", "important email", "predicted for", "what can we fix",
        "grand economics", "recipe", "phone capture", "repeat share", "famepilot",
        "ticket", "mystery audit", "scored lowest",
    )):
        return False
    return any(token in folded for token in (
        "why", "behind", "attention", "last week", "past week", "increase sales",
        "how did", "how are we", "how do we", "grow sales", "tracking",
        "week on week", "week-on-week",
    ))


def sections(question, data, owner):
    """The partner note. Empty when the question is a lookup."""
    if not is_analytic(question):
        return ""
    ctx = _read(data)
    parts = [
        _lead(question, ctx),
        "",
        *_supports(ctx),
        "",
        _so_what(question, ctx),
        "",
        "**Moves**",
        "",
        _moves(question, data, owner, ctx),
        "",
        _nonobvious(ctx),
        "",
        _hypothesis(ctx),
        "",
        _missing(ctx),
        "",
        _data_line(ctx),
    ]
    return "\n".join(part for part in parts if part)


def attach(packed, question, data, owner):
    """Shape the file answer. A role refusal stays as it is."""
    if not packed:
        return packed
    text = packed.get("text") or ""
    folded = text.casefold()
    if "not included for this role" in folded or "only on the owner login" in folded:
        return _footer(packed, question, data)
    if not is_analytic(question):
        note = _worth_noting(question, data, text)
        if note and "Worth noting:" not in text:
            packed["text"] = text.rstrip() + "\n\n" + note
        return _stamp_sales(packed, question, data)
    extra = sections(question, data, owner)
    if not extra or "**So what**" in text:
        return _footer(packed, question, data)
    # A working that already runs to several lines (the growth illustration) stays
    # underneath the note. A one-line lookup-style opener is replaced by the note.
    if "\n" in text.strip():
        packed["text"] = extra.rstrip() + "\n\n" + text.strip()
    else:
        packed["text"] = extra
    return _stamp_sales(packed, question, data)


def _stamp_sales(packed, question, data):
    folded = " ".join((question or "").casefold().split())
    if not any(token in folded for token in ("sale", "week", "yesterday", "forecast", "pace", "tracking", "bill", "price", "pay", "bought", "target", "behind", "attention")):
        return _footer(packed, question, data)
    from app.chat.guard import sales_stamp

    from app.chat.correctness import network_net_sentence, tracker_through_line

    line = sales_stamp(data)
    text = packed.get("text") or ""
    extra = []
    if line and "Sales through" not in text:
        extra.append(line)
    net = network_net_sentence(data)
    if net and "network net" not in text.casefold():
        extra.append(net)
    if any(token in folded for token in ("price", "pay", "paneer", "milk", "cheese", "daal", "bought")):
        tracker = tracker_through_line()
        if tracker and "Stock entries run through" not in text and tracker not in text:
            extra.append(tracker)
    if extra:
        packed["text"] = text.rstrip() + "\n\n" + "\n\n".join(extra)
    return _footer(packed, question, data)


def _footer(packed, question, data):
    from app.chat.correctness import data_footer

    line = data_footer(data, question)
    text = packed.get("text") or ""
    if line and "Data through" not in text:
        packed["text"] = text.rstrip() + "\n\n" + line
    return packed


def _read(data):
    """One pass over the series the note is allowed to use."""
    summary = data.get("summary") or {}
    windows = data.get("sales_windows") or {}
    gaps, label = _week_gaps()
    downs = sorted((row for row in gaps if row.get("gap", 0) < 0), key=lambda row: row["gap"])
    ups = sorted((row for row in gaps if row.get("gap", 0) > 0), key=lambda row: row["gap"], reverse=True)
    trading = _trading_week(windows.get("week_rows") or [])
    week_gross = sum(float(row.get("gross") or 0) for row in trading) if trading else None
    return {
        "summary": summary,
        "windows": windows,
        "east": _region(summary, "East"),
        "north": _region(summary, "North"),
        "gaps": gaps,
        "label": label,
        "east_gap": _sum_gap(gaps, "East"),
        "north_gap": _sum_gap(gaps, "North"),
        "downs": downs[:3],
        "up": ups[0] if ups else None,
        "week_gross": week_gross,
        "week_stores": len(trading),
        "drop": _largest_rupee_drop(data),
        "tickets": _ticket_lead(data),
        "pacific_tickets": _match_ticket(data, "pacific"),
        "reelo_phone": _lowest_reelo(data, "phone_capture"),
        "reelo_repeat": _lowest_reelo(data, "repeat_share"),
        "reelo_period": data.get("reelo_period") or "",
        "buy": _sharpest_buy(data),
        "food": _food_outlier(data),
        "channels": _channel_week(data),
        "audit": _lowest_audit(data),
        "forecast_rows": list(data.get("forecast") or []),
        "finance": list(data.get("finance") or []),
        "role_owner": bool(data.get("role") in {"owner", "finance"}),
    }


def _lead(question, ctx):
    folded = " ".join((question or "").casefold().split())
    north = ctx["north"]
    north_gap = _plan_gap(north)
    flagship = _flagship_sentence(ctx)
    pacific = _pacific_sentence(ctx)
    if any(token in folded for token in ("attention", "which store")) and pacific:
        return f"**{pacific}**"
    if any(token in folded for token in ("north", "behind")) and north_gap is not None:
        return (
            f"**Your North stores are {_lakh(north_gap)} behind their own pro-rata: "
            f"{_pace(north)} on {_lakh(north.get('net_L'))} net versus {_lakh(north.get('pro_rata_L'))}.**"
        )
    if any(token in folded for token in ("increase", "grow")) and flagship:
        return f"**The rupee to recover is in your East flagships: {flagship}**"
    pace = (ctx["summary"] or {}).get("target_pace_pct")
    actual = (ctx["summary"] or {}).get("mtd_actual_L")
    mid = (ctx["summary"] or {}).get("mtd_pred_mid_L")
    if any(token in folded for token in ("tracking", "target", "pace")) and pace is not None and actual is not None:
        ahead = ""
        if mid is not None:
            delta = float(actual) - float(mid)
            direction = "above" if delta >= 0 else "below"
            ahead = f", {_lakh(abs(delta))} {direction} the mid forecast of {_lakh(mid)}"
        return (
            f"**You are at {_pct(pace).replace('-', '')} of this month's own plan, on {_lakh(actual)} net{ahead}.**"
        )
    if ctx["east_gap"] is not None and ctx["north_gap"] is not None and north.get("pace_pct") is not None:
        return (
            f"**Your East stores gave up {_rupee_lakh(abs(ctx['east_gap']))} last week versus their own prior week, "
            f"while North, at {_pace(north)} of its own month plan, gave up {_rupee_lakh(abs(ctx['north_gap']))}.**"
        )
    if flagship:
        return f"**{flagship}**"
    if pace is not None:
        return f"**You are at {_pct(pace).replace('-', '')} of this month's own plan.**"
    return "**No pace figure and no week comparison is loaded, so there is no lead to give you.**"


def _supports(ctx):
    lines = []
    month = _month_point(ctx)
    if month:
        lines.append(f"- {month}")
    week = _week_point(ctx)
    if week:
        lines.append(f"- {week}")
    service = _service_point(ctx)
    if service:
        lines.append(f"- {service}")
    cost = _cost_point(ctx)
    if cost:
        lines.append(f"- {cost}")
    if not lines:
        lines.append("- No pace, week, complaint, Reelo, procurement, food-cost, or forecast figure is loaded.")
    return lines[:4]


def _mtd_precise(ctx):
    """Month-to-date net summed from unrounded daily city figures, rounded once."""
    from app.chat.correctness import period_nets

    summary = ctx.get("summary") or {}
    windows = ctx.get("windows") or {}
    end = str(windows.get("latest") or summary.get("actuals_through") or "")[:10]
    month = str(summary.get("current_month") or "")[:7]
    if len(month) != 7 or not end:
        return None
    found = period_nets(f"{month}-01", end)
    if found["rounded_total"] is None:
        return None
    return found


def _month_point(ctx):
    summary = ctx["summary"] or {}
    pace = summary.get("target_pace_pct")
    if pace is None:
        return ""
    precise = _mtd_precise(ctx)
    actual = precise["rounded_total"] if precise else summary.get("mtd_actual_L")
    bits = [f"November pace is {_pct(pace).replace('-', '')}"]
    if actual is not None:
        bits[0] += f" on {_lakh(actual)} net"
    bits[0] += "."
    city_nets = {}
    if precise:
        city_nets = {"East": precise["rounded_east"], "North": precise["rounded_north"]}
    for name, row in (("East", ctx["east"]), ("North", ctx["north"])):
        if row.get("pace_pct") is None:
            continue
        piece = f"{name} is {_pace(row)}"
        net = city_nets.get(name)
        if net is None:
            net = row.get("net_L")
        if net is not None and row.get("pro_rata_L") is not None:
            piece += f" on {_lakh(net)} net versus its own pro-rata {_lakh(row.get('pro_rata_L'))}"
        bits.append(piece + ".")
    mid = summary.get("mtd_pred_mid_L")
    if mid is not None and summary.get("mtd_actual_L") is not None:
        bits.append(f"The mid forecast is {_lakh(mid)}.")
    return " ".join(bits)


def _week_point(ctx):
    bits = []
    if ctx["week_gross"] is not None:
        windows = ctx["windows"] or {}
        span = ""
        if windows.get("week_start") and windows.get("latest"):
            span = f" ({windows.get('week_start')} to {windows.get('latest')})"
        bits.append(
            f"The latest 7 sales days{span} gross {_rupee_lakh(ctx['week_gross'])} across {ctx['week_stores']} open stores."
        )
    if ctx["label"] and ctx["east_gap"] is not None and ctx["north_gap"] is not None:
        bits.append(
            f"Versus each store's own prior week ({ctx['label']}), East is {_signed_lakh(ctx['east_gap'])} and North is {_signed_lakh(ctx['north_gap'])}."
        )
    named = []
    for row in ctx["downs"]:
        named.append(f"{row['display']} {_signed_lakh(row['gap'])}")
    if ctx["up"]:
        named.append(f"{ctx['up']['display']} {_signed_lakh(ctx['up']['gap'])}")
    if named:
        bits.append("Largest store moves: " + "; ".join(named) + ".")
    drop = ctx["drop"]
    if drop:
        bits.append(
            f"On the latest sales day versus its own same weekday, {_store_name(drop.get('store'))} is {_pct(drop.get('pct'))} "
            f"({_rupee_lakh(drop.get('gross'))} versus {_rupee_lakh(drop.get('prior_gross'))})."
        )
    if not bits:
        return ""
    bits.append(
        "A missing day is left out of both weeks, not treated as zero. NCR Navratri and Chhath days are left out. "
        "Rosedale from 1 Nov (partly open; closed 10 Nov) is left out of the comparison and is not flagged. "
        "Closed stores are out of the ranking. Manisquare and Forum bills and average bill are not used."
    )
    try:
        from app.chat.lenses import bill_driver
        driver = bill_driver()
    except Exception:
        driver = ""
    if driver:
        bits.append(driver)
    return " ".join(bits)


def _service_point(ctx):
    bits = []
    lead = ctx["tickets"]
    if lead:
        share = _pct(lead.get("stale_share")) if lead.get("stale_share") is not None else "share not loaded"
        bits.append(
            f"Famepilot: {_readable_ticket_store(lead.get('store'))} has {lead.get('stale')} stale tickets "
            f"out of {lead.get('count')} ({share})."
        )
    phone = ctx["reelo_phone"]
    if phone:
        period = f" ({ctx['reelo_period']})" if ctx["reelo_period"] else ""
        bits.append(
            f"Reelo{period}: {phone['store']} phone capture is {phone['phone_capture']:.2f}% of its own orders, the lowest loaded."
        )
    repeat = ctx["reelo_repeat"]
    if repeat and repeat.get("repeat_share") is not None:
        bits.append(f"{repeat['store']} repeat share is {repeat['repeat_share']:.2f}%, the lowest loaded.")
    if phone or repeat:
        bits.append("Stores missing from Reelo are left out on purpose.")
    audit = ctx["audit"]
    if audit:
        bits.append(
            f"{audit.get('store')} scored {_pct(audit.get('score'))} in the {audit.get('period') or 'October'} mystery audit, the lowest loaded score."
        )
    if not bits:
        return "Famepilot, Reelo, and the mystery audit are not loaded, so none of them is used."
    return " ".join(bits)


def _cost_point(ctx):
    bits = []
    food = ctx["food"]
    if food:
        packaging = f", packaging {food['packaging']} separate" if food.get("packaging") else ", packaging separate"
        period = f" The file is {food['period']}, so it does not explain this week." if food.get("period") else ""
        bits.append(
            f"Food cost is raw plus semi-processed consumption over Posist gross{packaging}. "
            f"The widest gap versus a store's own city median is {food['name']} at {_pct(food['pct'])} versus {_pct(food['median'])}.{period}"
        )
    else:
        bits.append("Food cost percent is not loaded, so none is stated.")
    buy = ctx["buy"]
    if buy:
        bits.append(
            f"{buy.get('city')} {buy.get('item')} was {_pct(buy.get('pct_above')).replace('-', '')} above its own baseline "
            f"on {_as_of(buy.get('date'))} (₹{float(buy.get('price')):.2f} versus ₹{float(buy.get('baseline_avg')):.2f}). "
            "Quantity is not loaded, so the rupee waste is not sized. The other city's price is not the comparison."
        )
    else:
        bits.append("Procurement prices are not loaded, so none are used.")
    return " ".join(bits)


def _so_what(question, ctx):
    folded = " ".join((question or "").casefold().split())
    north_gap = _plan_gap(ctx["north"])
    if any(token in folded for token in ("attention", "which store")) and _pacific_sentence(ctx):
        return (
            "**So what**\n\nA single audit score understates this store. "
            "The week sales, the phone capture, and the tickets point at the same door."
        )
    if any(token in folded for token in ("increase", "grow")):
        return (
            "**So what**\n\nRecover the two flagship weeks before you add a discount or a site. "
            "The monthly figure in the working below is an illustration, stated as an assumption and not a forecast."
        )
    if north_gap is not None and ctx["east_gap"] is not None:
        forecast = ""
        actual = (ctx["summary"] or {}).get("mtd_actual_L")
        mid = (ctx["summary"] or {}).get("mtd_pred_mid_L")
        if actual is not None and mid is not None:
            delta = float(actual) - float(mid)
            direction = "above" if delta >= 0 else "below"
            forecast = (
                f" You are {_lakh(abs(delta))} {direction} the mid forecast "
                f"({_lakh(actual)} net versus {_lakh(mid)})."
            )
        return (
            "**So what**\n\nYou are managing two different gaps. "
            f"North's own plan gap is {_lakh(north_gap)} "
            f"({_lakh(ctx['north'].get('pro_rata_L'))} pro-rata minus {_lakh(ctx['north'].get('net_L'))} net). "
            f"This week's rupee loss is {_rupee_lakh(abs(ctx['east_gap']))} in the East."
            + forecast
        )
    return "**So what**\n\nAct on the loaded figures above, and leave any gap the file does not size."


def _moves(question, data, owner, ctx):
    folded = " ".join((question or "").casefold().split())
    catalog = []
    flagship = _flagship_move(ctx)
    north = _north_move(ctx)
    pacific = _pacific_move(ctx)
    tickets = _ticket_move(ctx)
    buy = _buy_move(ctx)
    if any(token in folded for token in ("attention", "which store")):
        order = (pacific, flagship, tickets, north, buy)
    elif any(token in folded for token in ("north", "behind")):
        order = (north, flagship, pacific, tickets, buy)
    else:
        order = (flagship, north, pacific, tickets, buy)
    for item in order:
        if item:
            catalog.append(item)
    if owner and ctx["finance"] and len(catalog) < 5:
        card = ctx["finance"][0]
        catalog.append(
            f"Review {card.get('kicker')} with the loaded figure {card.get('value')}. "
            f"Value: {card.get('value')}, already in the file. Owner: Shilajit. Timeframe: this month."
        )
    if not catalog:
        return "1. No move is backed by a loaded figure. Value: not sized. The file has no pace, week, or forecast gap to size it. Owner: not named in the file. Timeframe: not set."
    lines = []
    for index, item in enumerate(catalog[:5], start=1):
        lines.append(f"{index}. {item}")
    return "\n".join(lines)


def _flagship_move(ctx):
    downs = ctx["downs"]
    if len(downs) < 2:
        return ""
    first, second = downs[0], downs[1]
    window = ctx["label"] or "each store's own prior week"
    return (
        f"Stand in {first['display']} and {second['display']} and find the lost sales. "
        f"Value: down {_rupee_lakh(abs(first['gap']))} and down {_rupee_lakh(abs(second['gap']))} versus each store's own prior week ({window}). "
        "Owner: Sanjoy / Anup / Vikas. Timeframe: this week."
    )


def _north_move(ctx):
    gap = _plan_gap(ctx["north"])
    if gap is None:
        return ""
    north = ctx["north"]
    return (
        "Put North back on its own pro-rata. "
        f"Value: {_lakh(gap)} (own pro-rata {_lakh(north.get('pro_rata_L'))} minus own net {_lakh(north.get('net_L'))}). "
        "Owner: Sanjoy / Anup / Vikas. Timeframe: before this month ends."
    )


def _pacific_move(ctx):
    sentence = _pacific_bits(ctx)
    if not sentence:
        return ""
    gap = sentence.get("gap")
    value = "Value: not sized. Bills per extra captured phone would size the capture lift."
    if gap is not None:
        value = (
            f"Value: {_rupee_lakh(abs(gap))} of week sales versus its own prior week. "
            "The gain from the audit score and the phone capture is not sized: bills per extra captured phone would size it."
        )
    return (
        f"Walk {sentence['name']} before the next audit visit. {value} "
        "Owner: Sanjoy / Anup / Vikas. Timeframe: before the next audit visit."
    )


def _ticket_move(ctx):
    lead = ctx["tickets"]
    if not lead or not lead.get("stale"):
        return ""
    name = _readable_ticket_store(lead.get("store"))
    return (
        f"Clear the stale tickets at {name}. "
        f"Value: not sized. Refunds or lost orders on the {lead.get('stale')} stale tickets out of {lead.get('count')} would size it. "
        "Owner: Sanjoy / Anup / Vikas. Timeframe: this week."
    )


def _buy_move(ctx):
    buy = ctx["buy"]
    if not buy or buy.get("price") is None or buy.get("baseline_avg") is None:
        return ""
    return (
        f"Re-check the {buy.get('city')} {buy.get('item')} buy before the next order. "
        f"Value: not sized. The quantity behind ₹{float(buy.get('price')):.2f} versus its own baseline "
        f"₹{float(buy.get('baseline_avg')):.2f} would size it. "
        "Owner: Sanjoy / Anup / Vikas. Timeframe: before the next order."
    )


def _nonobvious(ctx):
    bits = []
    if ctx["up"] and ctx["north_gap"] is not None and ctx["north_gap"] < 0:
        bits.append(
            f"{ctx['up']['display']} is up {_rupee_lakh(ctx['up']['gap'])} inside a North week that is down "
            f"{_rupee_lakh(abs(ctx['north_gap']))}, so the city total hides the rest of North."
        )
    channels = ctx["channels"] or {}
    swiggy = channels.get("swiggy") or {}
    zomato = channels.get("zomato") or {}
    if swiggy.get("stale") is not None and zomato.get("stale") is not None:
        label = _pretty_window(channels.get("window"))
        bits.append(
            f"In {label}, stale complaints are {swiggy.get('stale')} of {swiggy.get('tickets')} on Swiggy "
            f"and {zomato.get('stale')} of {zomato.get('tickets')} on Zomato. "
            "That is a complaint channel and a leading indicator, not a sales-channel split."
        )
    if not bits:
        return "**Non-obvious insight.** No second-order pattern is supported by the loaded figures."
    return "**Non-obvious insight.** " + " ".join(bits)


def _hypothesis(ctx):
    downs = ctx["downs"]
    if len(downs) >= 2:
        first, second = downs[0], downs[1]
        window = ctx["label"] or "the latest week"
        return (
            f"Hypothesis: the week drop is a slip at {first['display']} and {second['display']}, not a change in city prices. "
            f"Test: their gross over the next 7 days versus {window}. "
            "If both recover and their Famepilot counts stay flat, it was a one-week demand dip."
        )
    return "Hypothesis: none. The file does not support a cause beyond the figures already stated. Test: none until a second series is loaded."


def _missing(ctx):
    missing = ["Daypart is not loaded, so no daypart is stated."]
    if ctx["forecast_rows"]:
        lead = ctx["forecast_rows"][0]
        missing.append(
            f"Pred versus actual on the latest loaded day: {_store_name(lead.get('store'))} "
            f"{_pct(lead.get('pct'))} ({_rupee_lakh(lead.get('actual'))} versus mid {_rupee_lakh(lead.get('mid'))})."
        )
    else:
        missing.append("Store-level pred versus actual is not loaded, so no store forecast gap is stated.")
    missing.append(
        "Dine-in versus delivery sales are not loaded, so the 24.78% Swiggy and Zomato take "
        "(21% commission plus 18% GST on that commission) is not applied. "
        "A Famepilot channel is complaints, not sales."
    )
    return " ".join(missing)


def _data_line(ctx):
    bits = []
    windows = ctx["windows"] or {}
    summary = ctx["summary"] or {}
    if windows.get("week_start") and windows.get("latest"):
        bits.append(f"sales week {_as_of(windows.get('week_start'))}–{_as_of(windows.get('latest'))}")
    if summary.get("as_of_date"):
        bits.append(f"summary {_as_of(summary.get('as_of_date'))}")
    if ctx["label"]:
        bits.append(ctx["label"])
    if ctx["reelo_period"]:
        bits.append(f"Reelo {ctx['reelo_period']}")
    if not bits:
        return "Data: dates not loaded."
    return "Data: " + "; ".join(bits) + "."


def _worth_noting(question, data, text):
    """One line on a short lookup, only when a second series disagrees with the first."""
    folded = " ".join((question or "").casefold().split())
    if not any(token in folded for token in ("yesterday", "what were", "what was")):
        return ""
    if len(text or "") > 400 or (text or "").count("\n") > 2:
        return ""
    summary = data.get("summary") or {}
    parts = []
    pace = summary.get("target_pace_pct")
    actual = summary.get("mtd_actual_L")
    mid = summary.get("mtd_pred_mid_L")
    if pace is not None and actual is not None and mid is not None and float(actual) >= float(mid) and float(pace) < 100:
        parts.append(
            f"month-to-date net {_lakh(actual)} sits above the mid forecast {_lakh(mid)} "
            f"while pace is {_pct(pace).replace('-', '')} of its own pro-rata"
        )
    drop = _largest_rupee_drop(data)
    if drop:
        parts.append(
            f"{_store_name(drop.get('store'))} is {_pct(drop.get('pct'))} versus its own same weekday "
            f"({_rupee_lakh(drop.get('gross'))} versus {_rupee_lakh(drop.get('prior_gross'))})"
        )
    if not parts:
        return ""
    return "Worth noting: " + ", and ".join(parts) + "."


def _signed_lakh(value):
    if value < 0:
        return f"down {_rupee_lakh(abs(value))}"
    if value > 0:
        return f"up {_rupee_lakh(value)}"
    return _rupee_lakh(0)


def _plan_gap(row):
    if not row or row.get("pro_rata_L") is None or row.get("net_L") is None:
        return None
    return float(row["pro_rata_L"]) - float(row["net_L"])


def _pace(row):
    if not row or row.get("pace_pct") is None:
        return ""
    return _pct(row.get("pace_pct")).replace("-", "")


def _flagship_sentence(ctx):
    if len(ctx["downs"]) < 2:
        return ""
    first, second = ctx["downs"][0], ctx["downs"][1]
    return (
        f"{first['display']} is down {_rupee_lakh(abs(first['gap']))} and {second['display']} is down "
        f"{_rupee_lakh(abs(second['gap']))} versus each store's own prior week."
    )


def _pacific_bits(ctx):
    row = None
    for gap in ctx["gaps"]:
        if "pacific" in (gap.get("display") or "").casefold() or "pacific" in (gap.get("store") or "").casefold():
            row = gap
            break
    audit = ctx["audit"]
    phone = ctx["reelo_phone"]
    tickets = ctx["pacific_tickets"]
    if row is None and not audit:
        return None
    name = (row or {}).get("display") or (audit or {}).get("store") or "That store"
    return {
        "name": name,
        "gap": None if row is None else row.get("gap"),
        "audit": None if not audit else audit.get("score"),
        "period": None if not audit else audit.get("period"),
        "phone": None if not phone or "pacific" not in (phone.get("store") or "").casefold() else phone.get("phone_capture"),
        "stale": None if not tickets else tickets.get("stale"),
        "count": None if not tickets else tickets.get("count"),
    }


def _pacific_sentence(ctx):
    bits = _pacific_bits(ctx)
    if not bits or bits.get("gap") is None:
        return ""
    parts = [f"Your first walk is {bits['name']}: week sales are down {_rupee_lakh(abs(bits['gap']))}"]
    if bits.get("audit") is not None:
        parts.append(f"the mystery audit is {_pct(bits['audit'])}")
    if bits.get("phone") is not None:
        parts.append(f"phone capture is {bits['phone']:.2f}%")
    if bits.get("stale") is not None and bits.get("count"):
        parts.append(f"{bits['stale']} of {bits['count']} tickets are stale")
    return ", ".join(parts) + "."


def _week_gaps():
    try:
        from app.chat.wizard_a import _weekly_gaps
        gaps, label = _weekly_gaps()
    except Exception:
        return [], ""
    return list(gaps or []), label or ""


def _sum_gap(gaps, region):
    rows = [row for row in gaps if (row.get("region") or "") == region]
    if not rows:
        return None
    return sum(float(row["gap"]) for row in rows)


def _largest_rupee_drop(data):
    latest = (data.get("sales_windows") or {}).get("latest")
    ranked = []
    for row in data.get("movers") or []:
        if latest and row.get("date") != latest:
            continue
        if _closed_name(row.get("store")) or _rosedale(row.get("store")):
            continue
        try:
            gap = float(row.get("gross") or 0) - float(row.get("prior_gross") or 0)
        except (TypeError, ValueError):
            continue
        if gap >= 0:
            continue
        ranked.append((gap, row))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def _ticket_lead(data):
    stores = list((data.get("tickets") or {}).get("stores") or [])
    stores = [row for row in stores if not _closed_name(row.get("store")) and not _rosedale(row.get("store"))]
    if not stores:
        return None
    stores.sort(key=lambda row: row.get("stale") or 0, reverse=True)
    return stores[0]


def _match_ticket(data, needle):
    needle = (needle or "").casefold()
    for row in (data.get("tickets") or {}).get("stores") or []:
        if needle in str(row.get("store") or "").casefold():
            return row
    return None


def _lowest_reelo(data, field):
    rows = [row for row in (data.get("reelo") or []) if row.get(field) is not None]
    if not rows:
        return None
    rows.sort(key=lambda row: row[field])
    return rows[0]


def _sharpest_buy(data):
    from app.chat.guard import flag_unconfirmed

    pack = data.get("procurement") or {}
    held = set()
    for flag in pack.get("flags") or []:
        if not flag_unconfirmed(flag):
            continue
        for key in ("item", "name"):
            if flag.get(key):
                held.add(str(flag.get(key)).casefold())
    rows = [
        row for row in (pack.get("above_average") or [])
        if isinstance(row, dict) and row.get("pct_above") is not None
        and str(row.get("item") or "").casefold() not in held
    ]
    if not rows:
        return None
    rows.sort(key=lambda row: float(row.get("pct_above") or 0), reverse=True)
    return rows[0]


def _food_outlier(data):
    best = None
    for row in (data.get("dossiers") or {}).values():
        food = row.get("food") or {}
        if food.get("sanity") or food.get("exclude_compare"):
            continue
        if food.get("pct") is None:
            continue
        try:
            pct = float(food.get("pct"))
        except (TypeError, ValueError):
            continue
        if pct < 15 or pct > 45:
            continue
        median = _parse_pct(food.get("city_median"))
        if median is None:
            continue
        gap = pct - median
        if best is None or gap > best["gap"]:
            best = {
                "name": row.get("name") or "That store",
                "pct": pct,
                "median": median,
                "packaging": food.get("packaging_pct") or "",
                "period": food.get("period") or "",
                "gap": gap,
            }
    return best


def _parse_pct(value):
    raw = str(value or "").replace("%", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _lowest_audit(data):
    rows = [row for row in (data.get("october_audit") or []) if isinstance(row, dict) and row.get("score") is not None]
    if not rows:
        return None
    rows.sort(key=lambda row: float(row["score"]))
    return rows[0]


def _channel_week(data):
    grouped = {}
    for row in (data.get("tickets") or {}).get("weekly") or []:
        if (row.get("split") or "") != "channel":
            continue
        grouped.setdefault(row.get("window") or "", []).append(row)
    if not grouped:
        return None
    window = sorted(grouped)[-1]
    found = {"window": window}
    for row in grouped[window]:
        key = (row.get("key") or "").casefold()
        try:
            tickets = int(float(row.get("tickets") or 0))
        except (TypeError, ValueError):
            continue
        stale = None
        if row.get("stale") not in (None, "", "blank"):
            try:
                stale = int(float(row.get("stale")))
            except (TypeError, ValueError):
                stale = None
        found[key] = {"tickets": tickets, "stale": stale}
    if "swiggy" not in found or "zomato" not in found:
        return None
    return found


def _pretty_window(window):
    parts = str(window or "").split("_to_")
    if len(parts) != 2:
        return "the latest complaint week"
    try:
        start = datetime.strptime(parts[0], "%Y-%m-%d")
    except ValueError:
        return "the latest complaint week"
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{start.day}–{parts[1]} {months[start.month - 1]}"


def _rosedale(name):
    return "rosedale" in (name or "").casefold()


def _closed_name(name):
    text = (name or "").casefold()
    return "faridabad" in text or "chattarpur" in text or "gk1" in text or "gk 1" in text


def _trading_week(rows):
    """Open stores that actually sold. A zero from a closed store is not a result."""
    trading = []
    for row in rows:
        if _closed_name(row.get("store")):
            continue
        gross = row.get("gross")
        if gross in (None, 0):
            continue
        trading.append(row)
    trading.sort(key=lambda row: row.get("gross") or 0, reverse=True)
    return trading


def _store_name(name):
    text = str(name or "").split("(")[0].strip()
    return text or "That store"
