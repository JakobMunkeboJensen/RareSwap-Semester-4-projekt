"""Selvstændig Flask micro-API til Pokémon-kortdata med live PokemonTCG.io-opslag."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).with_name("pokemon_kort.json")
POKEMON_KORT: list[dict[str, Any]] = json.loads(_DATA_FILE.read_text(encoding="utf-8"))


app = Flask(__name__)

POKEMONTCG_API_KEY = os.getenv("POKEMONTCG_API_KEY", "").strip()

_fx_cache: dict[str, Any] = {"ts": 0.0, "rates": {}}
_FX_TTL_S = 6 * 60 * 60


def _get_eur_to_dkk_rate() -> float | None:
    """Returner EUR→DKK-valutakursen, cachet i 6 timer."""
    now = time.time()
    ts = float(_fx_cache.get("ts") or 0.0)
    rates = _fx_cache.get("rates")
    if isinstance(rates, dict) and (now - ts) < _FX_TTL_S:
        v = rates.get("DKK")
        return float(v) if isinstance(v, (int, float)) else None

    try:
        resp = requests.get("https://open.er-api.com/v6/latest/EUR", timeout=6)
        resp.raise_for_status()
        data = resp.json()
        rates2 = data.get("rates", {})
        if isinstance(rates2, dict) and rates2:
            _fx_cache["ts"] = now
            _fx_cache["rates"] = rates2
            v = rates2.get("DKK")
            return float(v) if isinstance(v, (int, float)) else None
    except Exception:
        logger.exception("Fejl ved hentning af EUR→DKK valutakurs")
    return None


def _eur_to_dkk(eur: float | None) -> float | None:
    """Konverter EUR til DKK via cachet valutakurs; returner None hvis kursen mangler."""
    if eur is None:
        return None
    fx = _get_eur_to_dkk_rate()
    if not fx:
        return None
    return round(eur * fx, 2)


def _normalize_local_card(c: dict[str, Any]) -> dict[str, Any]:
    """Normaliser et lokalt kortdict så det altid har felterne price_eur, price_dkk og image_url."""
    out = dict(c)
    if "price_eur" not in out:
        out["price_eur"] = None
    if "price_dkk" not in out and isinstance(out.get("price_eur"), (int, float)):
        out["price_dkk"] = _eur_to_dkk(float(out["price_eur"]))
    if "image_url" not in out:
        out["image_url"] = None
    return out


def fetch_cards_from_pokemontcg(name: str, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    """Hent op til 12 kort fra PokemonTCG.io og normaliser dem til et fladt dict."""
    q = (name or "").strip()
    if not q:
        return []

    headers: dict[str, str] = {"User-Agent": "pokemon-local-api/1.0"}
    if POKEMONTCG_API_KEY:
        headers["X-Api-Key"] = POKEMONTCG_API_KEY

    try:
        resp = requests.get(
            "https://api.pokemontcg.io/v2/cards",
            params={"q": f'name:"{q}"', "pageSize": 12},
            headers=headers,
            timeout=timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        logger.exception("Fejl ved opslag i PokemonTCG.io for %r", q)
        return []
    cards = data.get("data", [])
    if not isinstance(cards, list):
        return []

    out: list[dict[str, Any]] = []
    for it in cards:
        if not isinstance(it, dict):
            continue
        nm = it.get("name")
        set_info = it.get("set") if isinstance(it.get("set"), dict) else {}
        set_name = set_info.get("name") if isinstance(set_info, dict) else None
        images = it.get("images") if isinstance(it.get("images"), dict) else {}
        image_url = images.get("small") or images.get("large")

        cm = it.get("cardmarket") if isinstance(it.get("cardmarket"), dict) else {}
        prices = cm.get("prices") if isinstance(cm.get("prices"), dict) else {}
        eur = prices.get("averageSellPrice")
        price_eur = float(eur) if isinstance(eur, (int, float)) else None

        out.append(
            {
                "name": str(nm) if nm else "?",
                "set": str(set_name) if set_name else "?",
                "image_url": str(image_url) if image_url else None,
                "price_eur": price_eur,
                "price_dkk": _eur_to_dkk(price_eur),
                "source": "pokemontcg.io(cardmarket)",
            }
        )
    return out


@app.get("/cards")
def get_cards():
    """Returner alle kort eller filtrer efter navn. Prøver live API først, falder tilbage til lokal liste."""
    name_query = request.args.get("name", "").lower()

    if not name_query:
        # Intet søgenavn — returner hele den lokale liste uden live-opslag
        return jsonify([_normalize_local_card(c) for c in POKEMON_KORT])

    try:
        live = fetch_cards_from_pokemontcg(request.args.get("name", ""))
        if live:
            return jsonify(live)
    except Exception:
        logger.exception("Live API-opslag fejlede for %r", name_query)

    # Fallback: live API fejlede eller returnerede ingenting — søg i den lokale liste
    matches = [c for c in POKEMON_KORT if name_query in c["name"].lower()]
    return jsonify([_normalize_local_card(c) for c in matches])


@app.get("/cards/<name>")
def get_single_card(name: str):
    """Returner et enkelt kort efter navn. Prøver live API først, falder tilbage til lokal liste."""
    name_lower = name.lower()

    try:
        live = fetch_cards_from_pokemontcg(name, timeout_s=8.0)
        if live:
            return jsonify(live[0])
    except Exception:
        logger.exception("Live API-opslag fejlede for enkelt kort %r", name)

    # Fallback: live API fejlede eller returnerede ingenting — søg i den lokale liste
    for c in POKEMON_KORT:
        if name_lower in c["name"].lower():
            return jsonify(_normalize_local_card(c))
    return jsonify({"error": "Card not found"}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

