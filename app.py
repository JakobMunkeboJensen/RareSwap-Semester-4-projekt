"""Indgangspunkt for RareSwap Flask-webapplikationen."""

from __future__ import annotations

import logging
import os
from pathlib import Path

# Indlæs .env-fil hvis den findes (simpel implementering uden python-dotenv)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from webapp import create_app  # noqa: E402

app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=8000, debug=True)

