"""
Pokemon pris-scanner via PokemonTCG API.

Dette script kan:
- søge kort via PokemonTCG API baseret på kortnavn
- udtrække prisfelter fra API-respons
- falde tilbage til lokal eksempeldata ved netværksfejl
"""

from __future__ import annotations

from typing import Any

import requests

API_URL = "https://api.pokemontcg.io/v2/cards"
_DEFAULT_TIMEOUT_S = 20.0

# Simpel "offline" fallback-database, hvis API'et ikke svarer
FALLBACK_KORT = [
    {"name": "Charizard", "set": "Base Set", "market": 2500, "low": 2000, "mid": 2600, "high": 3000},
    {"name": "Pikachu", "set": "Base Set", "market": 50, "low": 30, "mid": 60, "high": 80},
    {"name": "Mewtwo", "set": "Base Set", "market": 400, "low": 350, "mid": 420, "high": 500},
]

_session = requests.Session()
_session.headers.update({"User-Agent": "pokemon-pris-scanner/1.0"})


def hent_kort_fra_api(
    kortnavn: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S
) -> list[dict[str, Any]] | None:
    """
    Henter kortdata fra PokemonTCG.io API for et givent navn.

    Args:
        kortnavn: Kortnavn eller delvist navn der skal søges efter.

    Returns:
        list[dict]: Liste af kortobjekter fra API'et ved succes.
        None: Ved timeout eller forbindelsesfejl.

    Notes:
        Søgningen begrænses til de første 10 resultater.
    """
    params = {
        "q": f"name:{kortnavn}",
        "pageSize": 10,
    }

    print(f"Søger i PokemonTCG API efter: {kortnavn}")
    try:
        resp = _session.get(API_URL, params=params, timeout=timeout_s)
        resp.raise_for_status()  # smider fejl ved fx 404/500
        data = resp.json()
        cards = data.get("data", [])
        return cards if isinstance(cards, list) else []
    except requests.exceptions.Timeout:
        # Vi håndterer timeout højere oppe som "brug fallback"
        return None
    except requests.exceptions.ConnectionError:
        # Ingen internet / kan ikke nå API'et
        return None


def udtraek_priser(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Går igennem kort fra API'et og finder prisfelter, hvis de findes.

    Args:
        cards: Liste af kortobjekter fra PokemonTCG API.

    Returns:
        list[dict]: Liste med normaliserede prisresultater.
    """
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

        # Vi prøver nogle almindelige varianter: normal, holofoil, reverseHolofoil
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
    """
    Kører interaktiv CLI-loop for manuelt prisopslag.

    Brugeren kan indtaste et kortnavn, hvorefter programmet forsøger:
    1) API-opslag i PokemonTCG
    2) fallback til lokal eksempeldata ved netværksfejl

    Loopet stopper ved tomt input.
    """
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
                # API'et kunne ikke nås – vi bruger fallback-data
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