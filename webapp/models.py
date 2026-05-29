"""SQLAlchemy ORM-modeller for prishistorik og brugere."""

from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class PriceHistory(db.Model):
    """Snapshot af et korts markedspris på et givet tidspunkt."""

    id = db.Column(db.Integer, primary_key=True)
    card_name = db.Column(db.String(200), nullable=False, index=True)
    card_set = db.Column(db.String(200), nullable=False, default="")
    market_usd = db.Column(db.Float, nullable=True)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class User(UserMixin, db.Model):
    """Brugerkonto med adgangskode-hash."""

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(200), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
