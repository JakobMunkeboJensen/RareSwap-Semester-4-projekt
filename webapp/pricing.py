from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, TypedDict

import requests
from flask import Blueprint, abort, jsonify, render_template, request

from pokemon_pris_scanner import hent_kort_fra_api, udtraek_priser

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
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except Exception:
        return None


def _get_usd_rates() -> dict[str, float]:
    """
    Henter valutakurser med base USD.
    Best-effort: bruger cache, og falder tilbage til sidste kendte kurser.
    """
    now = time.time()
    cached_ts = float(_rates_cache.get("ts") or 0.0)
    cached_rates = _rates_cache.get("rates")
    if isinstance(cached_rates, dict) and (now - cached_ts) < _RATES_TTL_S:
        return {k: float(v) for k, v in cached_rates.items() if isinstance(v, (int, float))}

    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=6)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        if isinstance(rates, dict) and rates:
            _rates_cache["ts"] = now
            _rates_cache["rates"] = rates
            return {k: float(v) for k, v in rates.items() if isinstance(v, (int, float))}
    except Exception:
        logger.info("Could not refresh FX rates; using cached rates if any.")

    if isinstance(cached_rates, dict):
        return {k: float(v) for k, v in cached_rates.items() if isinstance(v, (int, float))}
    return {}


def _get_eur_rates() -> dict[str, float]:
    """
    Henter valutakurser med base EUR.
    Best-effort: bruger cache, og falder tilbage til sidste kendte kurser.
    """
    now = time.time()
    cached_ts = float(_rates_cache.get("ts_eur") or 0.0)
    cached_rates = _rates_cache.get("rates_eur")
    if isinstance(cached_rates, dict) and (now - cached_ts) < _RATES_TTL_S:
        return {k: float(v) for k, v in cached_rates.items() if isinstance(v, (int, float))}

    try:
        resp = requests.get("https://open.er-api.com/v6/latest/EUR", timeout=6)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates", {})
        if isinstance(rates, dict) and rates:
            _rates_cache["ts_eur"] = now
            _rates_cache["rates_eur"] = rates
            return {k: float(v) for k, v in rates.items() if isinstance(v, (int, float))}
    except Exception:
        logger.info("Could not refresh EUR FX rates; using cached rates if any.")

    if isinstance(cached_rates, dict):
        return {k: float(v) for k, v in cached_rates.items() if isinstance(v, (int, float))}
    return {}


def _convert_from_eur(v_eur: float | None, currency: str) -> float | None:
    if v_eur is None:
        return None
    if currency == "EUR":
        return round(v_eur, 2)
    rates = _get_eur_rates()
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
    rates = _get_eur_rates()
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


def _rate_limit_or_429() -> None:
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


def _lookup_prices(name_query: str, currency: str) -> LookupResult:
    name_query = (name_query or "").strip()
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
        cards = hent_kort_fra_api(name_query)
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
        rates = _get_usd_rates()
        fx = float(rates.get(currency) or 0.0)
        if fx <= 0:
            fx = 1.0
            currency = "USD"
            symbol = SUPPORTED_CURRENCIES[currency]
            notice = "Kunne ikke hente valutakurs lige nu. Viser priser i USD."

    rows: list[PriceRow] = []
    for r in priser:
        market_usd = _to_float(r.get("market"))
        low_usd = _to_float(r.get("low"))
        mid_usd = _to_float(r.get("mid"))
        high_usd = _to_float(r.get("high"))

        rows.append(
            PriceRow(
                name=str(r.get("name", "")),
                set=str(r.get("set", "")),
                image_small=(str(r["image_small"]) if r.get("image_small") else None),
                image_large=(str(r["image_large"]) if r.get("image_large") else None),
                market=_convert(market_usd, fx),
                low=_convert(low_usd, fx),
                mid=_convert(mid_usd, fx),
                high=_convert(high_usd, fx),
            )
        )

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
    return render_template("index.html", currencies=SUPPORTED_CURRENCIES, currency="USD")


@bp.get("/lookup")
def lookup():
    _rate_limit_or_429()
    q = request.args.get("q", "")
    currency = request.args.get("currency", "USD")
    result = _lookup_prices(q, currency=currency)
    return render_template("results.html", **result, currencies=SUPPORTED_CURRENCIES)


@bp.get("/api/lookup")
def api_lookup():
    _rate_limit_or_429()
    q = request.args.get("q", "")
    currency = request.args.get("currency", "USD")
    result = _lookup_prices(q, currency=currency)
    return jsonify(
        {
            "query": result["query"],
            "error": result["error"],
            "currency": result["currency"],
            "rows": [asdict(r) for r in result["rows"]],
        }
    )


@bp.get("/status")
def status():
    _rate_limit_or_429()
    api_ok, api_msg = _pokemontcg_healthcheck()

    now = time.time()
    ts = float(_rates_cache.get("ts") or 0.0)
    age_s = max(0.0, now - ts) if ts else None
    cached_rates = _rates_cache.get("rates")
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

