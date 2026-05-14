"""Blueprint til kortprisopslag, valutakonvertering, prishistorik og statusside."""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, TypedDict

import requests
from flask import Blueprint, abort, jsonify, render_template, request

from pokemon_pris_scanner import hent_kort_fra_api, udtraek_priser

from .extensions import db
from .mail import send_email
from .models import PriceAlert, PriceHistory, User

logger = logging.getLogger(__name__)

bp = Blueprint("pricing", __name__)

SUPPORTED_CURRENCIES: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "DKK": "kr",
}

_rates_cache: dict[str, Any] = {"ts": 0.0, "rates": {}}
_RATES_TTL_S = 6 * 60 * 60  # 6 timer

LOCAL_CARD_API_BASE_URL = os.getenv("LOCAL_CARD_API_BASE_URL", "http://127.0.0.1:5000").strip()
USE_LOCAL_CARD_API = os.getenv("USE_LOCAL_CARD_API", "0").strip() in {"1", "true", "True"}

_RL_WINDOW_S = float(os.getenv("RATE_LIMIT_WINDOW_S", "60"))
_RL_MAX_REQ = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "30"))
_rl_by_ip: dict[str, deque[float]] = {}


@dataclass
class PriceRow:
    name: str
    set: str
    image_small: str | None
    image_large: str | None
    market: float | None
    low: float | None
    mid: float | None
    high: float | None


class LookupResult(TypedDict):
    query: str
    rows: list[PriceRow]
    error: str | None
    currency: str
    currency_symbol: str
    currency_notice: str | None


