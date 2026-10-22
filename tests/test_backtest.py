"""Walk-forward candle backtest: no look-ahead, honest stats, real fixture."""

import os

import pytest

from app import server
from app.backtest import contiguous_tail, run_backtest
from app.market_data import Candle, MarketDataError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPLAY = os.path.join(ROOT, "backend", "data", "replay_sample.json")


def as_candles(rows):
    return [Candle.from_mapping(row) for row in rows]


def always(decision):
    return lambda snapshot, settings: {"decision": decision}


@pytest.fixture
def rising(make_candles):
    return as_candles(make_candles([1.0 + i * 0.001 for i in range(160)]))


def test_entries_use_next_open_and_exit_after_horizon(rising):
    result = run_backtest("X", "FOREX", rising, {}, always("BUY"), horizon=5, window=100)
    first = result["recent_trades"][0]
    assert first["entry"] == round(rising[100].open, 5)
    assert first["exit"] == round(rising[104].close, 5)
    assert result["trades"] == (len(rising) - 100) // 5
    assert result["win_rate"] == 1.0 and result["max_drawdown_pct"] == 0.0


def test_sell_signals_profit_from_falling_prices(make_candles):
    falling = as_candles(make_candles([2.0 - i * 0.001 for i in range(160)]))
    result = run_backtest("X", "FOREX", falling, {}, always("SELL"), horizon=5, window=100)
    assert result["trades"] and result["wins"] == result["trades"]
    assert result["total_return_pct"] > 0


def test_direction_filter_blocks_disallowed_side(rising):
    result = run_backtest("X", "FOREX", rising, {}, always("SELL"), horizon=5, window=100, direction="buy")
    assert result["trades"] == 0 and result["win_rate"] is None


def test_hold_never_trades(rising):
    result = run_backtest("X", "FOREX", rising, {}, always("HOLD"), horizon=5, window=100)
    assert result["signals"] == 0 and result["bars_evaluated"] > 0


def test_cycled_replay_seam_is_dropped(rising):
    assert contiguous_tail(rising + rising) == rising


def test_too_few_candles_is_an_error(rising):
    with pytest.raises(MarketDataError):
        run_backtest("X", "FOREX", rising[:50], {}, always("BUY"))


@pytest.fixture
def client():
    server.app.config.update(TESTING=True)
    with server.app.test_client() as test_client:
        test_client.post("/api/reset")
        yield test_client


def test_endpoint_backtests_replay_candles(client):
    client.post(
        "/api/config",
        json={
            "symbols": [{"symbol": "frxEURUSD", "asset_class": "FOREX"}],
            "market_source": "replay",
            "market_replay_file": REPLAY,
        },
    )
    summary = client.post("/api/backtests/run", json={"horizon_bars": 3}).get_json()["summary"]
    report = summary["candle_backtest"]
    assert report["source"] == "replay" and report["errors"] == []
    row = report["results"][0]
    assert row["symbol"] == "frxEURUSD" and row["candles"] == 220 and row["horizon_bars"] == 3
    assert row["bars_evaluated"] > 0
    assert summary["scenario_total"] == 3


def test_endpoint_reports_missing_symbols(client):
    report = client.post("/api/backtests/run").get_json()["summary"]["candle_backtest"]
    assert report["results"] == [] and "No symbols" in report["errors"][0]["error"]
