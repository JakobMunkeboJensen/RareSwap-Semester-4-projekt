from __future__ import annotations

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .extensions import db
from .mail import send_email
from .models import User

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="password-reset")


def _make_reset_token(secret_key: str, user: User) -> str:
    return _serializer(secret_key).dumps({"uid": int(user.id), "ph": user.password_hash})


def _verify_reset_token(secret_key: str, token: str, max_age_s: int) -> User | None:
    try:
        data = _serializer(secret_key).loads(token, max_age=max_age_s)
    except SignatureExpired:
        return None
    except BadSignature:
        return None

    if not isinstance(data, dict):
        return None
    uid = data.get("uid")
    ph = data.get("ph")
    if not isinstance(uid, int) or not isinstance(ph, str):
        return None

    user = db.session.get(User, uid)
    if user is None:
        return None
    if user.password_hash != ph:
        return None
    return user


@bp.get("/register")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))
    return render_template("register.html")


@bp.post("/register")
def register_post():
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))

    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""

    if not username or not password:
        flash("Udfyld brugernavn og adgangskode.", "error")
        return redirect(url_for("auth.register"))
    if len(username) < 3:
        flash("Brugernavn skal være mindst 3 tegn.", "error")
        return redirect(url_for("auth.register"))
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        flash("Indtast en gyldig e-mail (eller lad feltet være tomt).", "error")
        return redirect(url_for("auth.register"))
    if len(password) < 6:
        flash("Adgangskode skal være mindst 6 tegn.", "error")
        return redirect(url_for("auth.register"))
    if password != password2:
        flash("Adgangskoderne matcher ikke.", "error")
        return redirect(url_for("auth.register"))

    existing = db.session.execute(db.select(User).where(User.username == username)).scalar_one_or_none()
    if existing is not None:
        flash("Brugernavn er allerede i brug.", "error")
        return redirect(url_for("auth.register"))

    if email:
        existing_email = db.session.execute(db.select(User).where(User.email == email)).scalar_one_or_none()
        if existing_email is not None:
            flash("E-mail er allerede i brug.", "error")
            return redirect(url_for("auth.register"))

    user = User(username=username, email=(email or None))
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    login_user(user)
    flash("Bruger oprettet. Du er nu logget ind.", "success")
    return redirect(url_for("auth.me"))


@bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))
    next_url = request.args.get("next")
    return render_template("login.html", next=next_url)


@bp.post("/login")
def login_post():
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))

    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    next_url = (request.form.get("next") or "").strip()

    user = db.session.execute(db.select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.check_password(password):
        flash("Forkert brugernavn eller adgangskode.", "error")
        return redirect(url_for("auth.login", next=next_url or None))

    login_user(user)
    flash("Du er nu logget ind.", "success")

    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("auth.me"))


@bp.get("/logout")
def logout():
    if current_user.is_authenticated:
        logout_user()
    flash("Du er nu logget ud.", "success")
    return redirect(url_for("pricing.home"))


@bp.get("/me")
@login_required
def me():
    return render_template("me.html", username=current_user.username, email=current_user.email)


@bp.get("/forgot-password")
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))
    return render_template("forgot_password.html")


@bp.post("/forgot-password")
def forgot_password_post():
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))

    email = (request.form.get("email") or "").strip()
    if not email:
        flash("Indtast din e-mail.", "error")
        return redirect(url_for("auth.forgot_password"))

    user = db.session.execute(db.select(User).where(User.email == email)).scalar_one_or_none()
    if user is not None and user.email:
        from flask import current_app

        token = _make_reset_token(current_app.config["SECRET_KEY"], user)
        link = url_for("auth.reset_password", token=token, _external=True)
        body = (
            "Du har bedt om at nulstille din adgangskode.\n\n"
            f"Åbn dette link for at vælge en ny adgangskode:\n{link}\n\n"
            "Hvis du ikke bad om dette, kan du ignorere denne mail."
        )
        try:
            send_email(user.email, "Nulstil adgangskode", body)
        except Exception:
            logger.exception("Failed to send password reset email")

    flash("Hvis e-mailen findes, har vi sendt et reset-link.", "success")
    return redirect(url_for("auth.login"))


@bp.get("/reset/<token>")
def reset_password(token: str):
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))

    from flask import current_app

    user = _verify_reset_token(
        current_app.config["SECRET_KEY"],
        token=token,
        max_age_s=int(current_app.config["RESET_TOKEN_MAX_AGE_S"]),
    )
    if user is None:
        flash("Reset-linket er ugyldigt eller udløbet.", "error")
        return redirect(url_for("auth.forgot_password"))
    return render_template("reset_password.html", token=token)


@bp.post("/reset/<token>")
def reset_password_post(token: str):
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))

    from flask import current_app

    user = _verify_reset_token(
        current_app.config["SECRET_KEY"],
        token=token,
        max_age_s=int(current_app.config["RESET_TOKEN_MAX_AGE_S"]),
    )
    if user is None:
        flash("Reset-linket er ugyldigt eller udløbet.", "error")
        return redirect(url_for("auth.forgot_password"))

    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""
    if len(password) < 6:
        flash("Adgangskode skal være mindst 6 tegn.", "error")
        return redirect(url_for("auth.reset_password", token=token))
    if password != password2:
        flash("Adgangskoderne matcher ikke.", "error")
        return redirect(url_for("auth.reset_password", token=token))

    user.set_password(password)
    db.session.commit()
    flash("Adgangskode opdateret. Du kan nu logge ind.", "success")
    return redirect(url_for("auth.login"))

