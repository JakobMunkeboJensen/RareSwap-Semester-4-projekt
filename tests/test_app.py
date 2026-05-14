"""Integrationstests for RareSwap Flask-applikationen."""

from __future__ import annotations

import pytest

from webapp import create_app


@pytest.fixture()
def app():
    """Opret en applikationsinstans konfigureret til in-memory-test."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    return app


@pytest.fixture()
def client(app):
    """Returner en testklient for den givne app."""
    return app.test_client()


def test_forside(client):
    r = client.get("/")
    assert r.status_code == 200


def test_login_side(client):
    r = client.get("/login")
    assert r.status_code == 200


def test_register_side(client):
    r = client.get("/register")
    assert r.status_code == 200


def test_status_side(client):
    r = client.get("/status")
    assert r.status_code == 200


def test_me_kraver_login(client):
    r = client.get("/me")
    assert r.status_code == 302


def test_registrer_bruger(client):
    r = client.post("/register", data={
        "username": "testbruger",
        "password": "hemligt123",
        "password2": "hemligt123",
    }, follow_redirects=True)
    assert r.status_code == 200


def test_registrer_for_kort_kodeord(client):
    r = client.post("/register", data={
        "username": "testbruger",
        "password": "abc",
        "password2": "abc",
    }, follow_redirects=True)
    assert b"mindst 6" in r.data


def test_registrer_kodeord_matcher_ikke(client):
    r = client.post("/register", data={
        "username": "testbruger",
        "password": "hemligt123",
        "password2": "anderledes",
    }, follow_redirects=True)
    assert b"matcher ikke" in r.data


def test_registrer_for_kort_brugernavn(client):
    r = client.post("/register", data={
        "username": "ab",
        "password": "hemligt123",
        "password2": "hemligt123",
    }, follow_redirects=True)
    assert b"mindst 3" in r.data


def test_login_forkert_kodeord(client):
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
    r = client.get("/api/lookup?q=")
    assert r.status_code == 200
    data = r.get_json()
    assert data["error"] is not None


def test_api_lookup_returnerer_json(client):
    r = client.get("/api/lookup?q=Pikachu")
    assert r.status_code == 200
    data = r.get_json()
    assert "rows" in data
    assert "query" in data
