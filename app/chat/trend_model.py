"""Cached sales trends. Rebuilt when the chat home or a trend question loads."""

from datetime import datetime

from app.extensions import db


class ChatTrend(db.Model):
    __tablename__ = "chat_trend"

    id = db.Column(db.Integer, primary_key=True)
    store = db.Column(db.String(120), nullable=False, default="")
    impact = db.Column(db.Float, nullable=True)
    direction = db.Column(db.String(8), nullable=False, default="")
    detail = db.Column(db.String(240), nullable=False, default="")
    computed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
