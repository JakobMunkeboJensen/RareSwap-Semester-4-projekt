"""
Raspberry Pi (Pi 5) Pokémon-kort scanner (MVP):

- Tager et billede fra Pi-kamera (Picamera2)
- Beskærer et "navnebånd" øverst i billedet (kan justeres)
- Kører OCR (Tesseract) for at gætte kortnavn
- Slår navnet op i et API (placeholder, nemt at skifte senere)
- Printer resultat i terminal
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

import cv2
import numpy as np
import pytesseract
import requests
from picamera2 import Picamera2

# Standard API-endpoint.
# Under udvikling kan du køre dit lokale Flask API (pokemon_api.py) på Pi'en
# og bruge http://127.0.0.1:5000/cards?name=<kortnavn>
API_BASE_URL = os.getenv("POKEMON_API_BASE_URL", "http://127.0.0.1:5000")
API_SEARCH_PATH = os.getenv("POKEMON_API_SEARCH_PATH", "/cards")


def _capture_frame(picam2: Picamera2) -> np.ndarray:
    frame = picam2.capture_array()  # typisk RGB
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


def _crop_name_band(img_bgr: np.ndarray) -> np.ndarray:
    """
    Antagelse: kortet ligger nogenlunde lige på bordet.
    Vi tager den øverste del af billedet, hvor navnet typisk står.

    Justér procenterne hvis du ser for meget støj eller for lidt af navnet.
    """
    h, w = img_bgr.shape[:2]
    y0 = int(h * 0.02)
    y1 = int(h * 0.22)
    x0 = int(w * 0.08)
    x1 = int(w * 0.92)
    return img_bgr[y0:y1, x0:x1]


def _preprocess_for_ocr(img_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    thr = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7
    )
    thr = cv2.morphologyEx(thr, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return thr


def _ocr_name(img_bin: np.ndarray) -> str:
    # PSM 7: antager én tekstlinje (navnet).
    text = pytesseract.image_to_string(img_bin, config="--oem 3 --psm 7")
    text = text.strip()
    text = re.sub(r"[^A-Za-z \-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def lookup_cards_from_api(name: str, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    """
    Placeholder API-opslag.

    Default matcher dit lokale Flask API i `pokemon_api.py`:
      GET {API_BASE_URL}/cards?name=<name>  ->  JSON liste

    Når du får et rigtigt API-link, kan du:
    - ændre POKEMON_API_BASE_URL env var, eller
    - ændre denne funktion til at matche det nye format.
    """
    url = f"{API_BASE_URL.rstrip('/')}{API_SEARCH_PATH}"
    resp = requests.get(url, params={"name": name}, timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def main() -> None:
    picam2 = Picamera2()
    picam2.configure(picam2.create_preview_configuration(main={"size": (1280, 720)}))
    picam2.start()
    time.sleep(1.0)

    print("=== Pi Pokémon-kort scanner (MVP) ===")
    print("Læg kortet på bordet (gerne ens afstand/retning).")
    print("Tryk ENTER for at scanne. Skriv 'q' + ENTER for at afslutte.\n")
    print(f"API: {API_BASE_URL.rstrip('/')}{API_SEARCH_PATH}\n")

    try:
        while True:
            cmd = input("Scan? (ENTER / q): ").strip().lower()
            if cmd == "q":
                break

            frame = _capture_frame(picam2)
            roi = _crop_name_band(frame)
            pre = _preprocess_for_ocr(roi)
            name_guess = _ocr_name(pre)

            if len(name_guess) < 3:
                print("Kunne ikke læse navn stabilt. Prøv mere lys/mindre genskin, eller justér crop.\n")
                continue

            print(f"Navn (OCR): {name_guess}")

            try:
                matches = lookup_cards_from_api(name_guess)
                if not matches:
                    print("Ingen match i API.\n")
                    continue

                print("Match i API:")
                for i, c in enumerate(matches, start=1):
                    nm = c.get("name", "?")
                    st = c.get("set", "?")
                    price = c.get("price_dkk", c.get("price", None))
                    print(f"{i}. {nm} ({st}) - pris: {price}")
                print()
            except requests.HTTPError as e:
                print(f"API-fejl (HTTP): {e}\n")
            except requests.RequestException as e:
                print(f"API-fejl (netværk): {e}\n")

    finally:
        picam2.stop()


if __name__ == "__main__":
    main()

