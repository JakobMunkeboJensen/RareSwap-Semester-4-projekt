"""Scan Pokémon-kort med webcam, læs kortnavnet med OCR og slå priser op."""

from __future__ import annotations

import argparse
import logging
import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from pokemon_pris_scanner import FALLBACK_KORT, hent_kort_fra_api, udtraek_priser

logger = logging.getLogger(__name__)

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover
    cv2 = None

try:
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover
    np = None

try:
    import pytesseract  # type: ignore
except ImportError:  # pragma: no cover
    pytesseract = None


KORT_SUFFIXES = [
    "vmax",
    "vstar",
    "v",
    "gx",
    "ex",
    "mega"
    "tag team",
]


def normaliser_kortnavn(navn: str) -> str:
    """Fjern sjældenhedsnøgleord og kortsufikser for at forbedre API-matchkvaliteten."""
    n = navn.strip()
    if not n:
        return n

    # Fjern almindelige varianter/keywords som ofte giver dårligt API-match.
    n = re.sub(r"\b(ultra rare|secret rare|rare)\b", "", n, flags=re.IGNORECASE).strip()
    for s in KORT_SUFFIXES:
        n = re.sub(rf"\b{re.escape(s)}\b", "", n, flags=re.IGNORECASE).strip()

    n = re.sub(r"\s+", " ", n).strip()
    return n


def _tjek_afhaengigheder() -> None:
    """Kast RuntimeError hvis påkrævede valgfri afhængigheder mangler."""
    if cv2 is None or np is None:
        raise RuntimeError("Installer `opencv-python` og `numpy` for kamera-behandling.")
    if pytesseract is None:
        raise RuntimeError("Installer `pytesseract` og `tesseract-ocr` for OCR.")


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Sorter fire hjørnepunkter som [øverst-venstre, øverst-højre, nederst-højre, nederst-venstre]."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]  # top-left
    rect[2] = pts[np.argmax(s)]  # bottom-right

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]  # top-right
    rect[3] = pts[np.argmax(diff)]  # bottom-left
    return rect


def _four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Anvend en perspektivtransformation for at rette et firkantområde til et rektangel."""
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect

    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_width = int(max(width_a, width_b))

    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_height = int(max(height_a, height_b))

    dst = np.array(
        [
            [0, 0],
            [max_width - 1, 0],
            [max_width - 1, max_height - 1],
            [0, max_height - 1],
        ],
        dtype="float32",
    )

    transform = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, transform, (max_width, max_height))
    return warped


def _detect_card_quad(frame: np.ndarray) -> np.ndarray | None:
    """Detektér kortets fire hjørnepunkter i billedet, eller returner None."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    edged = cv2.Canny(gray, 50, 150)
    edged = cv2.dilate(edged, np.ones((3, 3), np.uint8), iterations=1)
    edged = cv2.erode(edged, np.ones((3, 3), np.uint8), iterations=1)

    cnts = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]
    if not cnts:
        return None

    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:25]
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 0.02 * (frame.shape[0] * frame.shape[1]):
            continue

        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype("float32")

        # Fallback: minAreaRect giver altid 4 punkter.
        rect = cv2.minAreaRect(c)
        box = cv2.boxPoints(rect)
        if box is not None and len(box) == 4:
            return box.astype("float32")

    return None


