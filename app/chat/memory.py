"""Ratings and unanswered questions.

Rows live in Postgres in production and in the local database in tests.
The table is created if it is missing. Keys and the model prompt are never stored.
"""

import logging
from datetime import datetime, timedelta

from app.extensions import db

log = logging.getLogger(__name__)

_FINANCE = {"owner", "finance"}
_PEOPLE = {"owner", "hr"}


class ChatFeedback(db.Model):
    """One asked question, with an optional thumbs rating."""

    __tablename__ = "chat_feedback"

    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    topic = db.Column(db.String(40), nullable=False, default="")
    data_as_of = db.Column(db.String(40), nullable=False, default="")
    rating = db.Column(db.String(8), nullable=True)
    note = db.Column(db.String(160), nullable=True)
    role = db.Column(db.String(16), nullable=False, default="ops")
    source = db.Column(db.String(8), nullable=False, default="person")
    actor = db.Column(db.String(40), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ChatGap(db.Model):
    """A question the chat could not answer from the loaded data."""

    __tablename__ = "chat_gap"

    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    topic = db.Column(db.String(40), nullable=False, default="")
    reason = db.Column(db.String(24), nullable=False)
    data_as_of = db.Column(db.String(40), nullable=False, default="")
    role = db.Column(db.String(16), nullable=False, default="ops")
    source = db.Column(db.String(8), nullable=False, default="person")
    actor = db.Column(db.String(40), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


def ensure_chat_tables():
    """Create the learning tables when an older database does not have them yet."""
    ChatFeedback.__table__.create(db.engine, checkfirst=True)
    ChatGap.__table__.create(db.engine, checkfirst=True)


def gap_reason(text):
    """Why an answer did not have the figure. Empty when the answer is usable."""
    folded = (text or "").casefold()
    if "only on the owner" in folded:
        return "refusal"
    if (
        "isn't loaded" in folded
        or "aren't loaded" in folded
        or "is not loaded" in folded
        or "no forecast comparison is loaded" in folded
        or "no week-on-week" in folded
    ):
        return "stale"
    if (
        "isn't available" in folded
        or "isn't in the loaded" in folded
        or "aren't in the loaded" in folded
        or "no action is backed" in folded
    ):
        return "no_data"
    return ""


def _clip(text, limit):
    return " ".join(str(text or "").split())[:limit]


def _safe(source, role, actor):
    source = "bot" if str(source or "") == "bot" else "person"
    role = str(role or "ops").strip().lower()[:16] or "ops"
    actor = _clip(actor, 40) if source == "bot" else ""
    return source, role, actor


def record_ask(question, topic, data_as_of, role, source, actor):
    """Remember that this question was asked. Returns the row id, or None."""
    question = _clip(question, 500)
    if not question:
        return None
    source, role, actor = _safe(source, role, actor)
    try:
        row = ChatFeedback(
            question=question,
            topic=_clip(topic, 40),
            data_as_of=_clip(data_as_of, 40),
            role=role,
            source=source,
            actor=actor,
            created_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        log.info(
            "chat ask source=%s role=%s topic=%s question_chars=%s",
            source,
            role,
            row.topic,
            len(question),
        )
        return row.id
    except Exception:
        db.session.rollback()
        log.info("chat ask status=skipped")
        return None


def record_rating(ask_id, question, topic, data_as_of, rating, note, role, source, actor):
    """Store a thumbs rating. A note is kept only for thumbs down."""
    rating = str(rating or "").strip().lower()
    if rating not in {"up", "down"}:
        return None
    source, role, actor = _safe(source, role, actor)
    kept_note = _clip(note, 160) if rating == "down" else ""
    try:
        row = None
        if ask_id:
            row = ChatFeedback.query.filter_by(id=int(ask_id)).first()
        if row is None:
            question = _clip(question, 500)
            if not question:
                return None
            row = ChatFeedback(
                question=question,
                topic=_clip(topic, 40),
                data_as_of=_clip(data_as_of, 40),
                role=role,
                source=source,
                actor=actor,
                created_at=datetime.utcnow(),
            )
            db.session.add(row)
        row.rating = rating
        row.note = kept_note or None
        db.session.commit()
        log.info(
            "chat feedback source=%s role=%s rating=%s question_chars=%s",
            row.source,
            row.role,
            rating,
            len(row.question or ""),
        )
        return row.id
    except Exception:
        db.session.rollback()
        log.info("chat feedback status=skipped")
        return None


def record_gap(question, topic, text, data_as_of, role, source, actor):
    """Store a question the loaded files could not answer."""
    reason = gap_reason(text)
    question = _clip(question, 500)
    if not reason or not question:
        return None
    source, role, actor = _safe(source, role, actor)
    try:
        row = ChatGap(
            question=question,
            topic=_clip(topic, 40),
            reason=reason,
            data_as_of=_clip(data_as_of, 40),
            role=role,
            source=source,
            actor=actor,
            created_at=datetime.utcnow(),
        )
        db.session.add(row)
        db.session.commit()
        log.info("chat gap source=%s role=%s reason=%s question_chars=%s", source, role, reason, len(question))
        return row.id
    except Exception:
        db.session.rollback()
        log.info("chat gap status=skipped")
        return None


def _allowed(topic, role):
    topic = (topic or "").strip().lower()
    if topic == "finance":
        return role in _FINANCE
    if topic in {"people", "hr"}:
        return role in _PEOPLE
    return True


def learned_questions(role, days=30, minimum=3, limit=2):
    """Questions asked often and rated up more than down, for this role."""
    try:
        from flask import has_app_context
        if not has_app_context():
            return []
        since = datetime.utcnow() - timedelta(days=days)
        rows = ChatFeedback.query.filter(ChatFeedback.created_at >= since).all()
    except Exception:
        return []
    grouped = {}
    for row in rows:
        key = (row.question or "").strip().casefold()
        if not key:
            continue
        bucket = grouped.setdefault(key, {
            "question": (row.question or "").strip(),
            "topic": row.topic or "",
            "n": 0,
            "up": 0,
            "down": 0,
        })
        bucket["n"] += 1
        if row.rating == "up":
            bucket["up"] += 1
        elif row.rating == "down":
            bucket["down"] += 1
        if row.topic:
            bucket["topic"] = row.topic
    ranked = [
        bucket for bucket in grouped.values()
        if bucket["n"] >= minimum and bucket["up"] > bucket["down"] and _allowed(bucket["topic"], role)
    ]
    ranked.sort(key=lambda bucket: (bucket["up"] - bucket["down"], bucket["n"]), reverse=True)
    return [bucket["question"] for bucket in ranked[:limit]]


def _public_row(row):
    return {
        "question": row.question,
        "topic": row.topic,
        "note": row.note or "",
        "role": row.role,
        "source": row.source,
        "actor": row.actor,
        "data_as_of": row.data_as_of,
        "at": row.created_at.isoformat(timespec="minutes") if row.created_at else "",
    }


def window_summary(days):
    """Counts and lists for the insights page and the review API."""
    days = max(1, min(int(days or 7), 90))
    since = datetime.utcnow() - timedelta(days=days)
    feedback = (
        ChatFeedback.query.filter(ChatFeedback.created_at >= since)
        .order_by(ChatFeedback.created_at.desc())
        .all()
    )
    gaps = (
        ChatGap.query.filter(ChatGap.created_at >= since)
        .order_by(ChatGap.created_at.desc())
        .all()
    )
    grouped = {}
    ups = downs = 0
    for row in feedback:
        if row.rating == "up":
            ups += 1
        elif row.rating == "down":
            downs += 1
        key = (row.question or "").strip().casefold()
        bucket = grouped.setdefault(key, {"question": (row.question or "").strip(), "count": 0, "up": 0, "down": 0})
        bucket["count"] += 1
        if row.rating == "up":
            bucket["up"] += 1
        elif row.rating == "down":
            bucket["down"] += 1
    most = sorted(grouped.values(), key=lambda bucket: bucket["count"], reverse=True)[:8]
    reasons = {"no_data": "No matching data", "stale": "Stale source", "refusal": "Refused"}
    return {
        "days": days,
        "counts": {
            "questions": len(feedback),
            "up": ups,
            "down": downs,
            "gaps": len(gaps),
        },
        "most_asked": most,
        "thumbs_down": [_public_row(row) for row in feedback if row.rating == "down"][:20],
        "gaps": [
            {
                "question": row.question,
                "reason": reasons.get(row.reason, row.reason),
                "topic": row.topic,
                "source": row.source,
                "actor": row.actor,
                "at": row.created_at.isoformat(timespec="minutes") if row.created_at else "",
            }
            for row in gaps[:20]
        ],
    }
