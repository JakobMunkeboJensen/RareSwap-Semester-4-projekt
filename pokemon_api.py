from __future__ import annotations

import os
import time
from typing import Any

import requests
from flask import Flask, jsonify, request

POKEMON_KORT = [
    {"name": "Charizard", "set": "Base Set", "price_dkk": 2500.0},
    {"name": "Charizard Holo", "set": "Base Set 2", "price_dkk": 1800.0},
    {"name": "Dark Charizard", "set": "Team Rocket", "price_dkk": 650.0},
    {"name": "Charizard (Legendary Collection)", "set": "Legendary Collection", "price_dkk": 900.0},
    {"name": "Charizard ex", "set": "FireRed & LeafGreen", "price_dkk": 1200.0},
    {"name": "Charizard EX", "set": "Flashfire", "price_dkk": 220.0},
    {"name": "M Charizard EX", "set": "Flashfire", "price_dkk": 450.0},
    {"name": "Charizard GX", "set": "Burning Shadows", "price_dkk": 160.0},
    {"name": "Reshiram & Charizard GX", "set": "Unbroken Bonds", "price_dkk": 220.0},
    {"name": "Charizard V", "set": "Champion's Path", "price_dkk": 110.0},
    {"name": "Charizard VMAX", "set": "Champion's Path", "price_dkk": 160.0},
    {"name": "Charizard VSTAR", "set": "Brilliant Stars", "price_dkk": 120.0},
    {"name": "Radiant Charizard", "set": "Pokémon GO", "price_dkk": 60.0},
    {"name": "Charizard (Shiny)", "set": "Hidden Fates", "price_dkk": 1200.0},
    {"name": "Pikachu", "set": "Base Set", "price_dkk": 50.0},
    {"name": "Pikachu V", "set": "Vivid Voltage", "price_dkk": 80.0},
    {"name": "Pikachu VMAX", "set": "Vivid Voltage", "price_dkk": 140.0},
    {"name": "Pikachu & Zekrom GX", "set": "Team Up", "price_dkk": 180.0},
    {"name": "Pikachu (Secret Rare)", "set": "Cosmic Eclipse", "price_dkk": 300.0},
    {"name": "Pikachu (Promo)", "set": "SWSH Promo", "price_dkk": 35.0},
    {"name": "Mewtwo", "set": "Base Set", "price_dkk": 400.0},
    {"name": "Mewtwo EX", "set": "Next Destinies", "price_dkk": 150.0},
    {"name": "Mewtwo GX", "set": "Shining Legends", "price_dkk": 120.0},
    {"name": "Mewtwo V", "set": "Pokémon GO", "price_dkk": 45.0},
    {"name": "Mewtwo VSTAR", "set": "Crown Zenith", "price_dkk": 55.0},
    {"name": "Mew", "set": "Fossil", "price_dkk": 160.0},
    {"name": "Mew ex", "set": "151", "price_dkk": 120.0},
    {"name": "Gengar", "set": "Fossil", "price_dkk": 350.0},
    {"name": "Gengar VMAX", "set": "Fusion Strike", "price_dkk": 240.0},
    {"name": "Rayquaza", "set": "EX Deoxys", "price_dkk": 500.0},
    {"name": "Rayquaza VMAX", "set": "Evolving Skies", "price_dkk": 220.0},
    {"name": "Lugia", "set": "Neo Genesis", "price_dkk": 850.0},
    {"name": "Lugia V", "set": "Silver Tempest", "price_dkk": 55.0},
    {"name": "Lugia VSTAR", "set": "Silver Tempest", "price_dkk": 70.0},
    {"name": "Umbreon", "set": "Neo Discovery", "price_dkk": 650.0},
    {"name": "Umbreon VMAX", "set": "Evolving Skies", "price_dkk": 3800.0},
    {"name": "Espeon VMAX", "set": "Fusion Strike", "price_dkk": 250.0},
    {"name": "Sylveon VMAX", "set": "Evolving Skies", "price_dkk": 220.0},
    {"name": "Gardevoir ex", "set": "Scarlet & Violet", "price_dkk": 55.0},
    {"name": "Garchomp", "set": "Majestic Dawn", "price_dkk": 180.0},
    {"name": "Lucario", "set": "DP Promo", "price_dkk": 60.0},
    {"name": "Greninja", "set": "BREAKpoint", "price_dkk": 45.0},
    {"name": "Greninja (Shiny)", "set": "Shining Fates", "price_dkk": 140.0},
    {"name": "Eevee", "set": "Jungle", "price_dkk": 35.0},
    {"name": "Eevee V", "set": "Evolving Skies", "price_dkk": 20.0},
    {"name": "Snorlax", "set": "Jungle", "price_dkk": 220.0},
    {"name": "Snorlax VMAX", "set": "Sword & Shield", "price_dkk": 45.0},
    {"name": "Gyarados", "set": "Base Set", "price_dkk": 180.0},
    {"name": "Gyarados EX", "set": "Breakpoint", "price_dkk": 80.0},
    {"name": "Blastoise", "set": "Base Set", "price_dkk": 900.0},
    {"name": "Venusaur", "set": "Base Set", "price_dkk": 650.0},
    {"name": "Dragonite", "set": "Fossil", "price_dkk": 450.0},
    {"name": "Alakazam", "set": "Base Set", "price_dkk": 420.0},
    {"name": "Machamp", "set": "Base Set", "price_dkk": 160.0},
    {"name": "Zapdos", "set": "Fossil", "price_dkk": 220.0},
    {"name": "Articuno", "set": "Fossil", "price_dkk": 220.0},
    {"name": "Moltres", "set": "Fossil", "price_dkk": 220.0},
    {"name": "Arceus VSTAR", "set": "Brilliant Stars", "price_dkk": 110.0},
    {"name": "Dialga VSTAR", "set": "Astral Radiance", "price_dkk": 95.0},
    {"name": "Palkia VSTAR", "set": "Astral Radiance", "price_dkk": 95.0},
    {"name": "Giratina VSTAR", "set": "Lost Origin", "price_dkk": 140.0},
    {"name": "Miraidon ex", "set": "Scarlet & Violet", "price_dkk": 60.0},
    {"name": "Koraidon ex", "set": "Scarlet & Violet", "price_dkk": 60.0},
    {"name": "Iron Valiant ex", "set": "Paradox Rift", "price_dkk": 55.0},
    {"name": "Roaring Moon ex", "set": "Paradox Rift", "price_dkk": 80.0},
    {"name": "Gardevoir", "set": "Ruby & Sapphire", "price_dkk": 120.0},
    {"name": "Metagross", "set": "Hidden Legends", "price_dkk": 140.0},
    {"name": "Salamence", "set": "Dragon", "price_dkk": 160.0},
    {"name": "Tyranitar", "set": "Neo Discovery", "price_dkk": 520.0},
    {"name": "Tyranitar V", "set": "Battle Styles", "price_dkk": 35.0},
    {"name": "Tyranitar VMAX", "set": "Battle Styles", "price_dkk": 60.0},
    {"name": "Scizor", "set": "Neo Discovery", "price_dkk": 180.0},
    {"name": "Scizor V", "set": "Darkness Ablaze", "price_dkk": 18.0},
    {"name": "Scizor VMAX", "set": "Darkness Ablaze", "price_dkk": 28.0},
    {"name": "Lapras", "set": "Fossil", "price_dkk": 90.0},
    {"name": "Lapras V", "set": "Sword & Shield", "price_dkk": 20.0},
    {"name": "Lapras VMAX", "set": "Sword & Shield", "price_dkk": 35.0},
    {"name": "Charmeleon", "set": "Base Set", "price_dkk": 45.0},
    {"name": "Charmander", "set": "Base Set", "price_dkk": 35.0},
    {"name": "Squirtle", "set": "Base Set", "price_dkk": 35.0},
    {"name": "Wartortle", "set": "Base Set", "price_dkk": 45.0},
    {"name": "Bulbasaur", "set": "Base Set", "price_dkk": 35.0},
    {"name": "Ivysaur", "set": "Base Set", "price_dkk": 45.0},
    {"name": "Jolteon", "set": "Jungle", "price_dkk": 220.0},
    {"name": "Vaporeon", "set": "Jungle", "price_dkk": 220.0},
    {"name": "Flareon", "set": "Jungle", "price_dkk": 220.0},
    {"name": "Jolteon VMAX", "set": "Evolving Skies", "price_dkk": 80.0},
    {"name": "Vaporeon VMAX", "set": "Evolving Skies", "price_dkk": 80.0},
    {"name": "Flareon VMAX", "set": "Evolving Skies", "price_dkk": 80.0},
    {"name": "Glaceon VMAX", "set": "Evolving Skies", "price_dkk": 260.0},
    {"name": "Leafeon VMAX", "set": "Evolving Skies", "price_dkk": 240.0},
    {"name": "Eevee (McDonald's Promo)", "set": "McDonald's Collection", "price_dkk": 20.0},
    {"name": "Celebi", "set": "Neo Revelation", "price_dkk": 480.0},
    {"name": "Celebi V", "set": "Chilling Reign", "price_dkk": 20.0},
    {"name": "Celebi VMAX", "set": "Chilling Reign", "price_dkk": 35.0},
    {"name": "Jirachi", "set": "Team Up", "price_dkk": 35.0},
    {"name": "Deoxys", "set": "EX Deoxys", "price_dkk": 260.0},
    {"name": "Latias", "set": "EX Dragon", "price_dkk": 280.0},
    {"name": "Latios", "set": "EX Dragon", "price_dkk": 280.0},
    {"name": "Zekrom", "set": "Black & White", "price_dkk": 140.0},
    {"name": "Reshiram", "set": "Black & White", "price_dkk": 140.0},
    {"name": "Zacian V", "set": "Sword & Shield", "price_dkk": 20.0},
    {"name": "Zamazenta V", "set": "Sword & Shield", "price_dkk": 18.0},
    {"name": "Zeraora V", "set": "Chilling Reign", "price_dkk": 18.0},
    {"name": "Zeraora VMAX", "set": "Chilling Reign", "price_dkk": 28.0},
    {"name": "Suicune", "set": "Neo Revelation", "price_dkk": 520.0},
    {"name": "Entei", "set": "Neo Revelation", "price_dkk": 520.0},
    {"name": "Raikou", "set": "Neo Revelation", "price_dkk": 520.0},
    {"name": "Suicune V", "set": "Evolving Skies", "price_dkk": 30.0},
    {"name": "Entei V", "set": "Brilliant Stars", "price_dkk": 30.0},
    {"name": "Raikou V", "set": "Brilliant Stars", "price_dkk": 30.0},
    {"name": "Kyogre", "set": "EX Ruby & Sapphire", "price_dkk": 280.0},
    {"name": "Groudon", "set": "EX Ruby & Sapphire", "price_dkk": 280.0},
    {"name": "Kyogre EX", "set": "Dark Explorers", "price_dkk": 90.0},
    {"name": "Groudon EX", "set": "Dark Explorers", "price_dkk": 90.0},
    {"name": "Primal Kyogre EX", "set": "Primal Clash", "price_dkk": 180.0},
    {"name": "Primal Groudon EX", "set": "Primal Clash", "price_dkk": 180.0},
    {"name": "Ho-Oh", "set": "Neo Revelation", "price_dkk": 650.0},
    {"name": "Ho-Oh GX", "set": "Burning Shadows", "price_dkk": 45.0},
    {"name": "Ho-Oh V", "set": "Silver Tempest", "price_dkk": 35.0},
    {"name": "Darkrai", "set": "Great Encounters", "price_dkk": 180.0},
    {"name": "Darkrai GX", "set": "Burning Shadows", "price_dkk": 35.0},
    {"name": "Darkrai VSTAR", "set": "Crown Zenith", "price_dkk": 55.0},
    {"name": "Lucario V", "set": "Champion's Path", "price_dkk": 18.0},
    {"name": "Lucario VSTAR", "set": "Crown Zenith", "price_dkk": 45.0},
    {"name": "Snorlax (Promo)", "set": "SWSH Promo", "price_dkk": 25.0},
    {"name": "Gyarados V", "set": "Evolving Skies", "price_dkk": 18.0},
    {"name": "Gyarados VMAX", "set": "Evolving Skies", "price_dkk": 28.0},
    {"name": "Blaziken VMAX", "set": "Chilling Reign", "price_dkk": 180.0},
    {"name": "Infernape", "set": "Diamond & Pearl", "price_dkk": 120.0},
    {"name": "Empoleon", "set": "Diamond & Pearl", "price_dkk": 120.0},
    {"name": "Decidueye", "set": "Sun & Moon", "price_dkk": 45.0},
    {"name": "Incineroar", "set": "Sun & Moon", "price_dkk": 45.0},
    {"name": "Primarina", "set": "Sun & Moon", "price_dkk": 45.0},
    {"name": "Cinderace", "set": "Sword & Shield", "price_dkk": 30.0},
    {"name": "Inteleon", "set": "Sword & Shield", "price_dkk": 30.0},
    {"name": "Rillaboom", "set": "Sword & Shield", "price_dkk": 30.0},
    {"name": "Meowscarada ex", "set": "Paldea Evolved", "price_dkk": 45.0},
    {"name": "Skeledirge ex", "set": "Paldea Evolved", "price_dkk": 45.0},
    {"name": "Quaquaval ex", "set": "Paldea Evolved", "price_dkk": 45.0},
    {"name": "Gholdengo ex", "set": "Paradox Rift", "price_dkk": 55.0},
    {"name": "Mew VMAX", "set": "Fusion Strike", "price_dkk": 240.0},
    {"name": "Genesect V", "set": "Fusion Strike", "price_dkk": 25.0},
    {"name": "Arcanine", "set": "Base Set", "price_dkk": 120.0},
    {"name": "Arcanine ex", "set": "Scarlet & Violet", "price_dkk": 45.0},
    {"name": "Rapidash", "set": "Base Set", "price_dkk": 75.0},
    {"name": "Rapidash (Galarian)", "set": "Chilling Reign", "price_dkk": 20.0},
    {"name": "Ninetales", "set": "Base Set", "price_dkk": 180.0},
    {"name": "Ninetales (Alolan)", "set": "Guardians Rising", "price_dkk": 35.0},
    {"name": "Psyduck", "set": "Fossil", "price_dkk": 25.0},
    {"name": "Slowpoke", "set": "Team Rocket", "price_dkk": 20.0},
    {"name": "Slowbro", "set": "Fossil", "price_dkk": 80.0},
    {"name": "Ditto", "set": "Fossil", "price_dkk": 120.0},
    {"name": "Ditto V", "set": "Shining Fates", "price_dkk": 18.0},
    {"name": "Dragonite V", "set": "Evolving Skies", "price_dkk": 25.0},
    {"name": "Dragonite VSTAR", "set": "Pokémon GO", "price_dkk": 45.0},
    {"name": "Eevee & Snorlax GX", "set": "Team Up", "price_dkk": 120.0},
    {"name": "Gengar & Mimikyu GX", "set": "Team Up", "price_dkk": 180.0},
]


