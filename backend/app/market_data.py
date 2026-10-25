"""Market data providers for the FX Scalper Community Edition.

The community edition originally expected indicator values to be pasted into the
settings as JSON. This module closes that gap: a provider turns a symbol into a
list of candles, and app.snapshot turns those candles into the exact snapshot
the existing rule engine already consumes.

Two providers ship here:

  DerivCandleProvider   Live candles from Deriv over the WebSocket API
                        (ticks_history with style=candles). Market data needs no
                        API token, only an app_id, so this works out of the box.
                        A token is accepted and used if one is configured.
  BinanceCandleProvider Public Binance spot klines over REST. No API key needed;
                        the base URL is configurable (data-api.binance.vision by
                        default, api.binance.us for US users).
  ReplayCandleProvider  Deterministic candles from a JSON fixture. Use it for
                        local development, tests and CI so nothing has to reach
                        the network.

Choose with the COMMUNITY_MARKET_SOURCE environment variable ("deriv" by
default, "binance" or "replay") or with the market_source setting.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional

import requests
import websocket

DEFAULT_WS_URL = "wss://ws.derivws.com/websockets/v3"
DEFAULT_APP_ID = "1089"
DEFAULT_GRANULARITY = 300
DEFAULT_COUNT = 200
DEFAULT_TIMEOUT = 20.0

GRANULARITIES = (60, 120, 180, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400)

DEFAULT_BINANCE_DATA_URL = "https://data-api.binance.vision"
BINANCE_INTERVALS = {
    60: "1m", 180: "3m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h",
    7200: "2h", 14400: "4h", 28800: "8h", 86400: "1d",
}
BINANCE_PAGE = 1000

__all__ = [
    "Candle",
    "BinanceCandleProvider",
    "CandleProvider",
    "DEFAULT_BINANCE_DATA_URL",
    "DerivCandleProvider",
    "MarketDataError",
    "ReplayCandleProvider",
    "DEFAULT_GRANULARITY",
    "DEFAULT_WS_URL",
    "GRANULARITIES",
    "provider_from_settings",
    "validate_granularity",
]


class MarketDataError(RuntimeError):
    """Raised when candles cannot be produced for a symbol."""


def validate_granularity(value: object) -> int:
    """Return a Deriv-supported granularity in seconds, or raise."""
    try:
        granularity = int(value)
    except (TypeError, ValueError):
        raise MarketDataError(
            "granularity must be an integer number of seconds, got {!r}".format(value)
        )
    if granularity not in GRANULARITIES:
        raise MarketDataError(
            "unsupported granularity {}s; Deriv supports {}".format(
                granularity, list(GRANULARITIES)
            )
        )
    return granularity


@dataclass(frozen=True)
class Candle:
    """One OHLC candle. Volume is optional - Deriv history does not carry it."""

    epoch: int
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None

    @classmethod
    def from_mapping(cls, raw: Mapping) -> "Candle":
        if not isinstance(raw, Mapping):
            raise MarketDataError("candle must be a mapping, got {!r}".format(type(raw).__name__))
        missing = [key for key in ("epoch", "open", "high", "low", "close") if key not in raw]
        if missing:
            raise MarketDataError("candle is missing {}".format(", ".join(missing)))
        volume = raw.get("volume")
        return cls(
            epoch=int(raw["epoch"]),
            open=float(raw["open"]),
            high=float(raw["high"]),
            low=float(raw["low"]),
            close=float(raw["close"]),
            volume=None if volume is None else float(volume),
        )


class CandleProvider:
    """Interface every provider implements."""

    name = "base"

    def get_candles(
        self,
        symbol: str,
        granularity: int = DEFAULT_GRANULARITY,
        count: int = DEFAULT_COUNT,
    ) -> List[Candle]:
        raise NotImplementedError

    def __repr__(self) -> str:
        return "<{}>".format(type(self).__name__)


def _with_app_id(url: str, app_id: str) -> str:
    if "app_id=" in url:
        return url
    separator = "&" if "?" in url else "?"
    return "{}{}app_id={}".format(url, separator, app_id)


def _candles_from_payload(payload: Mapping, symbol: str) -> List[Candle]:
    rows = payload.get("candles")
    if isinstance(rows, list):
        candles = []
        for row in rows:
            try:
                candles.append(Candle.from_mapping(row))
            except MarketDataError:
                continue
        return candles
    history = payload.get("history")
    if isinstance(history, Mapping):
        prices = history.get("prices") or []
        times = history.get("times") or []
        return [
            Candle(epoch=int(times[index]), open=float(price), high=float(price), low=float(price), close=float(price))
            for index, price in enumerate(prices)
            if index < len(times)
        ]
    return []


class DerivCandleProvider(CandleProvider):
    """Live candles from Deriv. Market data needs an app_id, not a token."""

    name = "deriv"

    def __init__(
        self,
        app_id: object = DEFAULT_APP_ID,
        ws_url: object = DEFAULT_WS_URL,
        token: Optional[object] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.app_id = str(app_id or DEFAULT_APP_ID).strip() or DEFAULT_APP_ID
        self.ws_url = str(ws_url or DEFAULT_WS_URL).strip() or DEFAULT_WS_URL
        self.token = str(token).strip() if token else None
        self.timeout = float(timeout)
        self.url = _with_app_id(self.ws_url, self.app_id)

    def get_candles(
        self,
        symbol: str,
        granularity: int = DEFAULT_GRANULARITY,
        count: int = DEFAULT_COUNT,
    ) -> List[Candle]:
        symbol = str(symbol or "").strip()
        if not symbol:
            raise MarketDataError("symbol is required")
        granularity = validate_granularity(granularity)
        try:
            count = int(count)
        except (TypeError, ValueError):
            raise MarketDataError("count must be an integer, got {!r}".format(count))
        if count < 2:
            raise MarketDataError("count must be at least 2, got {}".format(count))

        request = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "style": "candles",
            "req_id": 1,
        }
        try:
            connection = websocket.create_connection(self.url, timeout=self.timeout)
        except Exception as error:
            raise MarketDataError(
                "could not connect to Deriv at {}: {}".format(self.url, error)
            ) from error
        try:
            connection.send(json.dumps(request))
            payload = self._await_candles(connection, symbol)
        finally:
            try:
                connection.close()
            except Exception:
                pass

        error = payload.get("error")
        if error:
            raise MarketDataError(
                "Deriv rejected ticks_history for {}: {} {}".format(
                    symbol, error.get("code"), error.get("message")
                )
            )
        candles = _candles_from_payload(payload, symbol)
        if not candles:
            raise MarketDataError("Deriv returned no candles for {}".format(symbol))
        return candles

    def _await_candles(self, connection: object, symbol: str) -> Mapping:
        while True:
            try:
                raw = connection.recv()
            except Exception as error:
                raise MarketDataError(
                    "Deriv websocket failed while reading {}: {}".format(symbol, error)
                ) from error
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(payload, Mapping):
                continue
            if payload.get("error"):
                return payload
            if payload.get("msg_type") in ("candles", "history"):
                return payload


class ReplayCandleProvider(CandleProvider):
    """Deterministic candles from fixtures, for development, tests and CI.

    Fixtures are either {symbol: [candle, ...]} or
    {"granularity": 300, "series": {symbol: [candle, ...]}}. When a fixture is
    shorter than the requested count the series is cycled so callers always get
    the count they asked for. Cycled epochs are not contiguous, so treat this
    provider as a shape-and-behaviour double, not as market history.
    """

    name = "replay"

    def __init__(self, series: Mapping, granularity: object = DEFAULT_GRANULARITY) -> None:
        self.granularity = validate_granularity(granularity)
        self._series: Dict[str, List[Candle]] = {}
        for symbol, rows in dict(series or {}).items():
            self._series[str(symbol)] = [Candle.from_mapping(row) for row in rows or []]

    @classmethod
    def from_file(cls, path: object, granularity: Optional[object] = None) -> "ReplayCandleProvider":
        fixture = Path(str(path)).expanduser()
        if not fixture.is_file():
            raise MarketDataError("replay fixture not found: {}".format(fixture))
        try:
            data = json.loads(fixture.read_text(encoding="utf-8"))
        except ValueError as error:
            raise MarketDataError("replay fixture {} is not valid JSON: {}".format(fixture, error)) from error
        if isinstance(data, Mapping) and isinstance(data.get("series"), Mapping):
            resolved = granularity if granularity is not None else data.get("granularity", DEFAULT_GRANULARITY)
            data = data["series"]
        else:
            resolved = granularity if granularity is not None else DEFAULT_GRANULARITY
        if not isinstance(data, Mapping):
            raise MarketDataError("replay fixture {} must map symbols to candles".format(fixture))
        return cls(data, granularity=resolved)

    def get_candles(
        self,
        symbol: str,
        granularity: int = DEFAULT_GRANULARITY,
        count: int = DEFAULT_COUNT,
    ) -> List[Candle]:
        validate_granularity(granularity)
        key = str(symbol or "").strip()
        candles = self._series.get(key)
        if not candles:
            raise MarketDataError("replay fixture has no series for {!r}".format(key))
        try:
            count = int(count)
        except (TypeError, ValueError):
            raise MarketDataError("count must be an integer, got {!r}".format(count))
        if count < 1:
            raise MarketDataError("count must be at least 1, got {}".format(count))
        if len(candles) >= count:
            return list(candles[-count:])
        repeats = (count // len(candles)) + 1
        return (list(candles) * repeats)[-count:]


class BinanceCandleProvider(CandleProvider):
    """Closed spot candles from Binance's public klines endpoint (no API key)."""

    name = "binance"

    def __init__(self, base_url: object = DEFAULT_BINANCE_DATA_URL, timeout: float = DEFAULT_TIMEOUT,
                 session: Optional[object] = None) -> None:
        self.base_url = (str(base_url or "").strip() or DEFAULT_BINANCE_DATA_URL).rstrip("/")
        self.timeout = float(timeout)
        self.session = session or requests

    def _page(self, symbol: str, interval: str, limit: int, end_ms: Optional[int]) -> list:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if end_ms is not None:
            params["endTime"] = end_ms
        try:
            response = self.session.get(self.base_url + "/api/v3/klines", params=params, timeout=self.timeout)
        except requests.RequestException as error:
            raise MarketDataError("Binance request failed for {}: {}".format(symbol, error)) from error
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code != 200:
            message = payload.get("msg") if isinstance(payload, Mapping) else ""
            hint = " Binance blocks this location; try https://api.binance.us." if response.status_code == 451 else ""
            raise MarketDataError(
                "Binance returned HTTP {} for {}: {}{}".format(response.status_code, symbol, message or "error", hint)
            )
        if not isinstance(payload, list):
            raise MarketDataError("Binance returned an unexpected klines payload for {}".format(symbol))
        return payload

    def get_candles(
        self,
        symbol: str,
        granularity: int = DEFAULT_GRANULARITY,
        count: int = DEFAULT_COUNT,
    ) -> List[Candle]:
        granularity = validate_granularity(granularity)
        interval = BINANCE_INTERVALS.get(granularity)
        if interval is None:
            raise MarketDataError(
                "Binance has no {}s interval; use one of {}".format(granularity, sorted(BINANCE_INTERVALS))
            )
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise MarketDataError("symbol is required")
        count = max(1, int(count))
        now_ms = int(time.time() * 1000)
        rows: list = []
        end_ms: Optional[int] = None
        while len(rows) < count + 1:
            page = self._page(symbol, interval, min(BINANCE_PAGE, count + 1 - len(rows)), end_ms)
            if not page:
                break
            rows = page + rows
            end_ms = int(page[0][0]) - 1
            if len(page) < BINANCE_PAGE:
                break
        candles = [
            Candle(
                epoch=int(row[0]) // 1000,
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in rows
            if int(row[6]) < now_ms
        ]
        if not candles:
            raise MarketDataError("Binance returned no closed candles for {}".format(symbol))
        return candles[-count:]


def provider_from_settings(settings: Optional[Mapping] = None) -> CandleProvider:
    """Pick a provider from the environment first, then the settings dict."""
    settings = settings or {}
    source = str(
        os.getenv("COMMUNITY_MARKET_SOURCE") or settings.get("market_source") or "deriv"
    ).strip().lower()
    if source in ("replay", "fixture", "file"):
        path = os.getenv("COMMUNITY_REPLAY_FILE") or settings.get("market_replay_file")
        if not path:
            raise MarketDataError(
                "replay market source selected but no market_replay_file is configured"
            )
        return ReplayCandleProvider.from_file(
            path, granularity=settings.get("market_replay_granularity")
        )
    if source == "binance":
        return BinanceCandleProvider(
            base_url=os.getenv("COMMUNITY_BINANCE_DATA_URL") or settings.get("binance_data_url")
        )
    app_id = os.getenv("COMMUNITY_DERIV_APP_ID") or settings.get("deriv_app_id") or DEFAULT_APP_ID
    ws_url = os.getenv("COMMUNITY_DERIV_WS_URL") or settings.get("deriv_ws_url") or DEFAULT_WS_URL
    token = os.getenv("COMMUNITY_DERIV_TOKEN") or settings.get("deriv_token") or None
    return DerivCandleProvider(app_id=app_id, ws_url=ws_url, token=token)
