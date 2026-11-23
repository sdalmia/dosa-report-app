"""Why and next steps for an analytic question, using only loaded figures."""

from app.chat.facts import _as_of, _lakh, _pct, _readable_ticket_store, _region, actions_from_data


def _rupee_lakh(value):
    """A rupee total, shown in lakhs. Values already stored in lakhs use _lakh."""
    number = float(value)
    sign = "-" if number < 0 else ""
    return f"{sign}₹{abs(number) / 100000:.2f}L"


def is_analytic(question):
    """A reason is added for a sales or attention question, not for a lookup."""
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


def _bold_first(text):
    if not text or text.startswith("**"):
        return text
    end = text.find(". ")
    if end < 0:
        return "**" + text + "**"
    return "**" + text[: end + 1] + "**" + text[end + 1 :]


def sections(question, data, owner):
    """Markdown after the direct answer. Empty when the question is a lookup."""
    if not is_analytic(question):
        return ""
    parts = [
        "**Why**",
        "",
        _sales_why(data),
        "No daypart split is in the packet, so no daypart is stated.",
        "A sales-channel split (dine-in versus delivery) is not in this packet, so it is not used as a driver. A Famepilot channel is a complaint source, not a sales channel.",
        "",
        "**Likely causes**",
        "",
        _causes(data),
        "",
        "**Next steps**",
        "",
        _steps(data, owner),
    ]
    return "\n".join(part for part in parts if part is not None)


def attach(packed, question, data, owner):
    """Append the reasoned sections. A role refusal stays as it is."""
    if not packed or not is_analytic(question):
        return packed
    text = packed.get("text") or ""
    folded = text.casefold()
    if "not included for this role" in folded or "only on the owner login" in folded:
        return packed
    extra = sections(question, data, owner)
    if extra and "**Why**" not in text:
        packed["text"] = _bold_first(text).rstrip() + "\n\n" + extra
    return packed


def _sales_why(data):
    lines = []
    summary = data.get("summary") or {}
    pace = summary.get("target_pace_pct")
    east = _region(summary, "East")
    north = _region(summary, "North")
    if pace is not None and east.get("pace_pct") is not None and north.get("pace_pct") is not None:
        on_net = f" on {_lakh(summary.get('mtd_actual_L'))} net" if summary.get("mtd_actual_L") is not None else ""
        east_own = ""
        if east.get("net_L") is not None and east.get("pro_rata_L") is not None:
            east_own = f" on {_lakh(east.get('net_L'))} net versus its own pro-rata {_lakh(east.get('pro_rata_L'))}"
        north_own = ""
        if north.get("net_L") is not None and north.get("pro_rata_L") is not None:
            north_own = f" on {_lakh(north.get('net_L'))} net versus its own pro-rata {_lakh(north.get('pro_rata_L'))}"
        lines.append(
            f"November pace is {_pct(pace).replace('-', '')}{on_net}, "
            "against this month's own pro-rata, not against another month. "
            f"East is {_pct(east.get('pace_pct')).replace('-', '')}{east_own}. "
            f"North is {_pct(north.get('pace_pct')).replace('-', '')}{north_own}."
        )
    windows = data.get("sales_windows") or {}
    week = _trading_week(windows.get("week_rows") or [])
    if week:
        gross = sum(float(row.get("gross") or 0) for row in week)
        lines.append(
            f"The last 7 sales days ({windows.get('week_start') or '?'} to {windows.get('latest') or '?'}) "
            f"gross {_rupee_lakh(gross)} across {len(week)} open stores. "
            f"The largest week gross is {_store_name(week[0].get('store'))} at {_rupee_lakh(week[0].get('gross'))}. "
            f"The smallest open store is {_store_name(week[-1].get('store'))} at {_rupee_lakh(week[-1].get('gross'))}. "
            "A closed store is not ranked, and a blank day is not zero."
        )
    try:
        from app.chat.wizard_a import trend_rows
        trends = trend_rows()
    except Exception:
        trends = []
    if trends:
        label = trends[0].get("label") or "the two latest weeks"
        shown = trends[:4]
        bits = [
            f"{row['display']} {row['direction']} {_rupee_lakh(abs(row['impact']))}"
            for row in shown
        ]
        lines.append(
            f"Versus each store's own previous 7 days ({label}): " + "; ".join(bits) + ". "
            "A missing day is left out of both weeks, not treated as zero."
        )
    latest = windows.get("latest")
    movers = [
        row for row in (data.get("movers") or [])
        if row.get("date") == latest and not _closed_name(row.get("store"))
    ]
    if movers:
        lead = movers[:3]
        bits = [
            f"{_store_name(row.get('store'))} {_pct(row.get('pct'))} "
            f"({_rupee_lakh(row.get('gross'))} versus {_rupee_lakh(row.get('prior_gross'))} on {_as_of(row.get('prior_date'))})"
            for row in lead
        ]
        lines.append(
            "Latest sales day versus that store's own same weekday a week earlier: " + "; ".join(bits) + "."
        )
    if not lines:
        lines.append("The packet has no pace, week, or same-weekday comparison to explain.")
    return " ".join(lines)