def _to_float(v: Any) -> float | None:
    """Konverter en numerisk-lignende værdi til float, returner None ved fejl."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except Exception:
        return None


def _get_rates(base: str) -> dict[str, float]:
    """Returner valutakurser for den givne basisvaluta med 6-timers cache i hukommelsen."""
    ts_key = f"ts_{base}"
    rates_key = f"rates_{base}"
    now = time.time()
    cached_ts = float(_rates_cache.get(ts_key) or 0.0)
    cached_rates = _rates_cache.get(rates_key)
    if isinstance(cached_rates, dict) and (now - cached_ts) < _RATES_TTL_S:
        return {k: float(v) for k, v in cached_rates.items() if isinstance(v, (int, float))}

    try:
        resp = requests.get(f"https://open.er-api.com/v6/latest/{base}", timeout=6)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        if isinstance(rates, dict) and rates:
            _rates_cache[ts_key] = now
            _rates_cache[rates_key] = rates
            return {k: float(v) for k, v in rates.items() if isinstance(v, (int, float))}
    except Exception:
        logger.info("Could not refresh %s FX rates; using cached rates if any.", base)

    if isinstance(cached_rates, dict):
        return {k: float(v) for k, v in cached_rates.items() if isinstance(v, (int, float))}
    return {}


def _convert_from_eur(v_eur: float | None, currency: str) -> float | None:
    if v_eur is None:
        return None
    if currency == "EUR":
        return round(v_eur, 2)
    rates = _get_rates("EUR")
    fx = float(rates.get(currency) or 0.0)
    if fx <= 0:
        return None
    return round(v_eur * fx, 2)


def _convert_from_dkk(v_dkk: float | None, currency: str) -> float | None:
    if v_dkk is None:
        return None
    if currency == "DKK":
        return round(v_dkk, 2)
    # Convert DKK -> EUR using EUR base rates (DKK per EUR), then EUR -> target
    rates = _get_rates("EUR")
    dkk_per_eur = float(rates.get("DKK") or 0.0)
    if dkk_per_eur <= 0:
        return None
    eur = v_dkk / dkk_per_eur
    return _convert_from_eur(eur, currency=currency)


def _lookup_cards_from_local_api(name: str) -> list[dict[str, Any]] | None:
    """
    Uses the local `pokemon_api.py` service:
      GET http://127.0.0.1:5000/cards?name=<name>
    Returns list[dict] or None on connectivity issues.
    """
    base = LOCAL_CARD_API_BASE_URL.rstrip("/")
    try:
        resp = requests.get(f"{base}/cards", params={"name": name}, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return None


def _convert(v_usd: float | None, fx: float) -> float | None:
    if v_usd is None:
        return None
    return round(v_usd * fx, 2)


_ALERT_COOLDOWN = timedelta(hours=24)


def _check_and_fire_alerts(card_name: str, card_set: str, market_usd: float) -> None:
    now = datetime.utcnow()
    try:
        alerts = db.session.execute(
            db.select(PriceAlert).where(
                PriceAlert.card_name == card_name,
                PriceAlert.card_set == card_set,
                PriceAlert.is_active,
                PriceAlert.threshold_usd >= market_usd,
            )
        ).scalars().all()
    except Exception:
        logger.exception("Could not query price alerts")
        return

    for alert in alerts:
        if alert.last_triggered_at and (now - alert.last_triggered_at) < _ALERT_COOLDOWN:
            continue
        user = db.session.get(User, alert.user_id)
        if user is None or not user.email:
            continue
        try:
            body = (
                f"Din pris-alarm for {card_name} ({card_set}) er udløst!\n\n"
                f"Nuværende market-pris: ${market_usd:.2f} USD\n"
                f"Din grænse: ${alert.threshold_usd:.2f} USD\n\n"
                f"Se mere på sitet: /lookup?q={card_name}\n\n"
                f"Du kan slette alarmen på /alerts."
            )
            send_email(user.email, f"Pris-alarm: {card_name}", body)
            alert.last_triggered_at = now
            logger.info("Fired price alert for %s to %s", card_name, user.email)
        except Exception:
            logger.exception("Failed to send price alert to %s", user.email)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def _rate_limit_or_429() -> None:
    """Afbryd med 429 hvis den kaldende IP har overskredet den konfigurerede anmodningsrate."""
    ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "unknown")
    now = time.time()
    q = _rl_by_ip.get(ip)
    if q is None:
        q = deque()
        _rl_by_ip[ip] = q
    cutoff = now - _RL_WINDOW_S
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= _RL_MAX_REQ:
        abort(429)
    q.append(now)


def _pokemontcg_healthcheck(timeout_s: float = 4.0) -> tuple[bool, str]:
    """Ping kort-API'et og returner (ok, menneskevenlig statusbesked)."""
    if USE_LOCAL_CARD_API:
        try:
            base = LOCAL_CARD_API_BASE_URL.rstrip("/")
            resp = requests.get(f"{base}/cards", params={"name": "Pikachu"}, timeout=timeout_s)
            if 200 <= resp.status_code < 300:
                return True, f"OK (local API) (HTTP {resp.status_code})"
            return False, f"Fejl (local API) (HTTP {resp.status_code})"
        except Exception as e:
            return False, f"Fejl (local API) ({type(e).__name__})"

    try:
        resp = requests.get(
            "https://api.pokemontcg.io/v2/cards",
            params={"q": "name:Pikachu", "pageSize": 1},
            timeout=timeout_s,
            headers={"User-Agent": "pokemon-pris-scanner/1.0"},
        )
        if 200 <= resp.status_code < 300:
            return True, f"OK (HTTP {resp.status_code})"
        return False, f"Fejl (HTTP {resp.status_code})"
    except Exception as e:
        return False, f"Fejl ({type(e).__name__})"


