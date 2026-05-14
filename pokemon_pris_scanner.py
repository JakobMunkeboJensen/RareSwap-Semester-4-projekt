"""Hent Pokémon-kortpriser fra PokemonTCG API med offline-fallback."""

from __future__ import annotations

from typing import Any

import requests

API_URL = "https://api.pokemontcg.io/v2/cards"
_DEFAULT_TIMEOUT_S = 20.0

# Offline fallback used when the API is unreachable
FALLBACK_KORT = [
    {"name": "Charizard", "set": "Base Set", "market": 2500, "low": 2000, "mid": 2600, "high": 3000},
    {"name": "Pikachu", "set": "Base Set", "market": 50, "low": 30, "mid": 60, "high": 80},
    {"name": "Mewtwo", "set": "Base Set", "market": 400, "low": 350, "mid": 420, "high": 500},
]

_session = requests.Session()
_session.headers.update({"User-Agent": "pokemon-pris-scanner/1.0"})


def hent_kort_fra_api(
    kortnavn: str, *, saet: str = "", timeout_s: float = _DEFAULT_TIMEOUT_S
) -> list[dict[str, Any]] | None:
    """Søg i PokemonTCG API; returner None ved timeout eller forbindelsesfejl."""
    q = f'name:"{kortnavn}"'
    if saet:
        q += f' set.name:"{saet}"'
    params = {
        "q": q,
        "pageSize": 30,
    }

    print(f"Søger i PokemonTCG API efter: {kortnavn}" + (f" (sæt: {saet})" if saet else ""))
    try:
        resp = _session.get(API_URL, params=params, timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json()
        cards = data.get("data", [])
        return cards if isinstance(cards, list) else []
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.ConnectionError:
        return None


def udtraek_priser(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Udtræk navn, sæt, billeder og TCGPlayer-priser fra rå API-kortobjekter."""
    resultater: list[dict[str, Any]] = []

    for c in cards:
        name = c.get("name", "Ukendt navn")
        set_obj = c.get("set", {})
        set_name = set_obj.get("name", "Ukendt sæt") if isinstance(set_obj, dict) else "Ukendt sæt"
        images_obj = c.get("images", {})
        image_small = None
        image_large = None
        if isinstance(images_obj, dict):
            image_small = images_obj.get("small")
            image_large = images_obj.get("large")
        tcgplayer = c.get("tcgplayer", {})
        prices = tcgplayer.get("prices", {}) if isinstance(tcgplayer, dict) else {}

        prisfelt = None
        for key in ["normal", "holofoil", "reverseHolofoil"]:
            if key in prices:
                prisfelt = prices[key]
                break

        if isinstance(prisfelt, dict) and prisfelt:
            market = prisfelt.get("market")
            low = prisfelt.get("low")
            mid = prisfelt.get("mid")
            high = prisfelt.get("high")
            resultater.append(
                {
                    "name": name,
                    "set": set_name,
                    "image_small": image_small,
                    "image_large": image_large,
                    "market": market,
                    "low": low,
                    "mid": mid,
                    "high": high,
                }
            )

    return resultater


def scan_kort():
    """Interaktiv CLI-løkke til at slå kortpriser op ved navn."""
    print("=== Pokémon Pris-Scanner (internet/API) ===")
    print("Skriv navnet på et Pokémon-kort (eller en del af navnet).")
    print("Tomt input lukker programmet.\n")

    while True:
        kortnavn = input("Kortnavn: ").strip()
        if not kortnavn:
            print("Farvel!")
            break

        try:
            cards = hent_kort_fra_api(kortnavn)

            if cards is None:
                print("Kunne ikke få svar fra API'et (timeout/ingen forbindelse).")
                print("Bruger indbyggede eksempelpriser i stedet.\n")
                priser = [
                    k for k in FALLBACK_KORT if kortnavn.lower() in k["name"].lower()
                ]
                if not priser:
                    print("Ingen match i fallback-data.\n")
                    continue
            else:
                if not cards:
                    print("Fandt ingen kort i API'et.\n")
                    continue

                priser = udtraek_priser(cards)

                if not priser:
                    print("Fandt kort, men ingen prisdata tilgængelig.\n")
                    continue

            print(f"\nFundne kort og priser for '{kortnavn}':")
            for i, r in enumerate(priser, start=1):
                print(
                    f"{i}. {r['name']} ({r['set']}) - "
                    f"Market: {r['market']}, Low: {r['low']}, "
                    f"Mid: {r['mid']}, High: {r['high']}"
                )
            print()
        except requests.HTTPError as e:
            print(f"Fejl fra PokemonTCG API ({e.response.status_code}): {e}\n")
        except Exception as e:
            print(f"Der opstod en uventet fejl: {e}\n")


if __name__ == "__main__":
    scan_kort()