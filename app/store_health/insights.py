"""Ops, CRM, and cost lines for one store.

Every figure is taken from a row already joined to that store. A blank cell
stays blank. A missing feed is named. This module does not turn a blank into
zero and does not compute a variance the file left empty.
"""

from app.store_health.contract import (
    AUDIT_FILE,
    CALENDAR_FILE,
    FAMEPILOT_FILE,
    KEKA_ACTIVE_FILE,
    KEKA_FILE,
    POSIST_FILE,
    REELO_FILE,
)
from app.store_health.present import (
    FAMEPILOT_WINDOW,
    REELO_PHONE_CAVEAT,
    STATUS_LABELS,
    format_count,
    format_date,
    format_money,
    format_pct,
    posist_window,
    present_audit,
    present_famepilot,
    present_keka,
    present_reelo,
    parse_number,
)


NOT_ON_FILE = "{filename} is not on file for this store."


def build_insights(feeds, store):
    """Return ops, CRM, and cost sentences for the store.

    A store with no joined rows stays empty. Gap lines ("not on file") are
    added only after at least one sentence comes from a real row.
    """
    empty = {"has_insight": False, "ops": [], "crm": [], "cost": []}
    if store is None:
        return empty

    ops, ops_gaps = _ops(feeds, store)
    crm, crm_gaps = _crm(feeds, store)
    cost, cost_gaps = _cost(feeds, store)
    if not ops and not crm and not cost:
        return empty
    return {
        "has_insight": True,
        "ops": ops + ops_gaps,
        "crm": crm + crm_gaps,
        "cost": cost + cost_gaps,
    }


def _gap(filename):
    return NOT_ON_FILE.format(filename=filename)


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


def _window_phrase(label):
    if label:
        return f"in the Posist window ({label})"
    return "in the Posist window"


def _ops(feeds, store):
    lines = []
    gaps = []
    rows = _posist_rows(feeds, store)
    window = posist_window(feeds, store)
    if rows:
        lines.extend(_posist_ops(rows, window))
    else:
        gaps.append(_gap(POSIST_FILE))
    audit = present_audit(feeds, store)
    if audit["has_row"]:
        lines.append(_audit_line(audit))
    else:
        gaps.append(_gap(AUDIT_FILE))
    keka = present_keka(feeds, store)
    if keka["has_row"]:
        lines.append(_keka_line(keka))
    else:
        if keka.get("active_state") == "missing":
            gaps.append(_gap(KEKA_ACTIVE_FILE))
        if keka.get("lead_state") == "missing":
            gaps.append(_gap(KEKA_FILE))
    return lines, gaps


def _posist_ops(rows, window):
    lines = []
    label = window.get("window_label") or ""
    shown = window["fields"]["void_bills"]
    filled = [row.get("void_bills") for row in rows if row.get("void_bills") is not None]
    if not filled:
        lines.append("Void bills are blank in posist_daily.csv, so no void action is on file.")
    else:
        sentence = f"Void bills {_window_phrase(label)} are {shown}"
        if len(filled) != len(rows):
            sentence += ", counting only days where the cell is filled"
        if shown == "0":
            sentence += ". No void-ticket action is on file."
        else:
            sentence += ". Open those void tickets and confirm each one had a reason."
        lines.append(sentence)
    lines.append(_bill_line(rows))
    missing = window.get("missing_label") or ""
    if missing:
        lines.append(f"{missing} Do not treat the totals as a full window.")
    return lines


def _bill_line(rows):
    row = _newest(rows, "bills_wow_pct")
    if row is None:
        return "Week-on-week bills are blank in posist_daily.csv, so no bill-count action is on file."
    pct = format_pct(row.get("bills_wow_pct"))
    day = format_date(row["date"])
    bills = format_count(row.get("bills")) if row.get("bills") is not None else ""
    last = format_count(row.get("bills_last_same_weekday")) if row.get("bills_last_same_weekday") is not None else ""
    detail = []
    if bills:
        detail.append(f"{bills} bills")
    if last:
        detail.append(f"{last} on the last same weekday")
    bracket = f" ({'; '.join(detail)})" if detail else ""
    if pct == "0%":
        return (
            f"On {day}, bills were unchanged versus the prior week{bracket}. "
            "No bill-count action is on file."
        )
    return (
        f"On {day}, bills moved {pct} versus the prior week{bracket}. "
        "Ask the store what changed in that bill count."
    )


