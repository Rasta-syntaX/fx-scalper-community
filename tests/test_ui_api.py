import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app import server  # noqa: E402


@pytest.fixture
def client():
    server.app.config.update(TESTING=True)
    with server.app.test_client() as test_client:
        test_client.post("/api/reset")
        yield test_client
        test_client.post("/api/reset")


def test_demo_loads_replay_and_paper_only(client):
    body = client.post("/api/demo").get_json()
    assert "Demo data loaded" in body["message"]
    settings = client.get("/api/bootstrap").get_json()["settings"]
    assert settings["market_source"] == "replay" and settings["live_trading_enabled"] is False
    assert [row["symbol"] for row in settings["symbols"]] == ["frxEURUSD"]


def test_candles_and_journal_routes(client):
    client.post("/api/demo")
    candles = client.get("/api/candles?symbol=frxEURUSD&count=50").get_json()
    assert candles["source"] == "replay" and len(candles["candles"]) == 50
    assert set(candles["candles"][0]) == {"epoch", "open", "high", "low", "close"}
    assert client.get("/api/candles?symbol=NOPE").status_code == 404
    client.post("/api/paper-trades/open", json={"symbol": "frxEURUSD", "side": "BUY", "exposure": 10})
    entries = client.get("/api/journal?limit=5").get_json()["entries"]
    assert isinstance(entries, list) and len(entries) <= 5
