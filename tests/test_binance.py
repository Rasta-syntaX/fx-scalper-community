import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app import market_data  # noqa: E402
from app.market_data import BinanceCandleProvider, MarketDataError  # noqa: E402

REPLAY = os.path.join(os.path.dirname(__file__), "..", "backend", "data", "replay_sample.json")


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def kline(open_ms, close=1.0, closed=True):
    close_ms = open_ms + 299_999 if closed else 99_999_999_999_999
    return [open_ms, "1.0", "1.2", "0.9", str(close), "5.0", close_ms, "0", 1, "0", "0", "0"]


class FakeSession:
    def __init__(self, rows, status=200):
        self.rows, self.status, self.calls = rows, status, []

    def get(self, url, params, timeout):
        self.calls.append(dict(params))
        if self.status != 200:
            return FakeResponse(self.status, {"code": 0, "msg": "restricted location"})
        end = params.get("endTime")
        rows = [row for row in self.rows if end is None or row[0] <= end]
        return FakeResponse(200, rows[-params["limit"]:])


def test_klines_map_to_closed_candles():
    rows = [kline(i * 300_000, close=1 + i) for i in range(5)] + [kline(5 * 300_000, closed=False)]
    session = FakeSession(rows)
    candles = BinanceCandleProvider(session=session).get_candles("btcusdt", granularity=300, count=3)
    assert [c.close for c in candles] == [3.0, 4.0, 5.0]
    assert candles[0].epoch == 600 and candles[0].volume == 5.0
    assert session.calls[0]["symbol"] == "BTCUSDT" and session.calls[0]["interval"] == "5m"


def test_pagination_fetches_older_pages():
    rows = [kline(i * 60_000) for i in range(2500)]
    session = FakeSession(rows)
    candles = BinanceCandleProvider(session=session).get_candles("ETHUSDT", granularity=60, count=2200)
    assert len(candles) == 2200 and len(session.calls) == 3
    assert [b.epoch - a.epoch for a, b in zip(candles, candles[1:])] == [60] * 2199


def test_errors_and_unsupported_interval():
    with pytest.raises(MarketDataError, match="451.*api.binance.us"):
        BinanceCandleProvider(session=FakeSession([], status=451)).get_candles("BTCUSDT")
    with pytest.raises(MarketDataError, match="no 120s interval"):
        BinanceCandleProvider(session=FakeSession([])).get_candles("BTCUSDT", granularity=120)


def test_provider_from_settings_binance(monkeypatch):
    monkeypatch.delenv("COMMUNITY_MARKET_SOURCE", raising=False)
    settings = {"market_source": "binance", "binance_data_url": "https://api.binance.us/"}
    provider = market_data.provider_from_settings(settings)
    assert isinstance(provider, BinanceCandleProvider) and provider.base_url == "https://api.binance.us"


def test_cli_fee_reduces_net_return(capsys):
    from app import cli

    assert cli.main(["backtest", "--replay", REPLAY, "--symbol", "frxEURUSD", "--fee", "0.1", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["fee_pct"] == 0.1
    assert row["total_net_return_pct"] == pytest.approx(row["total_return_pct"] - 0.2 * row["trades"], abs=1e-3)