def _causes(data):
    lines = []
    tickets = data.get("tickets") if isinstance(data.get("tickets"), dict) else {}
    stores = list(tickets.get("stores") or [])
    if stores:
        stores.sort(key=lambda row: row.get("stale") or 0, reverse=True)
        lead = stores[0]
        lines.append(
            f"Complaints: {_readable_ticket_store(lead.get('store'))} has {lead.get('stale')} stale tickets "
            f"out of {lead.get('count')} "
            f"({_pct(lead.get('stale_share')) if lead.get('stale_share') is not None else 'share not loaded'}). "
            f"The newest ticket date is {_as_of(tickets.get('as_of')) or 'unknown'}."
        )
    else:
        lines.append("Complaints: Famepilot tickets are not loaded, so none are used as a cause.")
    reelo = [row for row in (data.get("reelo") or []) if row.get("phone_capture") is not None]
    if reelo:
        reelo.sort(key=lambda row: row["phone_capture"])
        low = reelo[0]
        repeat = [row for row in reelo if row.get("repeat_share") is not None]
        repeat.sort(key=lambda row: row["repeat_share"])
        extra = ""
        if repeat:
            extra = (
                f" The lowest repeat share on the same file is {repeat[0]['store']} at "
                f"{repeat[0]['repeat_share']:.2f}%."
            )
        lines.append(
            f"Reelo ({data.get('reelo_period') or 'period not labelled'}): "
            f"{low['store']} phone capture is {low['phone_capture']:.2f}% of its own orders."
            + extra
            + " Stores missing from Reelo are left out on purpose."
        )
    else:
        lines.append("Reelo is not loaded, so it is not used as a cause.")
    pack = data.get("procurement") or {}
    above = [row for row in (pack.get("above_average") or []) if isinstance(row, dict)]
    if above:
        row = above[0]
        lines.append(
            f"Procurement, as of {pack.get('as_of') or 'unknown'}: {row.get('city')} {row.get('item')} "
            f"was {row.get('pct_above')}% above its own baseline "
            f"({row.get('price')} versus {row.get('baseline_avg')} on {row.get('date')}). "
            "That is not compared with the other city."
        )
    else:
        lines.append("Procurement prices are not loaded, so none are used as a cause.")
    audit = [row for row in (data.get("october_audit") or []) if isinstance(row, dict) and row.get("score") is not None]
    if audit:
        audit = sorted(audit, key=lambda row: float(row["score"]))
        lead = audit[0]
        lines.append(
            f"Service check: {lead.get('store')} scored {_pct(lead.get('score'))} "
            f"in the {lead.get('period') or 'October'} mystery audit, the lowest loaded score."
        )
    else:
        lines.append("No mystery-audit score is loaded, so no service check is stated.")
    return " ".join(lines)


def _steps(data, owner):
    actions = list(actions_from_data(data, owner))
    seen = set()
    lines = []
    for action in actions:
        key = (action.get("what") or "").casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(action)
    audit = [row for row in (data.get("october_audit") or []) if isinstance(row, dict) and row.get("score") is not None]
    if audit and len(lines) < 3:
        lead = sorted(audit, key=lambda row: float(row["score"]))[0]
        lines.append({
            "what": f"Walk {_store_name(lead.get('store'))} before the next audit visit.",
            "why": f"Mystery audit {_pct(lead.get('score'))}.",
            "owner": "Sanjoy / Anup / Vikas",
        })
    tickets = (data.get("tickets") or {}).get("stores") or []
    if tickets and len(lines) < 4:
        lead = sorted(tickets, key=lambda row: row.get("stale") or 0, reverse=True)[0]
        if lead.get("stale"):
            lines.append({
                "what": f"Clear stale tickets at {_readable_ticket_store(lead.get('store'))}.",
                "why": f"{lead.get('stale')} stale of {lead.get('count')} tickets.",
                "owner": "Sanjoy / Anup / Vikas",
            })
    if not lines:
        return "1. No action is backed by a loaded figure. Owner: not named in the packet."
    numbered = []
    for index, action in enumerate(lines[:5], start=1):
        owner_name = action.get("owner") or "not named in the packet"
        numbered.append(f"{index}. {action.get('what')} {action.get('why')} Owner: {owner_name}.")
    return "\n".join(numbered)


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
