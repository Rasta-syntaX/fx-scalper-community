"""Technical indicators for the FX Scalper Community Edition.

Pure standard library - no pandas or numpy - so the community image stays small
and every calculation is readable and testable in isolation.

Each function returns a list aligned 1:1 with its input, using None for the
leading slots where the window is not yet warm. Use last() to read the most
recent value.

The derived values consumed by app.snapshot follow the semantics implied by the
existing rule engine in app.server (see RULES, classify_regime and
evaluate_snapshot):

  atr_ratio        Current ATR divided by its own trailing mean. The engine
                   treats a value below 0.85 as volatility compression and
                   returns LOW_VOLATILITY.
  distance_to_band How far price sits from the middle Bollinger band,
                   normalised so 0.0 is the middle band and 1.0 is the band
                   itself. The engine treats anything above 0.88 as
                   overextended.
  candle_quality   "stretched" when the candle range exceeds
                   candle_stretch_ratio x ATR, otherwise "clean".

The 0.85 and 0.88 thresholds are read from the existing engine, not invented
here. The formulas that produce those two values are an inference from the
engine behaviour, and they are exposed as configurable settings.
"""

from __future__ import annotations

from typing import Optional, Sequence

Number = float

__all__ = [
    "sma",
    "ema",
    "rsi",
    "true_range",
    "atr",
    "adx",
    "bollinger",
    "vwap",
    "atr_ratio",
    "distance_to_band",
    "candle_quality",
    "last",
]


def _as_floats(values: Sequence[Number]) -> list:
    return [float(value) for value in values]


def _validate_period(period: int, name: str = "period") -> int:
    try:
        resolved = int(period)
    except (TypeError, ValueError):
        raise ValueError("{} must be an integer, got {!r}".format(name, period))
    if resolved < 1:
        raise ValueError("{} must be >= 1, got {!r}".format(name, period))
    return resolved


def _validate_lengths(*series: Sequence[Number]) -> int:
    lengths = {len(item) for item in series}
    if len(lengths) > 1:
        raise ValueError("series lengths differ: {}".format(sorted(lengths)))
    if not lengths:
        return 0
    return lengths.pop()


def last(series: Sequence[Optional[Number]]) -> Optional[float]:
    """Return the final value of a series, or None if it is empty or cold."""
    if series is None or len(series) == 0:
        return None
    value = series[-1]
    return None if value is None else float(value)


def sma(values: Sequence[Number], period: int) -> list:
    """Simple moving average. Slots before the window warms are None."""
    period = _validate_period(period)
    data = _as_floats(values)
    out: list = [None] * len(data)
    if len(data) < period:
        return out
    window_sum = sum(data[:period])
    out[period - 1] = window_sum / period
    for index in range(period, len(data)):
        window_sum += data[index] - data[index - period]
        out[index] = window_sum / period
    return out


def ema(values: Sequence[Number], period: int) -> list:
    """Exponential moving average, seeded with the first SMA (standard form)."""
    period = _validate_period(period)
    data = _as_floats(values)
    out: list = [None] * len(data)
    if len(data) < period:
        return out
    seed = sum(data[:period]) / period
    out[period - 1] = seed
    multiplier = 2.0 / (period + 1.0)
    previous = seed
    for index in range(period, len(data)):
        previous = data[index] * multiplier + previous * (1.0 - multiplier)
        out[index] = previous
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def rsi(values: Sequence[Number], period: int = 14) -> list:
    """Relative Strength Index using Wilder smoothing."""
    period = _validate_period(period)
    data = _as_floats(values)
    out: list = [None] * len(data)
    if len(data) <= period:
        return out
    gains = 0.0
    losses = 0.0
    for index in range(1, period + 1):
        change = data[index] - data[index - 1]
        if change >= 0.0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for index in range(period + 1, len(data)):
        change = data[index] - data[index - 1]
        gain = change if change > 0.0 else 0.0
        loss = -change if change < 0.0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[index] = _rsi_value(avg_gain, avg_loss)
    return out


