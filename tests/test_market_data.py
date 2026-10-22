"""Unit tests for the market data providers."""

import json

import pytest

from app.market_data import (
    Candle,
    DerivCandleProvider,
    MarketDataError,
    ReplayCandleProvider,
    provider_from_settings,
    validate_granularity,
)


def test_validate_granularity_accepts_deriv_values_and_rejects_others():
    assert validate_granularity("300") == 300
    assert validate_granularity(3600) == 3600
    with pytest.raises(MarketDataError):
        validate_granularity(7)
    with pytest.raises(MarketDataError):
        validate_granularity("soon")


def test_candle_from_mapping_requires_ohlc():
    candle = Candle.from_mapping({"epoch": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5})
    assert candle.close == 1.5
    assert candle.volume is None
    with pytest.raises(MarketDataError):
        Candle.from_mapping({"epoch": 1, "open": 1.0, "high": 2.0, "low": 0.5})


def test_replay_provider_returns_the_requested_count(make_candles):
    closes = [1.0 + 0.001 * index for index in range(50)]
    provider = ReplayCandleProvider({"frxEURUSD": make_candles(closes)})
    candles = provider.get_candles("frxEURUSD", granularity=300, count=10)
    assert len(candles) == 10
    assert candles[-1].close == pytest.approx(round(closes[-1], 5), abs=1e-6)


def test_replay_provider_cycles_a_short_fixture(make_candles):
    provider = ReplayCandleProvider({"frxEURUSD": make_candles([1.0, 1.1, 1.2])})
    assert len(provider.get_candles("frxEURUSD", granularity=300, count=9)) == 9


def test_replay_provider_rejects_an_unknown_symbol(make_candles):
    provider = ReplayCandleProvider({"frxEURUSD": make_candles([1.0, 1.1])})
    with pytest.raises(MarketDataError):
        provider.get_candles("frxUSDJPY", granularity=300, count=2)


def test_replay_provider_reads_the_committed_sample_fixture():
    provider = ReplayCandleProvider.from_file("backend/data/replay_sample.json")
    candles = provider.get_candles("frxEURUSD", granularity=300, count=120)
    assert len(candles) == 120
    assert provider.granularity == 300


def test_replay_provider_from_file_rejects_a_missing_path():
    with pytest.raises(MarketDataError):
        ReplayCandleProvider.from_file("backend/data/does-not-exist.json")


def test_provider_from_settings_requires_a_file_for_replay():
    with pytest.raises(MarketDataError):
        provider_from_settings({"market_source": "replay"})


def test_provider_from_settings_builds_a_deriv_provider_with_app_id():
    provider = provider_from_settings({"deriv_app_id": "12345"})
    assert isinstance(provider, DerivCandleProvider)
    assert "app_id=12345" in provider.url