app = Flask(__name__)

POKEMONTCG_API_KEY = os.getenv("POKEMONTCG_API_KEY", "").strip()

_fx_cache: dict[str, Any] = {"ts": 0.0, "rates": {}}
_FX_TTL_S = 6 * 60 * 60


def _get_eur_to_dkk_rate() -> float | None:
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
        pass
    return None


def _eur_to_dkk(eur: float | None) -> float | None:
    if eur is None:
        return None
    fx = _get_eur_to_dkk_rate()
    if not fx:
        return None
    return round(eur * fx, 2)


def _normalize_local_card(c: dict[str, Any]) -> dict[str, Any]:
    out = dict(c)
    if "price_eur" not in out:
        out["price_eur"] = None
    if "price_dkk" not in out and isinstance(out.get("price_eur"), (int, float)):
        out["price_dkk"] = _eur_to_dkk(float(out["price_eur"]))
    if "image_url" not in out:
        out["image_url"] = None
    return out


def fetch_cards_from_pokemontcg(name: str, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    q = (name or "").strip()
    if not q:
        return []

    headers: dict[str, str] = {"User-Agent": "pokemon-local-api/1.0"}
    if POKEMONTCG_API_KEY:
        headers["X-Api-Key"] = POKEMONTCG_API_KEY

    resp = requests.get(
        "https://api.pokemontcg.io/v2/cards",
        params={"q": f'name:"{q}"', "pageSize": 12},
        headers=headers,
        timeout=timeout_s,
    )
    resp.raise_for_status()
    data = resp.json()
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
    name_query = request.args.get("name", "").lower()

    if not name_query:
        return jsonify([_normalize_local_card(c) for c in POKEMON_KORT])

    # Try live lookup first (gives real-ish prices + images)
    try:
        live = fetch_cards_from_pokemontcg(request.args.get("name", ""))
        if live:
            return jsonify(live)
    except Exception:
        pass

    matches = [c for c in POKEMON_KORT if name_query in c["name"].lower()]
    return jsonify([_normalize_local_card(c) for c in matches])


@app.get("/cards/<name>")
def get_single_card(name: str):
    name_lower = name.lower()

    try:
        live = fetch_cards_from_pokemontcg(name, timeout_s=8.0)
        if live:
            return jsonify(live[0])
    except Exception:
        pass

    for c in POKEMON_KORT:
        if name_lower in c["name"].lower():
            return jsonify(_normalize_local_card(c))
    return jsonify({"error": "Card not found"}), 404


if __name__ == "__main__":
    # API'et kører på http://127.0.0.1:5000/
    app.run(host="127.0.0.1", port=5000, debug=True)

