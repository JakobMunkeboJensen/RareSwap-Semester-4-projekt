from __future__ import annotations

import logging

from flask import Flask
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

logger = logging.getLogger(__name__)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


def ensure_sqlite_user_email_column(app: Flask) -> None:
    """
    Minimal migration for existing SQLite DB.
    If the 'email' column is missing, we add it (nullable).
    """
    try:
        uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
        if not uri.startswith("sqlite:///"):
            return
        cols = db.session.execute(db.text("PRAGMA table_info(user)")).all()
        have_email = any((c[1] == "email") for c in cols) if cols else False
        if not have_email:
            db.session.execute(db.text("ALTER TABLE user ADD COLUMN email VARCHAR(255)"))
            db.session.commit()
    except Exception:
        logger.exception("Could not ensure SQLite columns")