def true_range(highs: Sequence[Number], lows: Sequence[Number], closes: Sequence[Number]) -> list:
    """Wilder true range. The first slot is simply high minus low."""
    _validate_lengths(highs, lows, closes)
    high = _as_floats(highs)
    low = _as_floats(lows)
    close = _as_floats(closes)
    out: list = []
    for index in range(len(high)):
        if index == 0:
            out.append(high[index] - low[index])
        else:
            out.append(
                max(
                    high[index] - low[index],
                    abs(high[index] - close[index - 1]),
                    abs(low[index] - close[index - 1]),
                )
            )
    return out


def atr(highs: Sequence[Number], lows: Sequence[Number], closes: Sequence[Number], period: int = 14) -> list:
    """Average True Range using Wilder smoothing."""
    period = _validate_period(period)
    ranges = true_range(highs, lows, closes)
    out: list = [None] * len(ranges)
    if len(ranges) < period:
        return out
    previous = sum(ranges[:period]) / period
    out[period - 1] = previous
    for index in range(period, len(ranges)):
        previous = (previous * (period - 1) + ranges[index]) / period
        out[index] = previous
    return out


def _dx(plus_smoothed: float, minus_smoothed: float, range_smoothed: float) -> float:
    if range_smoothed <= 0.0:
        return 0.0
    plus_di = 100.0 * plus_smoothed / range_smoothed
    minus_di = 100.0 * minus_smoothed / range_smoothed
    denominator = plus_di + minus_di
    if denominator <= 0.0:
        return 0.0
    return 100.0 * abs(plus_di - minus_di) / denominator


def adx(highs: Sequence[Number], lows: Sequence[Number], closes: Sequence[Number], period: int = 14) -> list:
    """Average Directional Index (Wilder). Needs about 2 x period candles to warm."""
    period = _validate_period(period)
    _validate_lengths(highs, lows, closes)
    high = _as_floats(highs)
    low = _as_floats(lows)
    close = _as_floats(closes)
    count = len(high)
    out: list = [None] * count
    if count < 2 * period:
        return out
    ranges = true_range(high, low, close)
    plus_dm = [0.0] * count
    minus_dm = [0.0] * count
    for index in range(1, count):
        up_move = high[index] - high[index - 1]
        down_move = low[index - 1] - low[index]
        if up_move > down_move and up_move > 0.0:
            plus_dm[index] = up_move
        if down_move > up_move and down_move > 0.0:
            minus_dm[index] = down_move
    range_smoothed = float(sum(ranges[1:period + 1]))
    plus_smoothed = float(sum(plus_dm[1:period + 1]))
    minus_smoothed = float(sum(minus_dm[1:period + 1]))
    dx_values: list = [None] * count
    dx_values[period] = _dx(plus_smoothed, minus_smoothed, range_smoothed)
    for index in range(period + 1, count):
        range_smoothed = range_smoothed - (range_smoothed / period) + ranges[index]
        plus_smoothed = plus_smoothed - (plus_smoothed / period) + plus_dm[index]
        minus_smoothed = minus_smoothed - (minus_smoothed / period) + minus_dm[index]
        dx_values[index] = _dx(plus_smoothed, minus_smoothed, range_smoothed)
    first_dx = period
    seed_index = first_dx + period - 1
    if seed_index >= count:
        return out
    window = [value for value in dx_values[first_dx:first_dx + period] if value is not None]
    if len(window) < period:
        return out
    previous = sum(window) / period
    out[seed_index] = previous
    for index in range(seed_index + 1, count):
        value = dx_values[index]
        if value is None:
            continue
        previous = (previous * (period - 1) + value) / period
        out[index] = previous
    return out


