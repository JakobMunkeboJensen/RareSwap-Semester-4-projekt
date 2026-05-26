"""Delte Flask-udvidelsesinstanser (db, csrf)."""

from __future__ import annotations

from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
csrf = CSRFProtect()

