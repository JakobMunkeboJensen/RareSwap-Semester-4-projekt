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


def test_login_side(client):
    """Login-siden returnerer HTTP 200."""
    r = client.get("/login")
    assert r.status_code == 200


def test_register_side(client):
    """Registreringssiden returnerer HTTP 200."""
    r = client.get("/register")
    assert r.status_code == 200


def test_status_side(client):
    """Statussiden returnerer HTTP 200."""
    r = client.get("/status")
    assert r.status_code == 200


def test_me_kraver_login(client):
    """Profil-siden omdirigerer til login hvis brugeren ikke er logget ind."""
    r = client.get("/me")
    assert r.status_code == 302


def test_registrer_bruger(client):
    """Succesfuld registrering opretter brugeren og returnerer HTTP 200."""
    r = client.post("/register", data={
        "username": "testbruger",
        "password": "hemligt123",
        "password2": "hemligt123",
    }, follow_redirects=True)
    assert r.status_code == 200


def test_registrer_for_kort_kodeord(client):
    """Registrering med adgangskode under 6 tegn viser fejlbesked."""
    r = client.post("/register", data={
        "username": "testbruger",
        "password": "abc",
        "password2": "abc",
    }, follow_redirects=True)
    assert b"mindst 6" in r.data


def test_registrer_kodeord_matcher_ikke(client):
    """Registrering hvor adgangskoderne ikke matcher viser fejlbesked."""
    r = client.post("/register", data={
        "username": "testbruger",
        "password": "hemligt123",
        "password2": "anderledes",
    }, follow_redirects=True)
    assert b"matcher ikke" in r.data


def test_registrer_for_kort_brugernavn(client):
    """Registrering med brugernavn under 3 tegn viser fejlbesked."""
    r = client.post("/register", data={
        "username": "ab",
        "password": "hemligt123",
        "password2": "hemligt123",
    }, follow_redirects=True)
    assert b"mindst 3" in r.data


def test_login_forkert_kodeord(client):
    """Login med forkert adgangskode viser fejlbesked."""
    client.post("/register", data={
        "username": "testbruger",
        "password": "hemligt123",
        "password2": "hemligt123",
    })
    r = client.post("/login", data={
        "username": "testbruger",
        "password": "forkert",
    }, follow_redirects=True)
    assert b"Forkert" in r.data


def test_login_og_logout(client):
    """Brugeren kan logge ind og ud uden fejl."""
    client.post("/register", data={
        "username": "testbruger",
        "password": "hemligt123",
        "password2": "hemligt123",
    })
    r = client.post("/login", data={
        "username": "testbruger",
        "password": "hemligt123",
    }, follow_redirects=True)
    assert r.status_code == 200

    r = client.get("/logout", follow_redirects=True)
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