def bollinger(values: Sequence[Number], period: int = 20, k: Number = 2.0) -> tuple:
    """Bollinger bands. Returns (middle, upper, lower), each aligned to input."""
    period = _validate_period(period)
    data = _as_floats(values)
    count = len(data)
    middle = sma(data, period)
    upper: list = [None] * count
    lower: list = [None] * count
    width = float(k)
    for index in range(period - 1, count):
        window = data[index - period + 1:index + 1]
        mean = middle[index]
        variance = sum((value - mean) ** 2 for value in window) / period
        deviation = variance ** 0.5
        upper[index] = mean + width * deviation
        lower[index] = mean - width * deviation
    return middle, upper, lower


def vwap(
    highs: Sequence[Number],
    lows: Sequence[Number],
    closes: Sequence[Number],
    volumes: Optional[Sequence[Number]] = None,
    period: Optional[int] = None,
) -> list:
    """Rolling VWAP.

    When volumes are supplied this is the true volume weighted average price.
    Deriv candle history does not carry volume, so when volumes is None the
    function falls back to an unweighted rolling mean of the typical price
    (high + low + close) / 3. That fallback is a documented proxy, not a real
    VWAP - it still answers the only question the engine asks, whether price is
    above or below its recent fair value.

    period=None produces an expanding average from the first candle.
    """
    _validate_lengths(highs, lows, closes)
    high = _as_floats(highs)
    low = _as_floats(lows)
    close = _as_floats(closes)
    count = len(high)
    typical = [(high[index] + low[index] + close[index]) / 3.0 for index in range(count)]
    weighted: Optional[list] = None
    if volumes is not None:
        _validate_lengths(highs, lows, closes, volumes)
        weighted = _as_floats(volumes)
    window = None if period is None else _validate_period(period)
    out: list = [None] * count
    price_volume = 0.0
    volume_total = 0.0
    typical_total = 0.0
    for index in range(count):
        if weighted is not None:
            price_volume += typical[index] * weighted[index]
            volume_total += weighted[index]
            if window is not None and index >= window:
                price_volume -= typical[index - window] * weighted[index - window]
                volume_total -= weighted[index - window]
            if window is not None and index < window - 1:
                continue
            out[index] = (price_volume / volume_total) if volume_total > 0.0 else typical[index]
        else:
            typical_total += typical[index]
            if window is not None and index >= window:
                typical_total -= typical[index - window]
            if window is not None and index < window - 1:
                continue
            divisor = float(window) if window is not None else float(index + 1)
            out[index] = typical_total / divisor
    return out


def atr_ratio(atr_series: Sequence[Optional[Number]], lookback: int = 20) -> Optional[float]:
    """Current ATR relative to its own trailing mean.

    The window includes the current value, so a perfectly steady ATR returns
    approximately 1.0. Returns None when there is no warm ATR at all.
    """
    lookback = _validate_period(lookback, "lookback")
    warm = [float(value) for value in atr_series if value is not None]
    if not warm:
        return None
    window = warm[-lookback:]
    baseline = sum(window) / len(window)
    if baseline <= 0.0:
        return None
    return warm[-1] / baseline


def distance_to_band(
    price: Optional[Number],
    middle: Optional[Number],
    upper: Optional[Number],
    lower: Optional[Number],
) -> Optional[float]:
    """Distance from the middle Bollinger band, 0.0 at the middle and 1.0 at the band.

    Clamped to [0, 1]. Returns None when any input is cold.
    """
    if price is None or middle is None or upper is None or lower is None:
        return None
    half_width = float(upper) - float(middle)
    if half_width <= 0.0:
        return 0.0
    value = abs(float(price) - float(middle)) / half_width
    return max(0.0, min(1.0, value))


def candle_quality(
    high: Optional[Number],
    low: Optional[Number],
    atr_value: Optional[Number],
    stretch_ratio: Number = 1.5,
) -> str:
    """Classify a candle as "stretched" or "clean" relative to ATR."""
    if high is None or low is None or atr_value is None:
        return "clean"
    if float(atr_value) <= 0.0:
        return "clean"
    candle_range = float(high) - float(low)
    if candle_range > float(stretch_ratio) * float(atr_value):
        return "stretched"
    return "clean"