def _audit_line(audit):
    fields = audit["fields"]
    period = fields.get("audit_period") or "the period on file"
    status = (fields.get("audit_status") or "").casefold()
    average = fields.get("audit_avg") or ""
    if status == "not in cycle" or average.casefold() == "not in cycle":
        return f"Mystery audit for {period} is not in cycle. No audit action is on file."
    sentences = []
    if average:
        sentences.append(f"Mystery audit average for {period} is {average}.")
    else:
        sentences.append(f"Mystery audit average for {period} is blank, so do not treat it as zero.")
    for label, key in (("Weekday score", "audit_weekday"), ("Weekend score", "audit_weekend")):
        value = fields.get(key) or ""
        if value:
            sentences.append(f"{label} is {value}.")
    note = fields.get("audit_note") or ""
    if note:
        sentences.append(f"The file notes: {note}.")
        action = _audit_action(note)
        sentences.append(action or "The note does not name a next step.")
    else:
        sentences.append("The audit note is blank, so no next step is on file.")
    return " ".join(sentences)


def _audit_action(note):
    text = note.casefold()
    if "pos outage" in text:
        return "Confirm the weekday POS outage is closed before the next weekday service."
    if "weekend crash" in text:
        return "Review the weekend service the audit calls a crash before the next weekend."
    if "soft both" in text:
        return "Walk the service on both a weekday and a weekend before the next audit."
    return ""


def _keka_line(keka):
    fields = keka["fields"]
    sentences = []
    active = fields.get("active_employees") or ""
    if keka.get("active_state") == "missing":
        sentences.append("keka_active.csv is missing. Do not treat active employees as zero.")
    elif keka.get("unmatched") or not active:
        sentences.append("Active employees are unmatched, not zero.")
    else:
        sentences.append(f"Active employees are {active}.")
    lead = fields.get("primary_lead") or ""
    if lead:
        sentences.append(f"Primary lead on file is {lead}.")
        sentences.append("The lead is the largest reporting line, not a confirmed single store manager.")
        sentences.append(f"Confirm who is covering the next service with {lead}.")
    else:
        sentences.append("No primary lead is on file, so there is no named person to confirm for the next service.")
    return " ".join(sentences)


def _crm(feeds, store):
    lines = []
    gaps = []
    fame = present_famepilot(feeds, store)
    if fame["has_row"]:
        lines.append(_fame_line(fame))
    else:
        gaps.append(_gap(FAMEPILOT_FILE))
    reelo = present_reelo(feeds, store)
    if reelo["has_row"]:
        lines.append(_reelo_line(reelo))
    else:
        gaps.append(_gap(REELO_FILE))
    return lines, gaps


def _fame_line(fame):
    if fame["no_location"]:
        return (
            "famepilot.csv has a row for this store but no Famepilot location, "
            "so the public rating and main complaint are not on file. "
            + FAMEPILOT_WINDOW
        )
    fields = fame["fields"]
    sentences = []
    rating = fields.get("rating") or ""
    reviews = fields.get("review_count") or ""
    if rating and reviews:
        sentences.append(f"Public rating is {rating} on {reviews} reviews.")
    elif rating:
        sentences.append(f"Public rating is {rating}. Public review count is blank, so the base of that rating is not on file.")
    elif reviews:
        sentences.append(f"Public rating is blank. Public review count is {reviews}.")
    else:
        sentences.append("Public rating and public review count are blank.")
    threat = fields.get("main_threat") or ""
    folded = threat.casefold()
    if folded.startswith("tie:"):
        named = threat.split(":", 1)[1].strip()
        sentences.append(
            f"Main complaint is a tie: {named}. "
            "Do not treat one complaint as the only one. "
            "Check tickets for each complaint in the tie."
        )
    elif folded == "not shown":
        sentences.append("Main complaint is not shown, so there is no named complaint to check.")
    elif threat:
        sentences.append(f"Main complaint is {threat}. Check the last {threat} tickets.")
    else:
        sentences.append("Main complaint is blank, so there is no named complaint to check.")
    private_rating = fields.get("private_rating") or ""
    private_count = fields.get("private_review_count") or ""
    private_number = parse_number(private_count) if private_count else None
    if private_number is not None and private_number > 0:
        if private_rating:
            sentences.append(
                f"Private rating is {private_rating} on {private_count} reviews. "
                "Read those private reviews with the shift lead."
            )
        else:
            sentences.append(
                f"Private review count is {private_count}. Private rating is blank. "
                "Read those private reviews with the shift lead."
            )
    elif private_count:
        extra = f"Private review count is {private_count}."
        if not private_rating:
            extra += " Private rating is blank."
        sentences.append(extra)
    elif private_rating:
        sentences.append(f"Private rating is {private_rating}. Private review count is blank, so do not treat it as zero.")
    sentences.append(FAMEPILOT_WINDOW)
    return " ".join(sentences)


