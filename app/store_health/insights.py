"""Ops, CRM, and cost actions for one store.

Each sentence uses a figure already on that store's row. A blank metric is
skipped. A missing mystery-audit score is one short line, then nothing more
about the audit. This module does not narrate filenames, does not turn a
blank into zero, and does not compute a variance the file left empty.
"""

import re

from app.store_health.present import (
    FAMEPILOT_WINDOW,
    format_count,
    format_date,
    format_money,
    format_pct,
    parse_number,
    present_audit,
    present_famepilot,
    present_reelo,
)


NO_AUDIT_SCORE = "There is no mystery audit score to act on."
# A public rating under 4 is the weak cutoff for a close-the-tickets action.
_WEAK_RATING = 4
_LEADING_NUMBER = re.compile(r"^[+-]?\d+(?:\.\d+)?")


def build_insights(feeds, store):
    """Return ops, CRM, and cost actions for the store.

    A store with no joined rows stays empty.
    """
    empty = {"has_insight": False, "ops": [], "crm": [], "cost": []}
    if store is None:
        return empty
    ops = _ops(feeds, store)
    crm = _crm(feeds, store)
    cost = _cost(feeds, store)
    if not ops and not crm and not cost:
        return empty
    return {"has_insight": True, "ops": ops, "crm": crm, "cost": cost}


def _posist_rows(feeds, store):
    keys = store.match_keys()
    return [row for (name, _day), row in feeds.get("posist", {}).items() if name in keys]


def _calendar_rows(feeds, store):
    keys = store.match_keys()
    return [row for (name, _day), row in feeds.get("calendar", {}).items() if name in keys]


def _newest(rows, field=None):
    chosen = None
    for row in rows:
        if field is not None and row.get(field) is None:
            continue
        if chosen is None or row["date"] > chosen["date"]:
            chosen = row
    return chosen


def _newest_present(rows, fields):
    chosen = None
    for row in rows:
        if not any(row.get(field) is not None for field in fields):
            continue
        if chosen is None or row["date"] > chosen["date"]:
            chosen = row
    return chosen


def _has_joined_row(feeds, store):
    if _posist_rows(feeds, store) or _calendar_rows(feeds, store):
        return True
    if present_audit(feeds, store)["has_row"]:
        return True
    if present_famepilot(feeds, store)["has_row"]:
        return True
    if present_reelo(feeds, store)["has_row"]:
        return True
    keka = feeds.get("keka_by_store", {}).get(store.label) if store else None
    return keka is not None


