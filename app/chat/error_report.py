"""A reporter flags a Wizard answer. Mail uses the app's SMTP settings.

Nothing here stores a password. If MAIL_SERVER or MAIL_USERNAME is missing,
the report is still written to the local log and the caller is told to try again.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parents[2]
_LOG = _ROOT / "data" / "chat" / "error_reports.jsonl"
_TO = "siddhant@dalgreenfoods.com"
_AREAS = ("Sales", "Forecast", "Reviews", "Procurement", "Marketing", "Reelo", "Other")
_SENSITIVE = (
    "ebitda", "rent", "salary", "inbox", "tally", "bank payment", "headcount",
    "grand economics", "p&l", "profit",
)
_IST = ZoneInfo("Asia/Kolkata")


def _clean(value):
    text = " ".join(str(value or "").split())
    return text or "Unknown"


def _area(value):
    text = _clean(value)
    for name in _AREAS:
        if text.casefold() == name.casefold():
            return name
    return "Other" if text == "Unknown" else "Other"


def subject_line(area, place, dates, metric, value):
    """Fixed subject a machine can parse. No field is left blank."""
    return (
        f"[Wizard error] {_area(area)} | {_clean(place)} | {_clean(dates)} | "
        f"{_clean(metric)}: {_clean(value)}"
    )


_AREA_WORDS = (
    ("Marketing", ("marketing", "campaign", "ads")),
    ("Reelo", ("reelo", "repeat", "enrol")),
    ("Procurement", ("procurement", "purchase", "wastage", "vendor")),
    ("Reviews", ("famepilot", "ticket", "review", "complaint", "audit")),
    ("Forecast", ("forecast", "predict", "pace")),
    ("Sales", ("sales", "gross", "bill", "transaction", "apc", "target", "delivery")),
)
_PLACES = (
    "Ideal Plaza", "Connaught Place", "Sec 18 Noida", "Sec 143 Noida",
    "Gurgaon Sec-15", "Pacific Mall, Jasola", "Salt Lake", "New Town Cloud Kitchen",
)


def _infer_area(text):
    folded = (text or "").casefold()
    for name, words in _AREA_WORDS:
        if any(word in folded for word in words):
            return name
    return ""


def _infer_place(text):
    folded = (text or "").casefold()
    for name in _PLACES:
        if name.casefold() in folded:
            return name
    if any(word in folded for word in ("ncr", "delhi", "north")):
        return "NCR"
    if any(word in folded for word in ("kolkata", "east")):
        return "Kolkata"
    if "network" in folded:
        return "Network"
    return ""


def _opening(answer):
    """The first claim that carries a figure. Later table rows are not the subject."""
    text = re.sub(r"[|#*]", " ", answer or "")
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=\.)\s+", text)
    for part in parts:
        folded = part.casefold()
        if "₹" in part or any(word in folded for word in ("ncr", "network", "kolkata", "sales")):
            return part
    return parts[0] if parts else ""


def _dates_in(text, as_of):
    match = re.search(
        r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?:\s+(20\d{2}))?",
        text or "",
    )
    if match:
        year = match.group(4) or "2026"
        return f"{int(match.group(1))} {match.group(3)}–{int(match.group(2))} {match.group(3)} {year}"
    return _clean(as_of) if as_of else ""


def _metric_in(text):
    money = re.search(r"(₹[\d,.]+\s*(?:Cr|L)?)", text or "")
    if not money:
        return "", ""
    window = (text or "")[max(0, money.start() - 48):money.start()].casefold()
    if "net" in window:
        metric = "Net sales"
    elif "gross" in window:
        metric = "Gross"
    elif "bill" in window:
        metric = "Bills"
    elif "sales" in window:
        metric = "Sales"
    else:
        metric = "Figure"
    return metric, money.group(1).strip()


def prefill(question, answer, as_of="", topic=""):
    """Best guess from the question and the lead of the answer. The reporter can change it."""
    lead = _opening(answer)
    area = _infer_area(question) or _infer_area(topic) or _infer_area(lead) or "Other"
    place = _infer_place(question) or _infer_place(lead) or "Network"
    dates = _dates_in(f"{question or ''} {lead}", as_of) or "Unknown"
    metric, value = _metric_in(lead)
    if not value:
        metric, value = _metric_in(answer or "")
    return {
        "area": area,
        "place": place,
        "dates": dates,
        "metric": metric or "Figure",
        "value": value or "Unknown",
    }


def _sensitive(text):
    folded = (text or "").casefold()
    return any(token in folded for token in _SENSITIVE)


def redact_transcript(turns, owner):
    """Finance, HR and inbox lines stay in only for an owner reporter."""
    cleaned = []
    for turn in turns or []:
        role = "You" if str(turn.get("role") or "").casefold() in {"user", "you"} else "Wizard"
        text = str(turn.get("text") or "")
        if not owner and _sensitive(text):
            text = "[redacted]"
        cleaned.append({"role": role, "text": text})
    return cleaned


def render_body(fields, note, correction, answer, email, page, when, turns):
    lines = [
        f"Area: {fields['area']}",
        f"Store or Network/City: {fields['place']}",
        f"Date range: {fields['dates']}",
        f"Metric: {fields['metric']}",
        f"Disputed value: {fields['value']}",
        "",
        "What looks wrong:",
        note or "Unknown",
        "",
        "What should it be:",
        correction or "Not given",
        "",
        "Flagged answer:",
        answer or "Unknown",
        "",
        f"Reported by: {email or 'Unknown'}",
        f"Time: {when}",
        f"Page: {page or 'Unknown'}",
        "",
        "Transcript:",
    ]
    for turn in turns:
        lines.append(f"{turn['role']}: {turn['text']}")
    return "\n".join(lines)


def transcript_html(turns):
    parts = ["<html><body><h1>Wizard transcript</h1><ol>"]
    for turn in turns:
        role = turn["role"]
        text = (turn["text"] or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(f"<li><strong>{role}.</strong> {text}</li>")
    parts.append("</ol></body></html>")
    return "".join(parts)


def mail_configured():
    import os
    return bool(os.getenv("MAIL_SERVER", "").strip() and os.getenv("MAIL_USERNAME", "").strip())


def save_log(record):
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def submit_report(payload, email, owner, mailer=None):
    """Save the report, then send it. Mailer is injectable for tests."""
    fields = {
        "area": _area(payload.get("area")),
        "place": _clean(payload.get("place")),
        "dates": _clean(payload.get("dates")),
        "metric": _clean(payload.get("metric")),
        "value": _clean(payload.get("value")),
    }
    note = " ".join(str(payload.get("note") or "").split())
    if not note:
        return {"ok": False, "error": "Say what looks wrong."}
    when = datetime.now(_IST).strftime("%d %b %Y, %I:%M %p IST").lstrip("0")
    turns = redact_transcript(payload.get("turns") or [], owner)
    subject = subject_line(fields["area"], fields["place"], fields["dates"], fields["metric"], fields["value"])
    body = render_body(
        fields, note, str(payload.get("correction") or "").strip(),
        str(payload.get("answer") or ""), email, str(payload.get("page") or ""), when, turns,
    )
    record = {"subject": subject, "body": body, "email": email, "when": when, "owner": bool(owner)}
    save_log(record)
    if not mail_configured() and mailer is None:
        return {"ok": False, "error": "Couldn't send, try again", "saved": True, "subject": subject}
    if mailer is not None:
        mailer(subject, body, turns)
        return {"ok": True, "subject": subject}
    from flask_mail import Message
    from app.mail import mail

    message = Message(subject=subject, recipients=[_TO], body=body)
    plain = "\n".join(f"{turn['role']}: {turn['text']}" for turn in turns)
    message.attach("wizard-transcript.txt", "text/plain", plain)
    message.attach("wizard-transcript.html", "text/html", transcript_html(turns))
    mail.send(message)
    return {"ok": True, "subject": subject}
