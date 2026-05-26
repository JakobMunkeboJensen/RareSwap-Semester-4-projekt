"""Integrationstests for RareSwap Flask-applikationen."""

from __future__ import annotations

import pytest

from webapp import create_app


@pytest.fixture()
def app():
    """Opret en applikationsinstans konfigureret til in-memory-test."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    return app


@pytest.fixture()
def client(app):
    """Returner en testklient for den givne app."""
    return app.test_client()


def test_forside(client):
    """Forsiden returnerer HTTP 200."""
    r = client.get("/")
    assert r.status_code == 200


def test_status_side(client):
    """Statussiden returnerer HTTP 200."""
    r = client.get("/status")
    assert r.status_code == 200


def test_api_lookup_uden_query(client):
    """API-opslag uden søgeterm returnerer en fejlbesked i JSON."""
    r = client.get("/api/lookup?q=")
    assert r.status_code == 200
    data = r.get_json()
    assert data["error"] is not None


def test_api_lookup_returnerer_json(client):
    """API-opslag med søgeterm returnerer JSON med felterne rows og query."""
    r = client.get("/api/lookup?q=Pikachu")
    assert r.status_code == 200
    data = r.get_json()
    assert "rows" in data
    assert "query" in data