def _leading_number(text):
    if not text:
        return None
    match = _LEADING_NUMBER.match(str(text).strip().replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _score_text(raw):
    number = _leading_number(raw)
    if number is None:
        return ""
    if float(number).is_integer():
        body = str(int(number))
    else:
        body = f"{float(number):.10f}".rstrip("0").rstrip(".")
    if "%" in str(raw):
        return body + "%"
    return body


def _detail(parts):
    filled = [part for part in parts if part]
    if not filled:
        return ""
    return " (" + "; ".join(filled) + ")"


def _ops(feeds, store):
    lines = []
    rows = _posist_rows(feeds, store)
    if rows:
        void = _void_line(rows)
        if void:
            lines.append(void)
        bills = _bill_line(rows)
        if bills:
            lines.append(bills)
    audit_line = _audit_line(present_audit(feeds, store))
    if audit_line == NO_AUDIT_SCORE:
        if _has_joined_row(feeds, store):
            lines.append(NO_AUDIT_SCORE)
    elif audit_line:
        lines.append(audit_line)
    return lines


def _void_line(rows):
    filled = [row.get("void_bills") for row in rows if row.get("void_bills") is not None]
    if not filled:
        return ""
    total = sum(float(value) for value in filled)
    shown = format_count(total)
    if total == 0:
        return f"Void bills are {shown}. Leave voids alone."
    return f"Void bills are {shown}. Confirm a reason on each void bill before the next close."


def _bill_line(rows):
    row = _newest(rows, "bills_wow_pct")
    if row is None:
        return ""
    day = format_date(row["date"])
    pct_value = row.get("bills_wow_pct")
    pct = format_pct(pct_value)
    bills = format_count(row.get("bills")) if row.get("bills") is not None else ""
    last = format_count(row.get("bills_last_same_weekday")) if row.get("bills_last_same_weekday") is not None else ""
    bracket = _detail([
        f"{bills} bills" if bills else "",
        f"{last} on the last same weekday" if last else "",
    ])
    if pct_value == 0:
        held = f" at {bills} bills" if bills else ""
        return f"On {day}, bills were unchanged{held}. Hold that bill count."
    if pct_value < 0:
        return (
            f"On {day}, bills were {pct} versus the last same weekday{bracket}. "
            "Find what cut that bill count before the next same weekday."
        )
    return (
        f"On {day}, bills were {pct} versus the last same weekday{bracket}. "
        "Keep whatever added those bills."
    )


def _audit_line(audit):
    if not audit["has_row"]:
        return NO_AUDIT_SCORE
    fields = audit["fields"]
    status = (fields.get("audit_status") or "").casefold()
    average_raw = fields.get("audit_avg") or ""
    if status == "not in cycle" or average_raw.casefold() == "not in cycle":
        return NO_AUDIT_SCORE
    weekday_raw = fields.get("audit_weekday") or ""
    weekend_raw = fields.get("audit_weekend") or ""
    average = _score_text(average_raw)
    weekday = _score_text(weekday_raw)
    weekend = _score_text(weekend_raw)
    if not average and not weekday and not weekend:
        return NO_AUDIT_SCORE
    period = fields.get("audit_period") or ""
    period_bit = f" for {period}" if period else ""
    sentences = []
    if average:
        sentences.append(f"Mystery audit average{period_bit} is {average}.")
    elif period:
        sentences.append(f"Mystery audit for {period} has a split score.")
    if weekday:
        sentences.append(f"Weekday score is {weekday}.")
    if weekend:
        sentences.append(f"Weekend score is {weekend}.")
    action = _audit_action(
        average,
        _leading_number(average_raw),
        _leading_number(weekday_raw),
        _leading_number(weekend_raw),
        (fields.get("audit_note") or "").casefold(),
    )
    if action:
        sentences.append(action)
    return " ".join(sentences)


def _audit_action(average, avg_n, week_n, end_n, note):
    if "pos outage" in note:
        return "Confirm the weekday POS outage is closed before the next weekday service."
    if "weekend crash" in note:
        return "Review the weekend service the audit calls a crash before the next weekend."
    if "soft both" in note:
        return "Walk the service on both a weekday and a weekend before the next audit."
    below = []
    if avg_n is not None and week_n is not None and week_n < avg_n:
        below.append("weekday")
    if avg_n is not None and end_n is not None and end_n < avg_n:
        below.append("weekend")
    if below == ["weekday", "weekend"]:
        return "Walk the weekday and weekend service before the next audit visit."
    if below == ["weekday"]:
        return "Walk the weekday service before the next audit visit."
    if below == ["weekend"]:
        return "Walk the weekend service before the next audit visit."
    if average:
        return f"Hold the {average} score on the next audit visit."
    return ""


def _crm(feeds, store):
    lines = []
    lines.extend(_fame_lines(present_famepilot(feeds, store)))
    lines.extend(_reelo_lines(present_reelo(feeds, store)))
    return lines


def _fame_lines(fame):
    if not fame["has_row"] or fame["no_location"]:
        return []
    fields = fame["fields"]
    lines = []
    public = _public_action(fields)
    if public:
        lines.append(public)
    private = _private_action(fields)
    if private:
        lines.append(private)
    if lines:
        lines.append(FAMEPILOT_WINDOW)
    return lines


def _public_action(fields):
    rating = fields.get("rating") or ""
    reviews = fields.get("review_count") or ""
    threat = fields.get("main_threat") or ""
    folded = threat.casefold()
    rating_n = parse_number(rating) if rating else None
    if not rating and not (folded.startswith("tie:") or (threat and folded != "not shown")):
        return ""
    sentences = []
    if rating and reviews:
        sentences.append(f"Public rating is {rating} on {reviews} reviews.")
    elif rating:
        sentences.append(f"Public rating is {rating}.")
    weak = rating_n is not None and rating_n < _WEAK_RATING
    if folded.startswith("tie:"):
        named = threat.split(":", 1)[1].strip()
        sentences.append(
            f"Main complaint is a tie: {named}. "
            "Check tickets for each complaint in the tie before the next shift."
        )
    elif folded in {"", "not shown"}:
        if rating and weak:
            sentences.append("Lift that rating before the next shift.")
        elif rating:
            sentences.append("Hold that rating.")
    else:
        sentences.append(f"Close {threat} tickets before the next shift.")
    return " ".join(sentences)


def _private_action(fields):
    count = fields.get("private_review_count") or ""
    count_n = parse_number(count) if count else None
    if count_n is None or count_n <= 0:
        return ""
    rating = fields.get("private_rating") or ""
    if rating:
        return (
            f"Private rating is {rating} on {count} reviews. "
            "Read those private reviews with the shift lead."
        )
    return f"Private review count is {count}. Read those private reviews with the shift lead."


def _reelo_lines(reelo):
    if not reelo["has_row"] or reelo["not_in_reelo"]:
        return []
    fields = reelo["fields"]
    lines = []
    capture = _capture_line(fields)
    if capture:
        lines.append(capture)
    redemption = _redemption_line(fields)
    if redemption:
        lines.append(redemption)
    return lines


def _capture_line(fields):
    capture = fields.get("phone_capture") or ""
    blocked = fields.get("phones_blocked") or ""
    capture_n = parse_number(capture) if capture else None
    blocked_n = parse_number(blocked) if blocked else None
    if capture_n == 100:
        return f"Phone capture is {capture}. Capture is fine."
    if capture_n is not None and blocked_n is not None and blocked_n > 0:
        return (
            f"Phone capture is {capture}. Blocked visits are {blocked}. "
            "Clear those blocked visits before the next phone-capture push."
        )
    if capture_n is not None and capture_n < 100:
        return f"Phone capture is {capture}. Ask for a phone number on the next visit."
    if blocked_n is not None and blocked_n > 0:
        return (
            f"Blocked visits are {blocked}. "
            "Clear those blocked visits before the next phone-capture push."
        )
    return ""


def _redemption_line(fields):
    rate = fields.get("redemption_rate") or ""
    times = fields.get("times_redeemed") or ""
    if rate and times:
        return (
            f"Redemption rate is {rate} across {times} redemptions. "
            "Ask the next guest who has points to redeem."
        )
    if rate:
        return f"Redemption rate is {rate}. Ask the next guest who has points to redeem."
    if times:
        return f"Rewards were redeemed {times} times. Ask the next guest who has points to redeem."
    return ""


def _cost(feeds, store):
    lines = []
    rows = _posist_rows(feeds, store)
    if rows:
        unsettled = _unsettled_line(rows)
        if unsettled:
            lines.append(unsettled)
        lines.extend(_sales_lines(rows))
    calendar = _calendar_line(_calendar_rows(feeds, store))
    if calendar:
        lines.append(calendar)
    return lines


def _unsettled_line(rows):
    amounts = [row.get("unsettled_amount") for row in rows if row.get("unsettled_amount") is not None]
    bills = [row.get("unsettled_bills") for row in rows if row.get("unsettled_bills") is not None]
    if not amounts and not bills:
        return ""
    amount = sum(float(value) for value in amounts) if amounts else None
    count = sum(float(value) for value in bills) if bills else None
    amount_txt = format_money(amount, "unsettled_amount") if amount is not None else ""
    count_txt = format_count(count) if count is not None else ""
    amount_zero = amount is not None and amount == 0
    count_zero = count is not None and count == 0
    if (amount is None or amount_zero) and (count is None or count_zero):
        if count_txt and amount_txt:
            return f"Unsettled bills are {count_txt} ({amount_txt}). There is nothing to clear."
        if count_txt:
            return f"Unsettled bills are {count_txt}. There is nothing to clear."
        return f"Unsettled amount is {amount_txt}. There is nothing to clear."
    if count_txt and amount_txt:
        return f"Clear the {count_txt} unsettled bills ({amount_txt}) before the next close."
    if count_txt:
        return f"Clear the {count_txt} unsettled bills before the next close."
    return f"Clear the unsettled amount of {amount_txt} before the next close."


def _sales_lines(rows):
    lines = []
    net_move = _newest(rows, "net_wow_pct")
    if net_move is not None and net_move.get("net") is not None:
        lines.append(_net_line(net_move))
    else:
        level = _level_line(rows)
        if level:
            lines.append(level)
    apb = _apb_line(rows)
    if apb:
        lines.append(apb)
    return lines


def _net_line(row):
    day = format_date(row["date"])
    pct_value = row.get("net_wow_pct")
    pct = format_pct(pct_value)
    net = format_money(row.get("net"), "net") if row.get("net") is not None else ""
    last = (
        format_money(row.get("net_last_same_weekday"), "net_last_same_weekday")
        if row.get("net_last_same_weekday") is not None
        else ""
    )
    bracket = _detail([net, f"{last} on the last same weekday" if last else ""])
    if pct_value == 0:
        return f"On {day}, net was unchanged{bracket}. Hold that net."
    if pct_value < 0:
        return (
            f"On {day}, net was {pct} versus the last same weekday{bracket}. "
            "Find what cut that net before the next same weekday."
        )
    return (
        f"On {day}, net was {pct} versus the last same weekday{bracket}. "
        "Keep that net on the next same weekday."
    )


def _level_line(rows):
    row = _newest_present(rows, ("net", "gross"))
    if row is None:
        return ""
    if row.get("net") is not None:
        kind = "net"
        money = format_money(row.get("net"), "net")
    else:
        kind = "gross"
        money = format_money(row.get("gross"), "gross")
    day = format_date(row["date"])
    bills = format_count(row.get("bills")) if row.get("bills") is not None else ""
    bill_bit = f" on {bills} bills" if bills else ""
    return (
        f"On {day}, {kind} was {money}{bill_bit}. "
        f"Add one more item on the next bill to lift that {kind}."
    )


def _apb_line(rows):
    row = _newest(rows, "apb")
    if row is None:
        return ""
    day = format_date(row["date"])
    apb = format_money(row.get("apb"), "apb")
    pct_value = row.get("apb_wow_pct")
    last = (
        format_money(row.get("apb_last_same_weekday"), "apb_last_same_weekday")
        if row.get("apb_last_same_weekday") is not None
        else ""
    )
    if pct_value is None:
        return f"On {day}, APB was {apb}. Add one more item on the next bill to lift that APB."
    pct = format_pct(pct_value)
    last_bit = f" from {last}" if last else ""
    if pct_value == 0:
        return f"On {day}, APB was {apb}, unchanged{last_bit}. Hold that APB."
    if pct_value < 0:
        return (
            f"On {day}, APB was {apb}, {pct}{last_bit}. "
            "Add one more item on the next bill to lift that APB."
        )
    return (
        f"On {day}, APB was {apb}, {pct}{last_bit}. "
        "Add one more item on the next bill to lift that APB."
    )


def _calendar_line(rows):
    varied = [row for row in rows if row.get("variance_vs_mid") is not None]
    if not varied:
        return ""
    row = _newest(varied)
    day = format_date(row["date"])
    sentences = [f"On {day}, variance versus mid is {format_money(row.get('variance_vs_mid'), 'variance_vs_mid')}."]
    if row.get("actual_net") is not None:
        sentences.append(f"Actual Net was {format_money(row.get('actual_net'), 'actual_net')}.")
    if row.get("pred_mid") is not None:
        sentences.append(f"Mid was {format_money(row.get('pred_mid'), 'pred_mid')}.")
    notes = (row.get("notes") or "").strip()
    if notes and "closed" in notes.casefold():
        sentences.append(f"The note says {notes}. Confirm whether that closure is still in effect.")
    elif row.get("variance_vs_mid") < 0:
        sentences.append("Find what missed the mid before the next same weekday.")
    elif row.get("variance_vs_mid") > 0:
        sentences.append("Keep whatever beat the mid.")
    else:
        sentences.append("Hold that result against the mid.")
    return " ".join(sentences)
