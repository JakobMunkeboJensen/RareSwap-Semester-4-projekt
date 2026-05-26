"""SQLAlchemy ORM-modeller for prishistorik."""

from __future__ import annotations

from datetime import datetime

from .extensions import db


class PriceHistory(db.Model):
    """Snapshot af et korts markedspris på et givet tidspunkt."""

    id = db.Column(db.Integer, primary_key=True)
    card_name = db.Column(db.String(200), nullable=False, index=True)
    card_set = db.Column(db.String(200), nullable=False, default="")
    market_usd = db.Column(db.Float, nullable=True)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
