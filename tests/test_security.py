"""The Deriv token must never be echoed to clients, and the optional API key must gate /api/*."""

import pytest

from app.server import app

TOKEN = "pat_super_secret_token_value"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("COMMUNITY_API_KEY", raising=False)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        test_client.post("/api/reset")
        yield test_client


def test_config_and_bootstrap_never_return_the_token(client):
    saved = client.post("/api/config", json={"deriv_app_id": "1089", "deriv_token": TOKEN})
    assert saved.status_code == 200
    assert TOKEN not in saved.get_data(as_text=True)
    assert saved.get_json()["settings"]["deriv_token_set"] is True

    boot = client.get("/api/bootstrap")
    assert TOKEN not in boot.get_data(as_text=True)
    settings = boot.get_json()["settings"]
    assert settings["deriv_token"] == ""
    assert settings["deriv_token_set"] is True
    assert settings["deriv_token_mode"] == "pat"


def test_saving_without_a_token_keeps_the_stored_one(client):
    client.post("/api/config", json={"deriv_app_id": "1089", "deriv_token": TOKEN})
    client.post("/api/config", json={"deriv_token": "", "risk_profile": "conservative"})
    from app.server import load_state

    assert load_state()["settings"]["deriv_token"] == TOKEN


def test_clear_deriv_token_forgets_it(client):
    client.post("/api/config", json={"deriv_token": TOKEN})
    cleared = client.post("/api/config", json={"clear_deriv_token": True})
    assert cleared.get_json()["settings"]["deriv_token_set"] is False


def test_api_key_is_optional_by_default(client):
    assert client.get("/api/bootstrap").status_code == 200


def test_api_key_gates_everything_but_health(client, monkeypatch):
    monkeypatch.setenv("COMMUNITY_API_KEY", "letmein")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/bootstrap").status_code == 401
    assert client.get("/api/bootstrap", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/api/live-trades/open", json={}).status_code == 401
    assert client.get("/api/bootstrap", headers={"X-API-Key": "letmein"}).status_code == 200


def test_cors_only_allows_local_dashboard_origins_by_default(client):
    allowed = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
    blocked = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in blocked.headers
