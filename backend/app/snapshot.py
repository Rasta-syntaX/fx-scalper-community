"""Snapshot builder: candles in, the exact market snapshot the engine eats out.

The rule engine in app.server consumes a flat dict of pre-computed values and
coerces it in normalize_market_snapshots(). The contract is deliberately frozen
here: build_snapshot returns exactly those keys, so evaluate_snapshot and the
existing frontend keep working with no changes at all. Everything added by this
module sits underneath the engine.

Typical use:

    provider = provider_from_settings(settings)
    result = build_market_snapshots(settings.get("symbols", []), settings, provider)
    market = [evaluate_snapshot(row, settings) for row in result.snapshots]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence

from app import indicators
from app.market_data import (
    DEFAULT_GRANULARITY,
    Candle,
    CandleProvider,
    MarketDataError,
    validate_granularity,
)

SNAPSHOT_KEYS = (
    "symbol",
    "asset_class",
    "price",
    "ema_fast",
    "ema_slow",
    "adx",
    "rsi",
    "atr_ratio",
    "price_vs_vwap",
    "candle_quality",
    "distance_to_band",
)

INDICATOR_DEFAULTS = {
    "ema_fast_period": 9,
    "ema_slow_period": 21,
    "rsi_period": 14,
    "adx_period": 14,
    "atr_period": 14,
    "bollinger_period": 20,
    "bollinger_k": 2.0,
    "atr_ratio_lookback": 20,
    "candle_stretch_ratio": 1.5,
    "vwap_period": 20,
}

__all__ = [
    "INDICATOR_DEFAULTS",
    "SNAPSHOT_KEYS",
    "IndicatorSettings",
    "ScanResult",
    "build_market_snapshots",
    "build_snapshot",
    "compute_indicators",
    "minimum_candles",
]


@dataclass(frozen=True)
class IndicatorSettings:
    """Indicator windows, read from the app settings with documented defaults."""

    ema_fast_period: int = 9
    ema_slow_period: int = 21
    rsi_period: int = 14
    adx_period: int = 14
    atr_period: int = 14
    bollinger_period: int = 20
    bollinger_k: float = 2.0
    atr_ratio_lookback: int = 20
    candle_stretch_ratio: float = 1.5
    vwap_period: int = 20

    @classmethod
    def from_settings(cls, settings: Optional[Mapping]) -> "IndicatorSettings":
        settings = settings or {}
        resolved: Dict[str, object] = {}
        for key, default in INDICATOR_DEFAULTS.items():
            value = settings.get(key, default)
            if value is None:
                value = default
            try:
                resolved[key] = float(value) if key == "bollinger_k" else int(value)
            except (TypeError, ValueError):
                resolved[key] = default
        return cls(**resolved)


def minimum_candles(config: IndicatorSettings) -> int:
    """Candles needed before every indicator in the snapshot is warm."""
    needed = max(
        2 * config.adx_period,
        config.atr_period + config.atr_ratio_lookback,
        config.bollinger_period,
        config.ema_slow_period,
        config.rsi_period + 1,
        config.vwap_period,
    )
    return int(needed) + 1


def compute_indicators(candles: Sequence[Candle], config: IndicatorSettings) -> Dict[str, object]:
    """Raw indicator values from candles. Any value may be None when still cold."""
    if not candles:
        raise MarketDataError("no candles supplied")
    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    closes = [candle.close for candle in candles]
    volumes = [candle.volume for candle in candles]
    volume_series = None if any(volume is None for volume in volumes) else volumes

    ema_fast = indicators.ema(closes, config.ema_fast_period)
    ema_slow = indicators.ema(closes, config.ema_slow_period)
    rsi_series = indicators.rsi(closes, config.rsi_period)
    atr_series = indicators.atr(highs, lows, closes, config.atr_period)
    adx_series = indicators.adx(highs, lows, closes, config.adx_period)
    middle, upper, lower = indicators.bollinger(closes, config.bollinger_period, config.bollinger_k)
    vwap_series = indicators.vwap(highs, lows, closes, volumes=volume_series, period=config.vwap_period)

    price = float(closes[-1])
    ema_fast_value = indicators.last(ema_fast)
    ema_slow_value = indicators.last(ema_slow)
    rsi_value = indicators.last(rsi_series)
    atr_value = indicators.last(atr_series)
    adx_value = indicators.last(adx_series)
    vwap_value = indicators.last(vwap_series)
    ratio = indicators.atr_ratio(atr_series, config.atr_ratio_lookback)
    proximity = indicators.distance_to_band(
        price,
        indicators.last(middle),
        indicators.last(upper),
        indicators.last(lower),
    )
    return {
        "price": price,
        "ema_fast": ema_fast_value,
        "ema_slow": ema_slow_value,
        "rsi": rsi_value,
        "atr": atr_value,
        "adx": adx_value,
        "vwap": vwap_value,
        "atr_ratio": ratio,
        "distance_to_band": proximity,
        "candle_quality": indicators.candle_quality(
            candles[-1].high, candles[-1].low, atr_value, config.candle_stretch_ratio
        ),
    }


def build_snapshot(
    symbol: str,
    asset_class: str,
    candles: Sequence[Candle],
    config: Optional[IndicatorSettings] = None,
) -> Dict[str, object]:
    """Turn candles into the flat snapshot normalize_market_snapshots() accepts.

    Raises MarketDataError when there are too few candles, or when an indicator
    the engine relies on is still cold, so a half-warm row never reaches the
    engine and silently reads as a neutral market.
    """
    config = config or IndicatorSettings()
    symbol = str(symbol or "").strip()
    if not symbol:
        raise MarketDataError("symbol is required")
    required = minimum_candles(config)
    if len(candles) < required:
        raise MarketDataError(
            "{} needs at least {} candles to warm its indicators, got {}".format(
                symbol, required, len(candles)
            )
        )
    values = compute_indicators(candles, config)
    cold = [
        name
        for name in ("ema_fast", "ema_slow", "rsi", "adx", "vwap", "atr_ratio", "distance_to_band")
        if values.get(name) is None
    ]
    if cold:
        raise MarketDataError(
            "{} indicators are still cold: {}".format(symbol, ", ".join(cold))
        )
    price = float(values["price"])
    vwap_value = float(values["vwap"])
    return {
        "symbol": symbol,
        "asset_class": str(asset_class or "CUSTOM").strip().upper() or "CUSTOM",
        "price": round(price, 5),
        "ema_fast": round(float(values["ema_fast"]), 5),
        "ema_slow": round(float(values["ema_slow"]), 5),
        "adx": round(float(values["adx"]), 2),
        "rsi": round(float(values["rsi"]), 2),
        "atr_ratio": round(float(values["atr_ratio"]), 4),
        "price_vs_vwap": "above" if price >= vwap_value else "below",
        "candle_quality": str(values["candle_quality"]),
        "distance_to_band": round(float(values["distance_to_band"]), 4),
    }


@dataclass
class ScanResult:
    """Snapshots that were built, plus per-symbol failures worth surfacing."""

    snapshots: List[Dict[str, object]] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.snapshots)


def build_market_snapshots(
    symbols: Sequence[object],
    settings: Optional[Mapping],
    provider: CandleProvider,
    granularity: object = DEFAULT_GRANULARITY,
    count: Optional[int] = None,
) -> ScanResult:
    """Build one snapshot per configured symbol, collecting failures.

    symbols accepts the settings shape (dicts with symbol and asset_class) or
    plain strings. A symbol that fails is reported in ScanResult.errors rather
    than silently dropped.
    """
    config = IndicatorSettings.from_settings(settings)
    granularity = validate_granularity(granularity)
    needed = minimum_candles(config)
    requested = int(count) if count else max(needed * 2, 200)
    result = ScanResult()
    for entry in symbols or []:
        if isinstance(entry, Mapping):
            symbol = str(entry.get("symbol") or "").strip()
            asset_class = str(entry.get("asset_class") or "CUSTOM")
        else:
            symbol = str(entry or "").strip()
            asset_class = "CUSTOM"
        if not symbol:
            continue
        try:
            candles = provider.get_candles(symbol, granularity=granularity, count=requested)
            result.snapshots.append(build_snapshot(symbol, asset_class, candles, config))
        except MarketDataError as error:
            result.errors.append({"symbol": symbol, "error": str(error)})
        except Exception as error:
            result.errors.append({"symbol": symbol, "error": "{}: {}".format(type(error).__name__, error)})
    return result
