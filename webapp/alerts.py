from __future__ import annotations

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .models import PriceAlert

logger = logging.getLogger(__name__)

bp = Blueprint("alerts", __name__)


@bp.get("/alerts")
@login_required
def list_alerts():
    alerts = db.session.execute(
        db.select(PriceAlert)
        .where(PriceAlert.user_id == current_user.id, PriceAlert.is_active == True)
        .order_by(PriceAlert.created_at.desc())
    ).scalars().all()
    return render_template("alerts.html", alerts=alerts)


@bp.post("/alerts/create")
@login_required
def create_alert():
    card_name = (request.form.get("card_name") or "").strip()
    card_set = (request.form.get("card_set") or "").strip()
    threshold_str = (request.form.get("threshold_usd") or "").strip()

    if not card_name:
        flash("Mangler kortnavn.", "error")
        return redirect(request.referrer or url_for("alerts.list_alerts"))

    try:
        threshold = float(threshold_str)
        if threshold <= 0:
            raise ValueError
    except ValueError:
        flash("Indtast en gyldig pris-grænse (USD).", "error")
        return redirect(request.referrer or url_for("alerts.list_alerts"))

    existing = db.session.execute(
        db.select(PriceAlert).where(
            PriceAlert.user_id == current_user.id,
            PriceAlert.card_name == card_name,
            PriceAlert.card_set == card_set,
            PriceAlert.is_active == True,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.threshold_usd = threshold
        db.session.commit()
        flash(f"Alarm for {card_name} opdateret til ${threshold:.2f} USD.", "success")
    else:
        alert = PriceAlert(
            user_id=current_user.id,
            card_name=card_name,
            card_set=card_set,
            threshold_usd=threshold,
        )
        db.session.add(alert)
        db.session.commit()
        flash(f"Alarm oprettet for {card_name} ved ${threshold:.2f} USD.", "success")

    return redirect(request.referrer or url_for("alerts.list_alerts"))


@bp.post("/alerts/<int:alert_id>/delete")
@login_required
def delete_alert(alert_id: int):
    alert = db.session.get(PriceAlert, alert_id)
    if alert is None or alert.user_id != current_user.id:
        flash("Alarm ikke fundet.", "error")
        return redirect(url_for("alerts.list_alerts"))

    alert.is_active = False
    db.session.commit()
    flash(f"Alarm for {alert.card_name} slettet.", "success")
    return redirect(url_for("alerts.list_alerts"))