def _reelo_line(reelo):
    if reelo["not_in_reelo"]:
        return (
            "This store is not in Reelo. Redemption and phone capture are not on file, "
            "so no loyalty action is on file."
        )
    fields = reelo["fields"]
    sentences = []
    rate = fields.get("redemption_rate") or ""
    times = fields.get("times_redeemed") or ""
    window = fields.get("reelo_date_range") or ""
    if rate and times:
        sentence = f"Redemption rate is {rate} across {times} redemptions"
    elif rate:
        sentence = "Redemption rate is " + rate + ". Times redeemed is blank, so do not treat it as zero"
    elif times:
        sentence = f"Rewards were redeemed {times} times. Redemption rate is blank, so do not treat it as zero"
    else:
        sentence = ""
    if sentence:
        if window:
            sentence += f" in the file window {window}."
        else:
            sentence += ". The Reelo date range is blank."
        sentences.append(sentence)
    else:
        sentences.append("Redemption rate and times redeemed are blank, so no redemption action is on file.")

    blocked = fields.get("phones_blocked") or ""
    capture = fields.get("phone_capture") or ""
    blocked_number = parse_number(blocked) if blocked else None
    caveat = f" {REELO_PHONE_CAVEAT}" if capture else ""
    if not blocked:
        if capture:
            sentences.append(
                f"Phone capture is {capture}. Blocked visits are blank, so do not treat them as zero.{caveat}"
            )
        else:
            sentences.append("Phone capture and blocked visits are blank, so no phone-capture action is on file.")
    elif blocked_number is None:
        sentences.append(f"Blocked visits are {blocked}, which is not a number, so no blocked-visit count is on file.")
    elif blocked_number == 0:
        capture_bit = f"Phone capture is {capture}. " if capture else "Phone capture is blank, so do not treat it as zero. "
        sentences.append(f"{capture_bit}Blocked visits are {blocked}, so no blocked-visit action is on file.{caveat}")
    else:
        capture_bit = f"Phone capture is {capture}. " if capture else ""
        sentences.append(
            f"{capture_bit}Blocked visits are {blocked}. "
            f"Review why those visits were blocked before the next phone-capture push.{caveat}"
        )
    if (fields.get("reelo_match_status") or "").casefold() == "inferred":
        sentences.append("Match status is inferred, not a confirmed address match.")
    return " ".join(sentences)


def _cost(feeds, store):
    lines = []
    gaps = []
    rows = _posist_rows(feeds, store)
    if rows:
        lines.extend(_posist_cost(rows, posist_window(feeds, store)))
    else:
        gaps.append(_gap(POSIST_FILE))
    calendar_rows = _calendar_rows(feeds, store)
    if calendar_rows:
        lines.append(_calendar_line(calendar_rows))
    else:
        gaps.append(_gap(CALENDAR_FILE))
    return lines, gaps


def _zero_display(text):
    return text in {"0", "₹0", "-₹0"}


