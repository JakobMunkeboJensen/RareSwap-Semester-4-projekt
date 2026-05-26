"""Blueprint til kortprisopslag, valutakonvertering, prishistorik og statusside."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, TypedDict

import requests
from flask import Blueprint, Response, abort, jsonify, render_template, request, stream_with_context

from pokemon_pris_scanner import hent_kort_fra_api, udtraek_priser

from .extensions import csrf, db
from .models import PriceHistory

logger = logging.getLogger(__name__)

bp = Blueprint("pricing", __name__)

# Delt kamerainstans — kører i baggrunden så stream og scan ikke konflikter
_cam_lock: threading.Lock = threading.Lock()
_cam_frame: "Any" = None
_cam_thread: "threading.Thread | None" = None
_cam_active: bool = False
_picam2_global: "Any" = None
_cam_scan_event: threading.Event = threading.Event()


def _camera_loop() -> None:
    global _cam_frame, _cam_active, _picam2_global
    try:
        import cv2
        from picamera2 import Picamera2
    except ImportError as e:
        logger.error("Pi-kamera import fejl: %s", e)
        return
    try:
        picam2 = Picamera2()
        preview_cfg = picam2.create_preview_configuration(main={"size": (854, 480)})
        picam2.configure(preview_cfg)
        picam2.start()
        _picam2_global = picam2
        logger.info("Pi-kamera startet OK")
        time.sleep(1.5)
        while _cam_active:
            if _cam_scan_event.is_set():
                time.sleep(0.05)
                continue
            frame = picam2.capture_array()
            bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            with _cam_lock:
                _cam_frame = bgr
    except Exception:
        logger.exception("Pi-kamera loop fejl")
    finally:
        try:
            picam2.stop()
            picam2.close()
        except Exception:
            pass
        _picam2_global = None
        with _cam_lock:
            _cam_frame = None
        logger.info("Pi-kamera stoppet")


def _ensure_camera() -> bool:
    global _cam_thread, _cam_active
    try:
        from picamera2 import Picamera2  # noqa: F401
    except ImportError:
        return False
    if _cam_thread is None or not _cam_thread.is_alive():
        _cam_active = True
        _cam_thread = threading.Thread(target=_camera_loop, daemon=True)
        _cam_thread.start()
    return True

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
    """Konverter en EUR-pris til den ønskede valuta via cachet kurs; returner None ved manglende kurs."""
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
    """Konverter en DKK-pris til den ønskede valuta via EUR-base-kurs; returner None ved manglende kurs."""
    if v_dkk is None:
        return None
    if currency == "DKK":
        return round(v_dkk, 2)
    # DKK -> EUR via EUR-basekurser (DKK pr. EUR), derefter EUR -> målvaluta
    rates = _get_rates("EUR")
    dkk_per_eur = float(rates.get("DKK") or 0.0)
    if dkk_per_eur <= 0:
        return None
    eur = v_dkk / dkk_per_eur
    return _convert_from_eur(eur, currency=currency)


def _lookup_cards_from_local_api(name: str) -> list[dict[str, Any]] | None:
    """Hent kort fra den lokale pokemon_api.py-service; returner None ved forbindelsesfejl."""
    base = LOCAL_CARD_API_BASE_URL.rstrip("/")
    try:
        resp = requests.get(f"{base}/cards", params={"name": name}, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return None


def _convert(v_usd: float | None, fx: float) -> float | None:
    """Gang en USD-pris med valutakursen og afrund til to decimaler; returner None for None-input."""
    if v_usd is None:
        return None
    return round(v_usd * fx, 2)



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
    """Slå kortpriser op via PokemonTCG API eller lokal API og returner et LookupResult."""
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


@bp.post("/api/scan-card-image")
@csrf.exempt
def scan_card_image():
    """Modtag et base64-billede, kør Python OCR-pipeline og returner kortnavnet."""
    try:
        import base64

        import cv2
        import numpy as np
    except ImportError:
        return jsonify({"error": "Server-side OCR ikke tilgængelig (mangler cv2/numpy)."}), 503

    try:
        from pokemon_camera_scanner import normaliser_kortnavn
    except ImportError:
        return jsonify({"error": "pokemon_camera_scanner ikke tilgængelig."}), 503

    data = request.get_json(silent=True) or {}
    image_data = data.get("image", "")
    if not image_data:
        return jsonify({"error": "Ingen billeddata."}), 400

    # Fjern data-URL prefix hvis til stede
    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    try:
        raw_bytes = base64.b64decode(image_data)
        arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return jsonify({"error": "Kunne ikke afkode billede."}), 400

    if frame is None:
        return jsonify({"error": "Ugyldigt billedformat."}), 400

    try:
        import pytesseract
    except ImportError:
        return jsonify({"error": "pytesseract ikke tilgængelig."}), 503

    import re

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # 3x upscale giver Tesseract markant bedre resultater på små tekstbånd
    gray = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)

    # Byg tre preprocessede varianter og tag den med bedst gennemsnits-confidence
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    variants = [
        clahe.apply(gray),                                          # CLAHE gråtone
        cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],  # Otsu
        255 - cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],  # Inverteret Otsu
    ]

    def _run_ocr(img: np.ndarray) -> tuple[str, float]:
        cfg = "--oem 3 --psm 7"
        d = pytesseract.image_to_data(
            img, lang="eng", config=cfg,
            output_type=pytesseract.Output.DICT,
        )
        words = [w for w, c in zip(d["text"], d["conf"], strict=False) if w.strip() and int(c) > 0]
        confs = [int(c) for c in d["conf"] if str(c) not in ("-1", "") and int(c) >= 0]
        avg = sum(confs) / len(confs) if confs else 0.0
        return " ".join(words), avg

    best_text, best_conf = "", -1.0
    for variant in variants:
        text, conf = _run_ocr(variant)
        logger.info("scan-card-image: conf=%.1f text=%r", conf, text)
        if conf > best_conf:
            best_conf, best_text = conf, text

    cleaned = re.sub(r"[^A-Za-z0-9 .'\-]", "", best_text).strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    best_line = max(lines, key=lambda line: sum(1 for c in line if c.isalpha())) if lines else cleaned

    name = normaliser_kortnavn(best_line) if best_line else ""
    if not name:
        name = best_line

    logger.info("scan-card-image: final name=%r (conf=%.1f)", name, best_conf)
    return jsonify({"name": name, "raw": best_text})


@bp.post("/api/scan-card-ai")
@csrf.exempt
def scan_card_ai():
    """Modtag et base64-billede, send til Claude vision og returner kortnavnet."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY ikke sat. Sæt env-variablen og genstart serveren."}), 503

    try:
        import anthropic
    except ImportError:
        return jsonify({"error": "anthropic pakken er ikke installeret. Kør: pip install anthropic"}), 503

    data = request.get_json(silent=True) or {}
    image_data = data.get("image", "")
    if not image_data:
        return jsonify({"error": "Ingen billeddata."}), 400

    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    try:
        client = anthropic.Anthropic(api_key=api_key)
        # Detect media type from data-URL prefix (jpeg or png)
        media_type = "image/jpeg"
        if image_data_raw := data.get("image", ""):
            if image_data_raw.startswith("data:image/png"):
                media_type = "image/png"

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=64,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_data},
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a webcam photo of a Pokemon Trading Card Game (TCG) card. "
                            "Look carefully at the card name printed at the top and identify the set from the card design, border, set symbol, and artwork style. "
                            "Include older sets like Base Set, Jungle, Fossil, Team Rocket, Gym Heroes, Gym Challenge, Neo Genesis, Neo Discovery, Neo Revelation, Neo Destiny, Expedition, Aquapolis, Skyridge, and all EX, Diamond & Pearl, HeartGold SoulSilver, Black & White, XY, Sun & Moon, Sword & Shield, and Scarlet & Violet series. "
                            "Always give your best guess even if uncertain. Never reply with Unknown. "
                            "Reply ONLY in this format:\nNAME: <pokemon name>\nSET: <set name>"
                        ),
                    },
                ],
            }],
        )
        raw = response.content[0].text.strip() if response.content else ""
        name, card_set = "", ""
        for line in raw.splitlines():
            if line.upper().startswith("NAME:"):
                name = line.split(":", 1)[1].strip()
            elif line.upper().startswith("SET:"):
                card_set = line.split(":", 1)[1].strip()
        if not name:
            name = raw
    except Exception as e:
        logger.exception("scan-card-ai fejl")
        return jsonify({"error": str(e)}), 500

    logger.info("scan-card-ai: name=%r set=%r", name, card_set)
    return jsonify({"name": name, "set": card_set})


