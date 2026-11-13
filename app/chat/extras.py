"""Files, share links, Chief of Staff, inbox ingest, and saved notes."""

import hmac
import html
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from app.extensions import db

_TAG = re.compile(r"<[^>]+>")
_RESTRICTED = ("grand economics", "ebitda", "keka", "headcount", "inbox", "important email", "red flag", "abscond")


class ChatSnapshot(db.Model):
    __tablename__ = "chat_snapshot"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(48), nullable=False, unique=True)
    question = db.Column(db.Text, nullable=False, default="")
    answer = db.Column(db.Text, nullable=False, default="")
    as_of = db.Column(db.String(40), nullable=False, default="")
    audience = db.Column(db.String(16), nullable=False, default="ops")
    restricted = db.Column(db.Boolean, nullable=False, default=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.String(120), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ChatShareEvent(db.Model):
    __tablename__ = "chat_share_event"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(48), nullable=False, default="")
    event = db.Column(db.String(16), nullable=False)
    actor = db.Column(db.String(120), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ChiefRequest(db.Model):
    __tablename__ = "chief_request"

    id = db.Column(db.String(36), primary_key=True)
    asked_by = db.Column(db.String(120), nullable=False, default="")
    request = db.Column(db.Text, nullable=False, default="")
    excerpt = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(32), nullable=False, default="waiting for approval")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ChatIngest(db.Model):
    __tablename__ = "chat_ingest"

    id = db.Column(db.Integer, primary_key=True)
    feed = db.Column(db.String(24), nullable=False, default="inbox")
    payload = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ChatNote(db.Model):
    __tablename__ = "chat_note"

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False, default="")
    author = db.Column(db.String(120), nullable=False, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


def strip_html(value):
    if isinstance(value, str):
        return _TAG.sub("", html.unescape(value))
    if isinstance(value, list):
        return [strip_html(item) for item in value]
    if isinstance(value, dict):
        return {key: strip_html(item) for key, item in value.items()}
    return value


def ingest_status(header):
    expected = os.environ.get("CHAT_INGEST_KEY") or os.environ.get("CHAT_INGEST_TOKEN") or ""
    expected = expected.strip()
    if not expected:
        return "unset"
    token = str(header or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return "bad"
    try:
        ok = hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))
    except Exception:
        return "bad"
    return "ok" if ok else "bad"


def is_restricted(question):
    folded = (question or "").casefold()
    return any(token in folded for token in _RESTRICTED)


def save_snapshot(question, answer, as_of, days, public, email):
    restricted = is_restricted(question)
    if restricted:
        public = False
    audience = "public" if public else ("owner" if restricted else "ops")
    row = ChatSnapshot(
        token=secrets.token_urlsafe(18),
        question=(question or "")[:500],
        answer=answer or "",
        as_of=as_of or "",
        audience=audience,
        restricted=restricted,
        expires_at=datetime.utcnow() + timedelta(days=days),
        created_by=email or "",
    )
    db.session.add(row)
    db.session.add(ChatShareEvent(token=row.token, event="create", actor=email or ""))
    db.session.commit()
    return row


def workbook_bytes(title, columns, rows, notes):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.active
    sheet.title = "Data"
    sheet.append(columns or ["Value"])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows or []:
        sheet.append(list(row))
    for column in sheet.columns:
        sheet.column_dimensions[get_column_letter(column[0].column)].width = 22
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    notes_sheet = book.create_sheet("Notes")
    notes_sheet.append(["Note"])
    for line in (notes or ["Figures are copied from the answer. They are not recalculated."]):
        notes_sheet.append([line])
    handle = BytesIO()
    book.save(handle)
    return handle.getvalue()


def pdf_bytes(title, lines):
    from fpdf import FPDF

    font = Path(__file__).resolve().parents[1] / "store_health" / "fonts" / "DejaVuSans.ttf"
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("DejaVu", "", str(font))
    pdf.set_font("DejaVu", size=14)
    pdf.multi_cell(0, 8, title or "Dosa Coffee Wizard")
    pdf.set_font("DejaVu", size=10)
    pdf.ln(2)
    for line in lines or []:
        pdf.multi_cell(0, 6, str(line))
        pdf.ln(1)
    return bytes(pdf.output())


def png_bytes(title, series):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.text((16, 12), title or "Chart", fill=(20, 20, 20))
    values = [float(item.get("value") or 0) for item in series or []]
    labels = [str(item.get("label") or "")[:18] for item in series or []]
    peak = max(values) if values else 1
    if peak == 0:
        peak = 1
    left = 140
    width = 520
    for index, value in enumerate(values[:8]):
        y = 50 + index * 36
        bar = int(abs(value) / peak * width)
        draw.rectangle((left, y, left + max(bar, 2), y + 18), fill=(122, 78, 13))
        draw.text((8, y), labels[index], fill=(20, 20, 20))
        draw.text((left + bar + 8, y), str(round(value, 2)), fill=(20, 20, 20))
    handle = BytesIO()
    image.save(handle, format="PNG")
    return handle.getvalue()