def _posist_cost(rows, window):
    lines = []
    fields = window["fields"]
    amount = fields.get("unsettled_amount") or ""
    bills = fields.get("unsettled_bills") or ""
    phrase = _window_phrase(window.get("window_label") or "")
    if not amount and not bills:
        lines.append("Unsettled bills and unsettled amount are blank in posist_daily.csv, so no unsettled-cash action is on file.")
    elif _zero_display(amount) and (not bills or _zero_display(bills)):
        lines.append(f"Unsettled amount {phrase} is {amount}. No unsettled-cash action is on file.")
    elif _zero_display(bills) and not amount:
        lines.append(
            f"Unsettled bills {phrase} are {bills}. Unsettled amount is blank, so do not treat it as zero. "
            "No unsettled-cash action is on file."
        )
    else:
        sentence = "Unsettled"
        if bills and amount:
            sentence = f"Unsettled bills {phrase} are {bills}, totaling {amount}"
        elif bills:
            sentence = f"Unsettled bills {phrase} are {bills}. Unsettled amount is blank, so do not treat it as zero"
        else:
            sentence = f"Unsettled amount {phrase} is {amount}. Unsettled bill count is blank, so do not treat it as zero"
        if not (_zero_display(amount) or _zero_display(bills)):
            sentence += ". Clear those unsettled bills before the next close."
        else:
            sentence += "."
        lines.append(sentence)

    net = fields.get("net") or ""
    gross = fields.get("gross") or ""
    net_move = _newest(rows, "net_wow_pct")
    if net_move is not None:
        lines.append(_net_wow_line(net_move))
    elif not net and gross:
        lines.append(f"Gross {phrase} is {gross}. Net is blank in posist_daily.csv, so no margin action is on file.")
    elif net and not gross:
        lines.append(f"Net {phrase} is {net}. Gross is blank in posist_daily.csv, so no margin action is on file.")
    elif net and gross:
        lines.append(
            f"Net {phrase} is {net}. Gross is {gross}. "
            "The file does not give a cost or margin, so no cost-ratio action is on file."
        )
    elif not net and not gross:
        lines.append("Net and gross are blank in posist_daily.csv, so no margin action is on file.")
    return lines


def _net_wow_line(row):
    day = format_date(row["date"])
    pct = format_pct(row.get("net_wow_pct"))
    net = format_money(row.get("net"), "net") if row.get("net") is not None else ""
    last = format_money(row.get("net_last_same_weekday"), "net_last_same_weekday") if row.get("net_last_same_weekday") is not None else ""
    detail = []
    if net:
        detail.append(f"net {net}")
    if last:
        detail.append(f"{last} on the last same weekday")
    bracket = f" ({'; '.join(detail)})" if detail else ""
    if pct == "0%":
        return f"On {day}, net was unchanged versus the prior week{bracket}. No net-change action is on file."
    return f"On {day}, net moved {pct} versus the prior week{bracket}. Ask the store what changed in that net."


def _calendar_line(rows):
    varied = [row for row in rows if row.get("variance_vs_mid") is not None]
    row = _newest(varied or rows)
    day = format_date(row["date"])
    sentences = []
    if row.get("actual_net") is not None:
        actual = format_money(row.get("actual_net"), "actual_net")
        sentences.append(f"On {day}, sales_pred_vs_actual.csv actual Net is {actual}.")
    else:
        sentences.append(f"On {day}, sales_pred_vs_actual.csv actual Net is blank, so do not treat it as zero.")
    status = row.get("status") or ""
    if status:
        sentences.append(f"Status is {STATUS_LABELS.get(status, str(status))}.")
    driver = row.get("drivers") or ""
    if driver:
        sentences.append(f"The file names {driver} as a driver.")
    if row.get("pred_mid") is not None:
        sentences.append(f"Mid prediction is {format_money(row.get('pred_mid'), 'pred_mid')}.")
    if row.get("variance_vs_mid") is not None:
        sentences.append(f"Variance versus mid is {format_money(row.get('variance_vs_mid'), 'variance_vs_mid')}.")
        if row.get("variance_pct") is not None:
            sentences.append(f"Variance percent is {format_pct(row.get('variance_pct'))}.")
        notes = row.get("notes") or ""
        if notes:
            sentences.append(f"The note says {notes}.")
        if notes and "closed" in notes.casefold():
            sentences.append("Confirm whether that closure is still in effect.")
        elif not notes:
            sentences.append("The file does not name a cause beyond the variance it already prints.")
    else:
        sentences.append("Variance versus mid is blank, so no miss-versus-forecast action is on file.")
    return " ".join(sentences)
