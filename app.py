"""Indgangspunkt for RareSwap Flask-webapplikationen."""

from __future__ import annotations

import logging

from webapp import create_app

app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=8000, debug=True)

