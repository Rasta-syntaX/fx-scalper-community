"""Unit tests for the indicator math."""

import pytest

from app import indicators


def test_sma_matches_hand_computed_values():
    assert indicators.sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_sma_returns_all_none_when_series_is_too_short():
    assert indicators.sma([1, 2], 3) == [None, None]


def test_ema_seeds_on_sma_then_smooths():
    assert indicators.ema([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_ema_of_a_flat_series_is_that_constant():
    values = indicators.ema([7.0] * 10, 3)
    assert values[2] == 7.0
    assert values[-1] == pytest.approx(7.0)


def test_rsi_is_100_when_price_only_rises():
    values = indicators.rsi(list(range(1, 30)), 14)
    assert values[-1] == pytest.approx(100.0)


def test_rsi_is_50_when_price_never_moves():
    values = indicators.rsi([5.0] * 30, 14)
    assert values[-1] == pytest.approx(50.0)


def test_rsi_stays_inside_bounds_on_an_oscillating_series():
    closes = [100 + (3 if index % 2 else -3) for index in range(60)]
    for value in indicators.rsi(closes, 14):
        if value is not None:
            assert 0.0 <= value <= 100.0


def test_true_range_uses_previous_close():
    ranges = indicators.true_range([10.0, 12.0], [8.0, 9.0], [9.0, 11.0])
    assert ranges[0] == pytest.approx(2.0)
    assert ranges[1] == pytest.approx(max(3.0, abs(12.0 - 9.0), abs(9.0 - 9.0)))


def test_atr_equals_the_constant_range_when_every_candle_is_identical():
    highs = [1.01] * 40
    lows = [0.99] * 40
    closes = [1.0] * 40
    values = indicators.atr(highs, lows, closes, 14)
    assert values[13] == pytest.approx(0.02)
    assert values[-1] == pytest.approx(0.02)


def test_adx_is_100_on_a_perfectly_one_directional_trend():
    closes = [1.0 + 0.001 * index for index in range(80)]
    highs = [value + 0.0005 for value in closes]
    lows = [value - 0.0005 for value in closes]
    values = indicators.adx(highs, lows, closes, 14)
    assert values[-1] == pytest.approx(100.0)


def test_adx_stays_inside_bounds_and_varies_on_a_choppy_series():
    import math

    closes = [1.1 + 0.0012 * math.sin(index / 1.7) for index in range(120)]
    highs = [value + 0.0003 for value in closes]
    lows = [value - 0.0003 for value in closes]
    warm = [value for value in indicators.adx(highs, lows, closes, 14) if value is not None]
    assert warm, "ADX never warmed up"
    assert all(0.0 <= value <= 100.0 for value in warm)
    assert max(warm) > min(warm), "ADX should not be constant on a choppy series"


def test_adx_needs_roughly_two_periods_of_candles():
    closes = [1.0 + 0.001 * index for index in range(20)]
    highs = [value + 0.0005 for value in closes]
    lows = [value - 0.0005 for value in closes]
    assert set(indicators.adx(highs, lows, closes, 14)) == {None}


def test_bollinger_collapses_to_the_mean_on_a_flat_series():
    middle, upper, lower = indicators.bollinger([2.0] * 30, 20, 2.0)
    assert middle[-1] == pytest.approx(2.0)
    assert upper[-1] == pytest.approx(2.0)
    assert lower[-1] == pytest.approx(2.0)


def test_bollinger_bands_straddle_the_middle_band():
    closes = [1.0 + 0.001 * index for index in range(40)]
    middle, upper, lower = indicators.bollinger(closes, 20, 2.0)
    assert lower[-1] < middle[-1] < upper[-1]


def test_vwap_without_volume_falls_back_to_typical_price_mean():
    highs = [10.0, 10.0]
    lows = [8.0, 8.0]
    closes = [9.0, 9.0]
    values = indicators.vwap(highs, lows, closes, period=2)
    assert values[-1] == pytest.approx(9.0)


def test_vwap_weights_by_volume_when_supplied():
    highs = [10.0, 20.0]
    lows = [10.0, 20.0]
    closes = [10.0, 20.0]
    volumes = [3.0, 1.0]
    values = indicators.vwap(highs, lows, closes, volumes=volumes, period=2)
    assert values[-1] == pytest.approx((10.0 * 3.0 + 20.0 * 1.0) / 4.0)


def test_atr_ratio_flags_a_sudden_compression():
    series = [1.0] * 30 + [0.4] * 5
    ratio = indicators.atr_ratio(series, 20)
    assert ratio is not None and ratio < 0.85


def test_atr_ratio_is_about_one_on_a_steady_series():
    assert indicators.atr_ratio([1.0] * 40, 20) == pytest.approx(1.0)


def test_atr_ratio_returns_none_when_not_warm():
    assert indicators.atr_ratio([None, None], 20) is None


def test_distance_to_band_scales_from_middle_to_band():
    assert indicators.distance_to_band(100.0, 100.0, 110.0, 90.0) == pytest.approx(0.0)
    assert indicators.distance_to_band(110.0, 100.0, 110.0, 90.0) == pytest.approx(1.0)
    assert indicators.distance_to_band(105.0, 100.0, 110.0, 90.0) == pytest.approx(0.5)


def test_distance_to_band_clamps_and_handles_a_flat_band():
    assert indicators.distance_to_band(150.0, 100.0, 110.0, 90.0) == pytest.approx(1.0)
    assert indicators.distance_to_band(100.0, 100.0, 100.0, 100.0) == pytest.approx(0.0)
    assert indicators.distance_to_band(None, 100.0, 110.0, 90.0) is None


def test_candle_quality_flags_a_range_beyond_the_stretch_ratio():
    # Threshold is stretch_ratio * atr, so 1.5 * 0.5 = 0.75 here.
    assert indicators.candle_quality(10.0, 9.6, 0.5, 1.5) == "clean"
    assert indicators.candle_quality(10.0, 8.0, 0.5, 1.5) == "stretched"
    assert indicators.candle_quality(10.0, 8.0, None, 1.5) == "clean"


def test_invalid_periods_are_rejected():
    with pytest.raises(ValueError):
        indicators.sma([1, 2, 3], 0)
    with pytest.raises(ValueError):
        indicators.ema([1, 2, 3], "nope")


def test_mismatched_series_lengths_are_rejected():
    with pytest.raises(ValueError):
        indicators.true_range([1, 2, 3], [1, 2], [1, 2, 3])