def _lookup_prices(name_query: str, currency: str, saet: str = "") -> LookupResult:
    name_query = (name_query or "").strip()
    saet = (saet or "").strip()
    currency = (currency or "USD").upper().strip()
    if currency not in SUPPORTED_CURRENCIES:
        currency = "USD"

    symbol = SUPPORTED_CURRENCIES[currency]
    notice: str | None = None

    if not name_query:
        return {
            "query": "",
            "rows": [],
            "error": "Indtast et kortnavn.",
            "currency": currency,
            "currency_symbol": symbol,
            "currency_notice": None,
        }

    if USE_LOCAL_CARD_API:
        cards_local = _lookup_cards_from_local_api(name_query)
        if cards_local is None:
            return {
                "query": name_query,
                "rows": [],
                "error": "Kunne ikke nå lokale kort-API (pokemon_api.py). Start det og prøv igen.",
                "currency": currency,
                "currency_symbol": symbol,
                "currency_notice": None,
            }
        if not cards_local:
            return {
                "query": name_query,
                "rows": [],
                "error": "Ingen kort fundet.",
                "currency": currency,
                "currency_symbol": symbol,
                "currency_notice": None,
            }

        rows: list[PriceRow] = []
        have_any_price = False
        for c in cards_local:
            if not isinstance(c, dict):
                continue
            eur = _to_float(c.get("price_eur"))
            dkk = _to_float(c.get("price_dkk"))
            market = _convert_from_eur(eur, currency=currency)
            if market is None:
                market = _convert_from_dkk(dkk, currency=currency)
            if market is not None:
                have_any_price = True

            img = c.get("image_url")
            img_url = str(img) if img else None
            rows.append(
                PriceRow(
                    name=str(c.get("name", "")),
                    set=str(c.get("set", "")),
                    image_small=img_url,
                    image_large=img_url,
                    market=market,
                    low=None,
                    mid=None,
                    high=None,
                )
            )

        if currency == "USD":
            notice = "Bemærk: lokale priser er i EUR/DKK og konverteres til USD."
        if not have_any_price:
            notice = "Fandt kort, men ingen Cardmarket-prisdata tilgængelig for dem."
        return {
            "query": name_query,
            "rows": rows,
            "error": None,
            "currency": currency,
            "currency_symbol": symbol,
            "currency_notice": notice,
        }

    try:
        cards = hent_kort_fra_api(name_query, saet=saet)
    except Exception:
        logger.exception("Lookup failed for query=%r", name_query)
        return {
            "query": name_query,
            "rows": [],
            "error": "Der opstod en fejl under opslaget. Prøv igen.",
            "currency": currency,
            "currency_symbol": symbol,
            "currency_notice": None,
        }

    if cards is None:
        return {
            "query": name_query,
            "rows": [],
            "error": "Kunne ikke nå PokemonTCG API (timeout/ingen internet).",
            "currency": currency,
            "currency_symbol": symbol,
            "currency_notice": None,
        }

    if not cards:
        return {
            "query": name_query,
            "rows": [],
            "error": "Ingen kort fundet.",
            "currency": currency,
            "currency_symbol": symbol,
            "currency_notice": None,
        }

    priser = udtraek_priser(cards)
    if not priser:
        return {
            "query": name_query,
            "rows": [],
            "error": "Fandt kort, men ingen prisdata tilgængelig.",
            "currency": currency,
            "currency_symbol": symbol,
            "currency_notice": None,
        }

    fx = 1.0
    if currency != "USD":
        rates = _get_rates("USD")
        fx = float(rates.get(currency) or 0.0)
        if fx <= 0:
            fx = 1.0
            currency = "USD"
            symbol = SUPPORTED_CURRENCIES[currency]
            notice = "Kunne ikke hente valutakurs lige nu. Viser priser i USD."

    rows: list[PriceRow] = []
    history_entries: list[PriceHistory] = []
    for r in priser:
        market_usd = _to_float(r.get("market"))
        low_usd = _to_float(r.get("low"))
        mid_usd = _to_float(r.get("mid"))
        high_usd = _to_float(r.get("high"))

        card_name = str(r.get("name", ""))
        card_set = str(r.get("set", ""))

        rows.append(
            PriceRow(
                name=card_name,
                set=card_set,
                image_small=(str(r["image_small"]) if r.get("image_small") else None),
                image_large=(str(r["image_large"]) if r.get("image_large") else None),
                market=_convert(market_usd, fx),
                low=_convert(low_usd, fx),
                mid=_convert(mid_usd, fx),
                high=_convert(high_usd, fx),
            )
        )

        if market_usd is not None:
            history_entries.append(PriceHistory(card_name=card_name, card_set=card_set, market_usd=market_usd))
            _check_and_fire_alerts(card_name, card_set, market_usd)

    if history_entries:
        try:
            db.session.add_all(history_entries)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Could not save price history")

    return {
        "query": name_query,
        "rows": rows,
        "error": None,
        "currency": currency,
        "currency_symbol": symbol,
        "currency_notice": notice,
    }


