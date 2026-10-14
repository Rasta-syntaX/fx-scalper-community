"""Integration tests for POST /api/scan through the real Flask application.

These exercise the whole path: HTTP request -> provider -> candles -> snapshot ->
rule engine -> persisted state -> bootstrap payload.
"""

import pytest

from app.server import app

FIXTURE = "backend/data/replay_sample.json"
FOREX_SYMBOL = [{"symbol": "frxEURUSD", "asset_class": "FOREX"}]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COMMUNITY_MARKET_SOURCE", "replay")
    monkeypatch.setenv("COMMUNITY_REPLAY_FILE", FIXTURE)
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        test_client.post("/api/reset")
        yield test_client


def test_health_responds(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_scan_without_symbols_reports_a_clear_error(client):
    response = client.post("/api/scan")
    assert response.status_code == 400
    body = response.get_json()
    assert body["ok"] is False
    assert body["scan"]["scanned"] == 0
    assert body["scan"]["errors"]


def test_scan_builds_snapshots_and_signals_from_candles(client):
    assert client.post("/api/config", json={"symbols": FOREX_SYMBOL}).status_code == 200

    response = client.post("/api/scan")
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["scan"]["scanned"] == 1
    assert body["scan"]["errors"] == []
    assert body["scan"]["source"] == "replay"
    assert body["stats"]["market_count"] == 1

    market = body["market"]
    assert market[0]["symbol"] == "frxEURUSD"
    assert market[0]["regime"] == "TRENDING"
    assert market[0]["decision"] == "BUY"
    assert market[0]["reason"]


def test_scan_persists_so_the_dashboard_bootstrap_shows_it(client):
    client.post("/api/config", json={"symbols": FOREX_SYMBOL})
    client.post("/api/scan")

    boot = client.get("/api/bootstrap").get_json()
    assert boot["stats"]["market_count"] == 1
    assert boot["stats"]["signal_count"] == 1
    assert boot["signals"][0]["symbol"] == "frxEURUSD"
    assert boot["last_scan"]["scanned"] == 1


def test_scan_reports_a_bad_symbol_without_losing_the_good_one(client):
    client.post(
        "/api/config",
        json={
            "symbols": [
                {"symbol": "frxEURUSD", "asset_class": "FOREX"},
                {"symbol": "frxNOPE", "asset_class": "FOREX"},
            ]
        },
    )
    body = client.post("/api/scan").get_json()
    assert body["scan"]["scanned"] == 1
    assert len(body["scan"]["errors"]) == 1
    assert body["scan"]["errors"][0]["symbol"] == "frxNOPE"


def test_scan_does_not_overwrite_good_snapshots_with_a_failed_scan(client, monkeypatch):
    client.post("/api/config", json={"symbols": FOREX_SYMBOL})
    assert client.post("/api/scan").get_json()["scan"]["scanned"] == 1

    # Break the data source rather than the symbol list: a scan that cannot get
    # candles must leave the last good snapshots in place.
    monkeypatch.setenv("COMMUNITY_REPLAY_FILE", "backend/data/does-not-exist.json")
    response = client.post("/api/scan")
    assert response.status_code == 400

    boot = client.get("/api/bootstrap").get_json()
    assert boot["stats"]["market_count"] == 1
    assert boot["market"][0]["symbol"] == "frxEURUSD"


def test_changing_symbols_drops_snapshots_for_symbols_no_longer_tracked(client):
    # Documents existing normalizer behaviour: snapshots are keyed by the
    # configured symbol list, so removing a symbol removes its snapshot.
    client.post("/api/config", json={"symbols": FOREX_SYMBOL})
    client.post("/api/scan")
    assert client.get("/api/bootstrap").get_json()["stats"]["market_count"] == 1

    client.post("/api/config", json={"symbols": [{"symbol": "frxUSDJPY", "asset_class": "FOREX"}]})
    assert client.get("/api/bootstrap").get_json()["stats"]["market_count"] == 0


def test_market_settings_round_trip_through_config(client):
    client.post(
        "/api/config",
        json={"market_source": "replay", "market_granularity": 900, "market_candle_count": 250},
    )
    settings = client.get("/api/bootstrap").get_json()["settings"]
    assert settings["market_source"] == "replay"
    assert settings["market_granularity"] == 900
    assert settings["market_candle_count"] == 250


def test_invalid_market_granularity_falls_back_for_a_clean_settings_response(client):
    client.post("/api/config", json={"market_granularity": 7})
    settings = client.get("/api/bootstrap").get_json()["settings"]
    assert settings["market_granularity"] == 300
