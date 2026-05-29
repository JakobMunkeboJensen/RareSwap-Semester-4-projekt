"""Flask-applikationsfabrik for RareSwap."""

from __future__ import annotations

import logging
import os

from flask import Flask, jsonify, render_template, request

from .extensions import csrf, db, login_manager
from .pricing import bp as pricing_bp
from .auth import bp as auth_bp

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

    db.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Log ind for at fortsætte."
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        from .models import User
        return db.session.get(User, int(user_id))

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

    with app.app_context():
        db.create_all()

    return app