@bp.get("/")
def home():
    """Vis søgningens startside."""
    return render_template("index.html", currencies=SUPPORTED_CURRENCIES, currency="USD")


@bp.get("/lookup")
def lookup():
    """Slå kortpriser op og vis resultatsiden."""
    _rate_limit_or_429()
    q = request.args.get("q", "")
    currency = request.args.get("currency", "USD")
    saet = request.args.get("set", "")
    result = _lookup_prices(q, currency=currency, saet=saet)
    return render_template("results.html", **result, currencies=SUPPORTED_CURRENCIES, saet=saet)


@bp.get("/api/lookup")
def api_lookup():
    """JSON-endpoint til kortprisopslag."""
    _rate_limit_or_429()
    q = request.args.get("q", "")
    currency = request.args.get("currency", "USD")
    saet = request.args.get("set", "")
    result = _lookup_prices(q, currency=currency, saet=saet)
    return jsonify(
        {
            "query": result["query"],
            "error": result["error"],
            "currency": result["currency"],
            "rows": [asdict(r) for r in result["rows"]],
        }
    )


@bp.get("/history")
def history():
    """Vis historiske markedspriser for et givet kort som diagram."""
    name = (request.args.get("name") or "").strip()
    card_set = (request.args.get("set") or "").strip()

    if not name:
        return render_template("history.html", name="", card_set="", entries=[], labels=[], prices=[])

    query = db.select(PriceHistory).where(PriceHistory.card_name == name)
    if card_set:
        query = query.where(PriceHistory.card_set == card_set)
    query = query.order_by(PriceHistory.recorded_at.asc()).limit(100)

    entries = db.session.execute(query).scalars().all()
    labels = [e.recorded_at.strftime("%d/%m %H:%M") for e in entries]
    prices = [e.market_usd for e in entries]

    return render_template("history.html", name=name, card_set=card_set, entries=entries, labels=labels, prices=prices)


@bp.get("/status")
def status():
    """Vis en sundhedstjekside for API'et og valutakurs-cachen."""
    _rate_limit_or_429()
    api_ok, api_msg = _pokemontcg_healthcheck()

    now = time.time()
    ts = float(_rates_cache.get("ts_USD") or 0.0)
    age_s = max(0.0, now - ts) if ts else None
    cached_rates = _rates_cache.get("rates_USD")
    have_rates = isinstance(cached_rates, dict) and bool(cached_rates)
    fx_ok = have_rates
    fx_msg = "Ingen kurser cached endnu."
    if have_rates and age_s is not None:
        fx_msg = f"Cached kurser OK (alder: {int(age_s)} sek.)"

    items = [
        {"label": "Webserver", "value": "OK", "ok": True},
        {"label": "PokemonTCG API", "value": api_msg, "ok": api_ok},
        {"label": "Valutakurser (USD base)", "value": fx_msg, "ok": fx_ok},
        {"label": "Rate limit", "value": f"{_RL_MAX_REQ} requests pr. {int(_RL_WINDOW_S)} sek. (per IP)", "ok": True},
    ]

    return render_template("status.html", title="Status", items=items, pokemontcg_ok=api_ok, fx_ok=fx_ok)