@bp.get("/api/pi-camera-stream")
def pi_camera_stream():
    """Stream live MJPEG fra Pi-kameraet via delt kamerainstans."""
    if not _ensure_camera():
        abort(503)

    def generate():
        import cv2
        time.sleep(2.0)
        while True:
            with _cam_lock:
                frame = _cam_frame
            if frame is not None:
                small = cv2.resize(frame, (854, 480))
                _, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
            time.sleep(0.05)

    return Response(stream_with_context(generate()), mimetype="multipart/x-mixed-replace; boundary=frame")


@bp.post("/api/pi-camera-scan")
@csrf.exempt
def pi_camera_scan():
    """Tag et billede fra den delte kamerainstans og scan det med Claude AI."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY ikke sat."}), 503

    if not _ensure_camera():
        return jsonify({"error": "Pi-kamera ikke tilgængeligt på denne enhed."}), 503

    # Vent på at kameraet er klar
    for _ in range(50):
        if _picam2_global is not None:
            break
        time.sleep(0.1)

    if _picam2_global is None:
        return jsonify({"error": "Kameraet startede ikke — prøv igen."}), 503

    try:
        import base64
        import cv2
        _cam_scan_event.set()
        time.sleep(0.15)
        still_cfg = _picam2_global.create_still_configuration(main={"size": (1920, 1080)})
        frame = _picam2_global.switch_mode_and_capture_array(still_cfg)
        _picam2_global.switch_mode(_picam2_global.create_preview_configuration(main={"size": (854, 480)}))
        _cam_scan_event.clear()
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        image_data = base64.b64encode(buf.tobytes()).decode("utf-8")
    except Exception as e:
        _cam_scan_event.clear()
        return jsonify({"error": f"Kunne ikke tage billede: {e}"}), 500

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=64,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                    {"type": "text", "text": (
                        "This is a photo of a Pokemon Trading Card Game (TCG) card. "
                        "Look carefully at the card name printed at the top and identify the set from the card design, border, set symbol, and artwork style. "
                        "Include older sets like Base Set, Jungle, Fossil, Team Rocket, Gym Heroes, Gym Challenge, Neo Genesis, Neo Discovery, Neo Revelation, Neo Destiny, Expedition, Aquapolis, Skyridge, and all EX, Diamond & Pearl, HeartGold SoulSilver, Black & White, XY, Sun & Moon, Sword & Shield, and Scarlet & Violet series. "
                        "Always give your best guess even if uncertain. Never reply with Unknown. "
                        "Reply ONLY in this format:\nNAME: <pokemon name>\nSET: <set name>"
                    )},
                ],
            }],
        )
        raw = response.content[0].text.strip() if response.content else ""
        name, card_set = "", ""
        for line in raw.splitlines():
            if line.upper().startswith("NAME:"):
                name = line.split(":", 1)[1].strip()
            elif line.upper().startswith("SET:"):
                card_set = line.split(":", 1)[1].strip()
        if not name:
            name = raw
    except Exception as e:
        logger.exception("pi-camera-scan AI fejl")
        return jsonify({"error": str(e)}), 500

    logger.info("pi-camera-scan: name=%r set=%r", name, card_set)
    return jsonify({"name": name, "set": card_set})


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