def webhook_connected():
    return bool(os.environ.get("WIZARD_WEBHOOK_URL", "").strip() and os.environ.get("WIZARD_WEBHOOK_KEY", "").strip())


def send_to_chief(request_text, excerpt, email):
    """Store the request. Call the webhook only from this function, after a click."""
    row = ChiefRequest(
        id=str(uuid.uuid4()),
        asked_by=email or "",
        request=(request_text or "")[:500],
        excerpt=(excerpt or "")[:800],
        status="waiting for approval",
    )
    if not webhook_connected():
        row.status = "not_connected"
        db.session.add(row)
        db.session.commit()
        return row
    import urllib.request

    url = os.environ.get("WIZARD_WEBHOOK_URL", "").strip()
    key = os.environ.get("WIZARD_WEBHOOK_KEY", "").strip()
    header = os.environ.get("WIZARD_WEBHOOK_KEY_HEADER", "").strip() or "X-Webhook-Key"
    body = {
        "request_id": row.id,
        "asked_by": row.asked_by,
        "asked_at": datetime.utcnow().isoformat() + "Z",
        "request": row.request,
        "answer_excerpt": row.excerpt,
        "status_url": "/api/chat/cos/" + row.id + "/status",
    }
    call = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={header: key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(call, timeout=15) as response:
            response.read()
        row.status = "sent"
    except Exception:
        row.status = "failed"
    db.session.add(row)
    db.session.commit()
    return row


def latest_inbox():
    cutoff = datetime.utcnow() - timedelta(days=14)
    try:
        row = (
            ChatIngest.query.filter_by(feed="inbox")
            .filter(ChatIngest.created_at >= cutoff)
            .order_by(ChatIngest.created_at.desc())
            .first()
        )
    except Exception:
        row = None
    if row and row.payload:
        try:
            return json.loads(row.payload)
        except json.JSONDecodeError:
            return None
    path = Path(__file__).resolve().parents[2] / "data" / "chat" / "inbox_digest.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def save_note(body, author):
    text = (body or "").strip()
    if not text:
        return None
    row = ChatNote(body=text[:500], author=author or "")
    db.session.add(row)
    db.session.commit()
    return row


def what_if_text(question):
    """Reprice one item from recipe cost and menu gross. Elasticity stays none unless stated."""
    import re

    from app.chat.menu_hr import newest_menu

    match = re.search(r"₹\s*(\d+(?:\.\d+)?)", question or "")
    if not match:
        return "Name the rupee change. No new price was assumed. Volume elasticity is none."
    delta = float(match.group(1))
    folded = (question or "").casefold()
    elasticity = "none"
    volume = re.search(r"volume[^0-9]{0,12}(\d+(?:\.\d+)?)\s*%", folded)
    if volume:
        elasticity = volume.group(1) + "% drop" if "drop" in folded or "down" in folded else volume.group(1) + "%"
    picked = newest_menu()
    price = None
    item = ""
    period = ""
    if picked:
        _path, rows = picked
        words = [word for word in re.findall(r"[a-z]{4,}", folded) if word not in {"raise", "what", "price", "dosa", "coffee"}]
        for row in rows:
            name = (row.get("item") or "").casefold()
            if words and not all(word in name for word in words[:2]):
                continue
            gross = row.get("gross") or row.get("total_sales")
            qty = row.get("qty") or row.get("total_orders")
            try:
                gross_n = float(str(gross).replace(",", ""))
                qty_n = float(str(qty).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if qty_n:
                price = gross_n / qty_n
                item = row.get("item") or ""
                period = f"{row.get('date_from') or row.get('period_start') or ''} to {row.get('date_to') or row.get('period_end') or ''}"
                break
    if price is None:
        return "No selling price was found for that item, so the new food-cost percent is not stated. Volume elasticity is " + elasticity + "."
    new_price = price + delta
    return (
        f"{item or 'Item'} current price {_inr_plain(price)} of gross ({period}). "
        f"After ₹{delta:.0f}, price is {_inr_plain(new_price)}. "
        "Net is blank on the menu file, so this is gross. "
        "The 24.78% aggregator rule applies only if this is a Swiggy or Zomato net bill, not dine-in. "
        f"Volume elasticity is {elasticity}. No volume change was assumed."
    )


def _inr_plain(value):
    return f"₹{float(value):.2f}"


def inbox_text(role):
    if role != "owner":
        return "Inbox: not included for this role."
    digest = latest_inbox()
    if not digest:
        return "No inbox digest is loaded. Full email bodies are not stored."
    lines = ["Inbox digest. Full email bodies are not stored."]
    for item in (digest.get("items") or [])[:8]:
        lines.append(
            f"{item.get('urgency') or ''} {item.get('date') or ''} {item.get('subject') or ''}: {item.get('summary') or ''}"
        )
    return "\n".join(lines)


def active_notes():
    try:
        return ChatNote.query.filter_by(active=True).order_by(ChatNote.created_at.desc()).limit(20).all()
    except Exception:
        return []
