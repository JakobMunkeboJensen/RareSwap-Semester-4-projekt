"""Flask-applikationsfabrik for RareSwap."""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, render_template, request

from .alerts import bp as alerts_bp
from .auth import bp as auth_bp
from .extensions import db, login_manager
from .models import User, ensure_sqlite_user_email_column
from .pricing import bp as pricing_bp

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """Opret og konfigurer Flask-applikationen."""
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, "templates"),
        static_folder=os.path.join(base_dir, "static"),
    )

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    db_path = os.path.join(base_dir, "app.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", f"sqlite:///{db_path}")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["RESET_TOKEN_MAX_AGE_S"] = int(os.getenv("RESET_TOKEN_MAX_AGE_S", "3600"))
    app.config["MAIL_FROM"] = os.getenv("MAIL_FROM", "noreply@localhost")
    app.config["SMTP_HOST"] = os.getenv("SMTP_HOST", "")
    app.config["SMTP_PORT"] = int(os.getenv("SMTP_PORT", "587"))
    app.config["SMTP_USER"] = os.getenv("SMTP_USER", "")
    app.config["SMTP_PASSWORD"] = os.getenv("SMTP_PASSWORD", "")
    app.config["SMTP_TLS"] = os.getenv("SMTP_TLS", "1") not in {"0", "false", "False"}

    db.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        """Genindlæs brugerobjektet fra sessions-bruger-ID."""
        try:
            uid = int(user_id)
        except ValueError:
            return None
        return db.session.get(User, uid)

    @app.errorhandler(429)
    def too_many_requests(_e):
        """Returner 429-svar for JSON API-stier eller en HTML-statusside."""
        msg = "For mange forespørgsler. Prøv igen om lidt."
        retry_after = int(os.getenv("RATE_LIMIT_WINDOW_S", "60"))
        if request.path.startswith("/api/"):
            return jsonify({"error": msg}), 429, {"Retry-After": str(retry_after)}
        return (
            render_template(
                "status.html",
                title="Rate limit",
                items=[
                    {"label": "Status", "value": "429 Too Many Requests", "ok": False},
                    {"label": "Besked", "value": msg, "ok": False},
                ],
                pokemontcg_ok=None,
                fx_ok=None,
            ),
            429,
            {"Retry-After": str(retry_after)},
        )

    app.register_blueprint(pricing_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(alerts_bp)

    with app.app_context():
        db.create_all()
        ensure_sqlite_user_email_column(app)

    return app

