"""SMTP e-mail-hjælper til adgangskode-nulstilling og prisalarmer."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, body: str) -> None:
    """Send en e-mail i klartekst; logger og returnerer tidligt hvis SMTP ikke er konfigureret."""
    app = current_app
    host = str(app.config.get("SMTP_HOST") or "").strip()
    port = int(app.config.get("SMTP_PORT") or 587)
    user = str(app.config.get("SMTP_USER") or "").strip()
    password = str(app.config.get("SMTP_PASSWORD") or "")
    use_tls = bool(app.config.get("SMTP_TLS"))
    mail_from = str(app.config.get("MAIL_FROM") or "noreply@localhost").strip()

    if not host:
        logger.warning("SMTP not configured. Would send to %s:\nSubject: %s\n\n%s", to_email, subject, body)
        return

    msg = EmailMessage()
    msg["From"] = mail_from
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=10) as s:
        if use_tls:
            s.starttls()
        if user:
            s.login(user, password)
        s.send_message(msg)