def _preprocess_roi_for_ocr(roi_gray: np.ndarray) -> np.ndarray:
    """Opskalér, støjreducer og binarisér et gråtone-ROI til Tesseract."""
    roi = cv2.resize(roi_gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    roi = cv2.bilateralFilter(roi, 9, 75, 75)

    _, th = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if th.mean() < 127:  # mørk baggrund dominerer — inverter
        th = 255 - th
    return th


def _ocr_card_name(warped_image: np.ndarray) -> str:
    """Kør Tesseract på det øverste navnebånd af et rettet kortbillede og returner den bedste linje."""
    h, w = warped_image.shape[:2]
    if h < 100 or w < 100:
        return ""

    y1 = int(0.02 * h)
    y2 = int(0.28 * h)
    x1 = int(0.05 * w)
    x2 = int(0.95 * w)
    roi = warped_image[y1:y2, x1:x2]

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    processed = _preprocess_roi_for_ocr(gray)

    config = "--oem 3 --psm 7"
    text = pytesseract.image_to_string(processed, lang="eng", config=config)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    def score(line: str) -> int:
        # OCR-støj har typisk færre bogstaver end rigtigt tekst
        return sum(1 for c in line if c.isalpha()) + 2 * sum(1 for c in line if c.isdigit())

    best = max(lines, key=score)
    best = re.sub(r"[^A-Za-z0-9 .'-]", "", best).strip()
    best = re.sub(r"\s+", " ", best).strip()
    return best


def _capture_one_frame(camera_index: int, show_window: bool) -> np.ndarray:
    """Tag ét enkelt billede fra kameraet og returner det som numpy-array."""
    _tjek_afhaengigheder()

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Kunne ikke åbne kamera (index={camera_index}).")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    frame: np.ndarray | None = None
    if show_window:
        print("Kamera aktivt. Tryk `c` for at tage foto, `ESC` for at annullere.")
        while True:
            ok, f = cap.read()
            if not ok:
                continue
            frame = f
            cv2.imshow("Pokemon kort scan - tryk c", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("c"):
                break
            if key == 27:  # ESC
                frame = None
                break
    else:
        ok, f = cap.read()
        if ok:
            frame = f

    cap.release()
    if frame is None:
        raise RuntimeError("Ingen billedcapture gennemført (annulleret eller fejl).")
    return frame


def _print_priser_for_kortnavn(kortnavn: str) -> None:
    """Slå kortnavnet op i API'et og udskriv fundne priser; bruger fallback-data ved fejl."""
    cards = hent_kort_fra_api(kortnavn)
    if cards is None:
        print("Kunne ikke nå PokemonTCG API (ingen internet/timeout).")
        print("Bruger fallback-data i stedet.\n")
        priser = [k for k in FALLBACK_KORT if kortnavn.lower() in k["name"].lower()]
        if not priser:
            print("Ingen match i fallback-data.\n")
            return
    else:
        if not cards:
            print("Fandt ingen kort i API'et.\n")
            return
        priser = udtraek_priser(cards)
        if not priser:
            print("Fandt kort, men ingen prisdata tilgængelig.\n")
            return

    print(f"\nFundne kort og priser for '{kortnavn}':")
    for i, r in enumerate(priser, start=1):
        print(
            f"{i}. {r['name']} ({r['set']}) - "
            f"Market: {r['market']}, Low: {r['low']}, "
            f"Mid: {r['mid']}, High: {r['high']}"
        )
    print()


def _sharpness_score(img_bgr: np.ndarray) -> float:
    """Returner Laplacian-variansen af billedet som et mål for skarphed/fokus."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _capture_best_of_n(camera_index: int, n: int, show_window: bool) -> np.ndarray:
    """Tag N billeder og returner det skarpeste; Pi/USB-kameraers første frame er ofte sløret."""
    _tjek_afhaengigheder()
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Kunne ikke åbne kamera (index={camera_index}).")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    best_frame: np.ndarray | None = None
    best_score = -1.0

    if show_window:
        print("Kamera aktivt. Tryk `c` for at tage serie (skarpeste vælges), `ESC` for at annullere.")
        while True:
            ok, f = cap.read()
            if not ok:
                continue
            cv2.imshow("Pokemon kort scan - tryk c", f)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("c"):
                for _ in range(max(1, n)):
                    ok2, f2 = cap.read()
                    if not ok2:
                        continue
                    sc = _sharpness_score(f2)
                    if sc > best_score:
                        best_score = sc
                        best_frame = f2
                break
            if key == 27:
                best_frame = None
                break
    else:
        for _ in range(max(1, n)):
            ok, f = cap.read()
            if not ok:
                continue
            sc = _sharpness_score(f)
            if sc > best_score:
                best_score = sc
                best_frame = f

    cap.release()
    if best_frame is None:
        raise RuntimeError("Ingen billedcapture gennemført (annulleret eller fejl).")
    return best_frame


def _name_similarity(a: str, b: str) -> float:
    """Returner et 0–1 lighedsforhold mellem to kortnavne-strenge."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _rank_cards_by_name(cards: list[dict], query: str) -> list[dict]:
    """Sortér kort efter navnelighed med søgningen, højeste match først."""
    scored: list[tuple[float, dict]] = []
    qn = normaliser_kortnavn(query) or query
    for c in cards:
        name = str(c.get("name", "")).strip()
        if not name:
            continue
        s1 = _name_similarity(name, query)
        s2 = _name_similarity(name, qn)
        scored.append((max(s1, s2), c))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [c for _, c in scored]


def _choose_best_match(cards: list[dict], query: str) -> dict | None:
    """Vis de fem bedste matches og lad brugeren vælge; returner det valgte kort eller None."""
    ranked = _rank_cards_by_name(cards, query)[:5]
    if not ranked:
        return None

    print("\nTop matches:")
    for i, c in enumerate(ranked, start=1):
        name = c.get("name", "Ukendt navn")
        set_name = c.get("set", {}).get("name", "Ukendt sæt")
        number = c.get("number", "?")
        print(f"{i}. {name} ({set_name}) #{number}")

    choice = input("Vælg 1-5 (Enter = 1, 0 = annuller): ").strip()
    if choice == "0":
        return None
    if not choice:
        return ranked[0]
    try:
        idx = int(choice)
        if 1 <= idx <= len(ranked):
            return ranked[idx - 1]
    except ValueError:
        pass
    return ranked[0]


def scan_kort_med_kamera(camera_index: int, show_window: bool) -> None:
    """Tag et kortbillede, læs navnet med OCR og udskriv TCG-priser."""
    frame = _capture_best_of_n(camera_index=camera_index, n=8, show_window=show_window)
    quad = _detect_card_quad(frame)
    if quad is None:
        print("Kunne ikke finde kortets kanter. Prøv igen med bedre lys/afstand.")
        return

    warped = _four_point_transform(frame, quad)
    ocr_name = _ocr_card_name(warped)
    if not ocr_name:
        print("OCR kunne ikke læse et kortnavn. Prøv igen (evt. andet lys/vinkel).")
        return

    kandidater: list[str] = []
    for cand in [ocr_name, normaliser_kortnavn(ocr_name)]:
        cand = cand.strip()
        if cand and cand not in kandidater:
            kandidater.append(cand)

    print(f"OCR fandt: '{ocr_name}'")
    bruger_input = input(
        f"Ret søgeord (Enter = brug '{kandidater[0]}'): "
    ).strip()
    query = bruger_input if bruger_input else kandidater[0]
    query = query.strip()
    if not query:
        return

    cards = hent_kort_fra_api(query)
    if cards is None:
        _print_priser_for_kortnavn(query)
        return
    if not cards and normaliser_kortnavn(query) and normaliser_kortnavn(query).lower() != query.lower():
        cards = hent_kort_fra_api(normaliser_kortnavn(query)) or []

    if not cards:
        print("Fandt ingen kort i API'et. Prøv at rette søgeordet og scan igen.")
        return

    chosen = _choose_best_match(cards, query=query)
    if chosen is None:
        print("Afbryder.")
        return

    priser = udtraek_priser([chosen])
    if not priser:
        print("Valgt kort har ingen prisdata tilgængelig.")
        return

    r = priser[0]
    print(
        f"\nValgt: {r['name']} ({r['set']}) - "
        f"Market: {r['market']}, Low: {r['low']}, "
        f"Mid: {r['mid']}, High: {r['high']}"
    )
    print()


def scan_loop_manuel() -> None:
    """Interaktiv CLI-løkke til at slå kortpriser op ved at skrive navnet."""
    print("=== Pokémon Pris-Scanner (manuel) ===")
    print("Skriv navnet på et Pokémon-kort (eller en del af navnet).")
    print("Tomt input lukker programmet.\n")
    while True:
        kortnavn = input("Kortnavn: ").strip()
        if not kortnavn:
            print("Farvel!")
            return
        _print_priser_for_kortnavn(kortnavn)


def main(argv: Sequence[str] | None = None) -> None:
    """Analysér CLI-argumenter og videresend til kamera- eller manueltilstand."""
    parser = argparse.ArgumentParser(description="Pokemon kort scanner (kamera + OCR + prisopslag)")
    parser.add_argument("--camera", action="store_true", help="Brug kamera + OCR til at læse kortnavn")
    parser.add_argument("--camera-index", type=int, default=0, help="Kamera index (typisk 0)")
    parser.add_argument("--no-window", action="store_true", help="Tag foto uden preview-vindue")
    args = parser.parse_args(argv)

    if args.camera:
        scan_kort_med_kamera(camera_index=args.camera_index, show_window=not args.no_window)
    else:
        scan_loop_manuel()


if __name__ == "__main__":
    main()

