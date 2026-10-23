"""Automated trading loop: direction, daily limits, kill switch, paper + broker adapter."""

import json
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
    assert auto["day"] == "2026-01-05" and auto["realized_pnl"] == 0.0
    assert auto["trades_today"] == 0 and auto["halted_reason"] == "" and auto["loss_streak"] == 0


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


def test_guards_halt_or_pause():
    auto = autotrader.default_auto_state()
    assert autotrader.blocking_reason(auto, {}, NOW) == ("", False)
    auto["trades_today"] = 3
    assert autotrader.blocking_reason(auto, {"max_trades_per_day": 3}, NOW)[1] is True
    auto = autotrader.default_auto_state()
    for pnl in (-1, -1):
        autotrader.record_close(
            auto, {"loss_cooldown_minutes": 15}, symbol="A", side="BUY", pnl=pnl, now=NOW, mode="paper"
        )
    reason, halt = autotrader.blocking_reason(auto, {"max_loss_streak": 2}, NOW)
    assert "2 losses in a row" in reason and halt
    reason, halt = autotrader.blocking_reason(auto, {}, NOW + timedelta(minutes=5))
    assert "Cooling down" in reason and not halt
    assert autotrader.blocking_reason(auto, {}, NOW + timedelta(minutes=16)) == ("", False)


def test_trading_hours_window():
    assert autotrader.in_trading_hours(NOW, 8, 17)
    assert not autotrader.in_trading_hours(NOW, 13, 17)
    assert autotrader.in_trading_hours(NOW, 22, 13)
    assert not autotrader.in_trading_hours(NOW, 22, 6)
    assert autotrader.in_trading_hours(NOW, 0, 0)
    hours = {"trading_hours_start": 13, "trading_hours_end": 17}
    reason, halt = autotrader.blocking_reason(autotrader.default_auto_state(), hours, NOW)
    assert "Outside trading hours (13:00-17:00 UTC)" in reason and not halt


def test_record_close_and_performance():
    auto = autotrader.default_auto_state()
    for symbol, pnl in (("A", 2.0), ("A", -1.0), ("B", 0.5)):
        autotrader.record_close(auto, {}, symbol=symbol, side="BUY", pnl=pnl, now=NOW, mode="paper")
    assert auto["realized_pnl"] == 1.5 and auto["wins_today"] == 2 and auto["losses_today"] == 1
    assert auto["loss_streak"] == 0
    stats = autotrader.performance(auto["closed_trades"])
    assert stats["trades"] == 3 and stats["equity_curve"] == [2.0, 1.0, 1.5]
    assert stats["by_symbol"][0] == {"symbol": "A", "trades": 2, "wins": 1, "pnl": 1.0, "win_rate": 0.5}


def test_daily_summary_event_on_rollover(client):
    client.post("/api/auto/start", json={"mode": "paper"})
    state = server.load_state()
    state["auto_trader"].update({"day": "2026-01-04", "trades_today": 2, "wins_today": 1, "losses_today": 1,
                                 "realized_pnl": 0.4})
    server.save_state(state)
    auto = server.auto_trade_tick(now=NOW)
    assert auto["day"] == "2026-01-05"
    summary = [row for row in server.load_state()["trade_history"] if row["type"] == "DAILY_SUMMARY"]
    assert summary and summary[0]["note"].startswith("2026-01-04: 2 trades opened, 1 won / 1 lost")


def test_max_trades_per_day_halts(client):
    client.post("/api/config", json={"max_trades_per_day": 1})
    client.post("/api/auto/start", json={"mode": "paper"})
    assert server.auto_trade_tick(now=NOW)["trades_today"] == 1
    assert "Max trades per day" in server.auto_trade_tick(now=NOW)["halted_reason"]
    assert server.bootstrap_payload(server.load_state())["auto_performance"]["trades"] == 0


def test_backtest_payout_scoring(client):
    client.post("/api/backtests/run", json={"payout_pct": 85, "candle_count": 1000})
    result = server.load_state()["last_backtest"]["candle_backtest"]["results"][0]
    assert result["trades"] > 0
    assert result["break_even_win_rate"] == round(1 / 1.85, 4)
    assert result["net_per_stake"] == round(result["wins"] * 0.85 - result["losses"], 4)
    assert len(result["equity_curve"]) == result["trades"]


def test_cli_backtest(capsys):
    from app import cli

    code = cli.main(["backtest", "--replay", REPLAY, "--symbol", "frxEURUSD", "--payout", "85", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["results"][0]["symbol"] == "frxEURUSD" and report["results"][0]["payout"] == 0.85
    assert cli.main(["backtest", "--replay", REPLAY, "--symbol", "frxEURUSD"]) == 0
    assert "net/$1" not in capsys.readouterr().out
