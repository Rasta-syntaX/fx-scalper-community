"""Tests for the snapshot builder and its contract with the rule engine.

The point of these tests is the frozen contract: a snapshot built from candles
must be accepted by app.server unchanged, and must drive a real decision.
"""

import math

import pytest

from app.market_data import Candle, MarketDataError, ReplayCandleProvider
from app.snapshot import (
    SNAPSHOT_KEYS,
    IndicatorSettings,
    build_market_snapshots,
    build_snapshot,
    compute_indicators,
    minimum_candles,
)
from app.server import evaluate_snapshot, normalize_market_snapshots

DRIFT = 0.00016
AMPLITUDE = 0.0024
PERIOD = 3.0
BALANCED = {"risk_profile": "balanced"}
SYMBOL_MAP = {"frxEURUSD": {"symbol": "frxEURUSD", "asset_class": "FOREX"}}


def closes(count=220, drift=DRIFT, amplitude=AMPLITUDE, period=PERIOD, base=1.08):
    return [base + drift * index + amplitude * math.sin(index / period) for index in range(count)]


def candles_for(make_candles, values, spread=0.0002):
    return [Candle.from_mapping(row) for row in make_candles(values, spread=spread)]


def test_minimum_candles_covers_the_longest_window():
    config = IndicatorSettings()
    assert minimum_candles(config) >= 2 * config.adx_period
    assert minimum_candles(config) >= config.bollinger_period
    assert minimum_candles(config) >= config.atr_period + config.atr_ratio_lookback


def test_indicator_settings_read_overrides_and_ignore_junk():
    config = IndicatorSettings.from_settings(
        {"ema_fast_period": 5, "ema_slow_period": "34", "bollinger_k": 2.5, "rsi_period": None}
    )
    assert config.ema_fast_period == 5
    assert config.ema_slow_period == 34
    assert config.bollinger_k == pytest.approx(2.5)
    assert config.rsi_period == IndicatorSettings().rsi_period


def test_build_snapshot_emits_exactly_the_engine_contract(make_candles):
    snapshot = build_snapshot("frxEURUSD", "FOREX", candles_for(make_candles, closes()))
    assert tuple(snapshot.keys()) == SNAPSHOT_KEYS
    assert snapshot["symbol"] == "frxEURUSD"
    assert snapshot["asset_class"] == "FOREX"
    for key in SNAPSHOT_KEYS:
        assert snapshot[key] is not None


def test_build_snapshot_normalises_the_values_the_engine_expects(make_candles):
    snapshot = build_snapshot("frxEURUSD", "FOREX", candles_for(make_candles, closes()))
    assert snapshot["price_vs_vwap"] in {"above", "below"}
    assert snapshot["candle_quality"] in {"clean", "stretched"}
    assert 0.0 <= snapshot["distance_to_band"] <= 1.0
    assert snapshot["atr_ratio"] > 0.0
    assert 0.0 <= snapshot["rsi"] <= 100.0
    assert 0.0 <= snapshot["adx"] <= 100.0


def test_build_snapshot_rejects_a_series_that_is_too_short(make_candles):
    short = candles_for(make_candles, closes(count=10))
    with pytest.raises(MarketDataError) as error:
        build_snapshot("frxEURUSD", "FOREX", short)
    assert "at least" in str(error.value)


def test_build_snapshot_requires_a_symbol(make_candles):
    with pytest.raises(MarketDataError):
        build_snapshot("", "FOREX", candles_for(make_candles, closes()))


def test_compute_indicators_rejects_an_empty_series():
    with pytest.raises(MarketDataError):
        compute_indicators([], IndicatorSettings())


def test_snapshot_survives_normalize_market_snapshots_unchanged(make_candles):
    snapshot = build_snapshot("frxEURUSD", "FOREX", candles_for(make_candles, closes()))
    rows = normalize_market_snapshots([snapshot], SYMBOL_MAP)
    assert len(rows) == 1
    assert set(rows[0].keys()) == set(SNAPSHOT_KEYS)
    assert rows[0]["symbol"] == snapshot["symbol"]
    assert rows[0]["price"] == pytest.approx(snapshot["price"])
    assert rows[0]["adx"] == pytest.approx(snapshot["adx"])
    assert rows[0]["price_vs_vwap"] == snapshot["price_vs_vwap"]


def test_a_trending_series_drives_the_engine_to_a_buy(make_candles):
    snapshot = build_snapshot("frxEURUSD", "FOREX", candles_for(make_candles, closes()))
    decision = evaluate_snapshot(dict(snapshot), BALANCED)
    assert decision["regime"] == "TRENDING"
    assert decision["decision"] == "BUY"
    assert decision["reason"]


def test_a_falling_series_drives_the_engine_to_a_sell(make_candles):
    # A straight mirror of the bullish fixture lands RSI outside the bearish
    # band, so this fixture is tuned to sit inside it with room to spare.
    values = closes(drift=-0.00010, amplitude=0.0024, period=3.5, base=1.18)
    snapshot = build_snapshot("frxEURUSD", "FOREX", candles_for(make_candles, values))
    decision = evaluate_snapshot(dict(snapshot), BALANCED)
    assert decision["regime"] == "TRENDING"
    assert decision["decision"] == "SELL"


def test_build_market_snapshots_uses_the_provider(make_candles):
    provider = ReplayCandleProvider({"frxEURUSD": make_candles(closes())}, granularity=300)
    result = build_market_snapshots(
        [{"symbol": "frxEURUSD", "asset_class": "FOREX"}], BALANCED, provider, granularity=300, count=200
    )
    assert result.ok
    assert len(result.snapshots) == 1
    assert result.errors == []


def test_build_market_snapshots_reports_a_missing_symbol_instead_of_hiding_it(make_candles):
    provider = ReplayCandleProvider({"frxEURUSD": make_candles(closes())}, granularity=300)
    result = build_market_snapshots(
        [{"symbol": "frxEURUSD", "asset_class": "FOREX"}, {"symbol": "frxUSDJPY", "asset_class": "FOREX"}],
        BALANCED,
        provider,
        granularity=300,
        count=200,
    )
    assert len(result.snapshots) == 1
    assert len(result.errors) == 1
    assert result.errors[0]["symbol"] == "frxUSDJPY"
