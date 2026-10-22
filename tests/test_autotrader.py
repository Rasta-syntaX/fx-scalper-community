"""Automated trading loop: direction, daily limits, kill switch, paper + broker adapter."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from app import autotrader, server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPLAY = os.path.join(ROOT, "backend", "data", "replay_sample.json")
NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def test_limits():
    auto = {"realized_pnl": 10.0, "pending_live": []}
    assert "profit target" in autotrader.limit_breached(auto, {"daily_profit_target": 10})
    assert autotrader.limit_breached(auto, {"daily_profit_target": 0, "daily_loss_limit": 0}) == ""
    losing = {"realized_pnl": -3.0, "pending_live": [{"stake": 2.0}]}
    assert "loss limit" in autotrader.limit_breached(losing, {"daily_loss_limit": 5})
    assert autotrader.limit_breached(losing, {"daily_loss_limit": 6}) == ""


def test_pick_entries_respects_direction_held_and_room():
    market = [
        {"symbol": "A", "decision": "BUY"},
        {"symbol": "B", "decision": "SELL"},
        {"symbol": "C", "decision": "BUY"},
        {"symbol": "D", "decision": "HOLD"},
    ]
    held = [{"symbol": "A"}]
    picks = autotrader.pick_entries(market, held, {"trade_direction": "buy", "max_open_positions": 6}, 1)
    assert [row["symbol"] for row in picks] == ["C"]
    picks = autotrader.pick_entries(market, [], {"trade_direction": "both", "max_open_positions": 2}, 0)
    assert [row["symbol"] for row in picks] == ["A", "B"]


def test_roll_day_resets_counters():
    auto = {"day": "2026-01-04", "realized_pnl": -9.0, "trades_today": 4, "halted_reason": "x"}
    autotrader.roll_day(auto, NOW)
    assert auto == {"day": "2026-01-05", "realized_pnl": 0.0, "trades_today": 0, "halted_reason": ""}


def test_paper_pnl_sign():
    position = {"entry_price": 1.0, "exposure": 100.0, "side": "SELL"}
    assert autotrader.paper_pnl(position, 0.99) == 1.0


@pytest.fixture
def client():
    server.app.config.update(TESTING=True)
    with server.app.test_client() as test_client:
        test_client.post("/api/reset")
        test_client.post(
            "/api/config",
            json={
                "symbols": [{"symbol": "frxEURUSD", "asset_class": "FOREX"}],
                "market_source": "replay",
                "market_replay_file": REPLAY,
                "auto_hold_minutes": 10,
            },
        )
        yield test_client
        test_client.post("/api/auto/stop")


def replay_decision():
    state = server.load_state()
    server.run_market_scan(state)
    return server.market_view(state["settings"])[0]["decision"]


def test_paper_loop_opens_then_closes_after_hold(client):
    decision = replay_decision()
    assert decision in {"BUY", "SELL"}, "replay fixture should produce a signal"
    assert client.post("/api/auto/start", json={"mode": "paper"}).status_code == 200
    auto = server.auto_trade_tick(now=NOW)
    state = server.load_state()
    assert auto["trades_today"] == 1
    assert [p["symbol"] for p in state["portfolio"] if p["auto"]] == ["frxEURUSD"]
    server.auto_trade_tick(now=datetime.now(timezone.utc) + timedelta(minutes=11))
    types = [row["type"] for row in server.load_state()["trade_history"]]
    assert "AUTO_CLOSE" in types and "AUTO_OPEN" in types and "AUTO_START" in types


def test_direction_filter_blocks_signal(client):
    decision = replay_decision()
    client.post("/api/config", json={"trade_direction": "sell" if decision == "BUY" else "buy"})
    client.post("/api/auto/start", json={"mode": "paper"})
    assert server.auto_trade_tick(now=NOW)["trades_today"] == 0


def test_stop_is_a_kill_switch(client):
    client.post("/api/auto/start", json={"mode": "paper"})
    client.post("/api/auto/stop")
    auto = server.auto_trade_tick(now=NOW)
    assert auto["running"] is False and auto["trades_today"] == 0
    assert server.load_state()["portfolio"] == []


def test_live_requires_opt_in(client):
    response = client.post("/api/auto/start", json={"mode": "live"})
    assert response.status_code == 400 and "live trading" in response.get_json()["error"].lower()


class FakeBroker:
    name = "fake"
    profit = None

    def open_trade(self, *, symbol, side, amount, **options):
        return {"ref": "42", "price": amount, "contract_type": "CALL"}

    def trade_status(self, ref):
        return {"settled": FakeBroker.profit is not None, "profit": FakeBroker.profit}

    def close(self):
        pass


def test_live_loop_uses_broker_adapter_and_halts_on_loss(client, monkeypatch):
    monkeypatch.setattr(server, "live_broker_from_settings", lambda settings: FakeBroker())
    client.post("/api/config", json={"live_trading_enabled": True, "live_trade_stake": 2, "daily_loss_limit": 2})
    assert client.post("/api/auto/start", json={"mode": "live"}).status_code == 200
    FakeBroker.profit = None
    auto = server.auto_trade_tick(now=NOW)
    assert [item["ref"] for item in auto["pending_live"]] == ["42"]
    assert "loss limit" in server.auto_trade_tick(now=NOW)["halted_reason"]
    FakeBroker.profit = -2.0
    auto = server.auto_trade_tick(now=NOW)
    assert auto["realized_pnl"] == -2.0 and auto["pending_live"] == []
    assert auto["trades_today"] == 1
    types = [row["type"] for row in server.load_state()["trade_history"]]
    assert "LIVE_SETTLED" in types and "AUTO_HALT" in types
