"""Versioned menus. A new upload inserts a version. It does not replace an old one."""

from datetime import datetime

from app.extensions import db


class MenuVersion(db.Model):
    __tablename__ = "menu_version"

    id = db.Column(db.Integer, primary_key=True)
    city = db.Column(db.String(80), nullable=False)
    channel = db.Column(db.String(40), nullable=False)
    store_scope = db.Column(db.String(120), nullable=False, default="All stores")
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date, nullable=True)
    source = db.Column(db.String(255), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    prices = db.relationship(
        "MenuItemPrice",
        backref="version",
        cascade="all, delete-orphan",
        lazy="select",
    )


class MenuItemPrice(db.Model):
    __tablename__ = "menu_item_price"

    id = db.Column(db.Integer, primary_key=True)
    version_id = db.Column(db.Integer, db.ForeignKey("menu_version.id"), nullable=False, index=True)
    item = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(120), nullable=False, default="")
    price = db.Column(db.Float, nullable=True)
