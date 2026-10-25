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


# --- Binance Spot broker (mocked HTTP; nothing reaches Binance) ---

from app import brokers, server  # noqa: E402
from app.brokers import BinanceSpotBroker, BrokerError  # noqa: E402

EXCHANGE_INFO = {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC", "filters": [
    {"filterType": "LOT_SIZE", "stepSize": "0.00001000", "minQty": "0.00001000"},
    {"filterType": "NOTIONAL", "minNotional": "5.00000000"},
]}]}
SETTINGS = {"binance_api_key": "key", "binance_api_secret": "secret"}


class SpotSession:
    def __init__(self, sell_price=110.0):
        self.calls, self.sell_price = [], sell_price

    def request(self, method, url, params=None, headers=None, timeout=None):
        self.calls.append((method, url, headers))
        if "/exchangeInfo" in url:
            return FakeResponse(200, EXCHANGE_INFO)
        if "/account" in url:
            return FakeResponse(200, {"canTrade": True, "balances": [{"asset": "USDT", "free": "100"}]})
        if "side=BUY" in url:
            return FakeResponse(200, {"orderId": 7, "status": "FILLED", "executedQty": "0.10000000",
                                      "cummulativeQuoteQty": "10.00", "fills": [
                                          {"price": "100", "commission": "0.0001", "commissionAsset": "BTC"}]})
        qty = float(url.split("quantity=")[1].split("&")[0])
        quote = qty * self.sell_price
        return FakeResponse(200, {"orderId": 8, "status": "FILLED", "executedQty": str(qty),
                                  "cummulativeQuoteQty": str(quote), "fills": [
                                      {"price": str(self.sell_price), "commission": str(quote * 0.001),
                                       "commissionAsset": "USDT"}]})


def test_signature_is_hmac_sha256_of_query():
    import hashlib
    import hmac

    signed = BinanceSpotBroker(SETTINGS, session=SpotSession()).sign({"symbol": "BTCUSDT", "timestamp": 1})
    expected = hmac.new(b"secret", b"symbol=BTCUSDT&timestamp=1", hashlib.sha256).hexdigest()
    assert signed == "symbol=BTCUSDT&timestamp=1&signature=" + expected


def test_testnet_is_default_and_keys_required():
    assert BinanceSpotBroker(SETTINGS, session=SpotSession()).base_url == brokers.BINANCE_TESTNET_URL
    with pytest.raises(BrokerError, match="API key"):
        BinanceSpotBroker({}, session=SpotSession())


def test_buy_then_close_uses_fills_and_fees():
    session = SpotSession(sell_price=110.0)
    broker = BinanceSpotBroker(SETTINGS, session=session)
    trade = broker.open_trade(symbol="btcusdt", side="BUY", amount=10)
    method, url, headers = session.calls[-1]
    assert method == "POST" and "quoteOrderQty=10" in url and "signature=" in url
    assert headers == {"X-MBX-APIKEY": "key"}
    assert trade["position"] == {"symbol": "BTCUSDT", "qty": 0.0999, "cost": 10.0, "avg_price": 100.0}
    result = broker.close_trade(trade["position"])
    assert "quantity=0.0999" in session.calls[-1][1]
    assert result["profit"] == pytest.approx(0.0999 * 110 * 0.999 - 10.0, abs=1e-6)


def test_buy_only_and_min_notional():
    broker = BinanceSpotBroker(SETTINGS, session=SpotSession())
    with pytest.raises(BrokerError, match="buy-only"):
        broker.open_trade(symbol="BTCUSDT", side="SELL", amount=10)
    with pytest.raises(BrokerError, match="minimum order"):
        broker.open_trade(symbol="BTCUSDT", side="BUY", amount=1)


def test_http_errors_map_to_broker_error():
    class Blocked:
        def request(self, *args, **kwargs):
            return FakeResponse(451, {})

    with pytest.raises(BrokerError, match="451.*location"):
        BinanceSpotBroker(SETTINGS, session=Blocked()).account()


@pytest.fixture
def client():
    server.app.config.update(TESTING=True)
    with server.app.test_client() as test_client:
        test_client.post("/api/reset")
        test_client.post("/api/config", json={
            "symbols": [{"symbol": "frxEURUSD", "asset_class": "FOREX"}],
            "market_source": "replay", "market_replay_file": REPLAY,
        })
        yield test_client
        test_client.post("/api/reset")


def test_binance_keys_are_write_only(client):
    body = client.post("/api/config", json={"broker_provider": "binance", "binance_api_key": "abc",
                                            "binance_api_secret": "shh"}).get_json()["settings"]
    assert body["broker_provider"] == "binance" and body["binance_testnet"] is True
    assert body["binance_api_key"] == "" and body["binance_api_secret"] == ""
    assert body["binance_key_set"] and body["binance_secret_set"]
    boot = client.get("/api/bootstrap").get_data(as_text=True)
    assert "shh" not in boot and '"abc"' not in boot
    cleared = client.post("/api/config", json={"clear_binance_keys": True}).get_json()["settings"]
    assert not cleared["binance_key_set"]


def test_mainnet_auto_start_needs_confirmation(client):
    client.post("/api/config", json={"broker_provider": "binance", "binance_testnet": False,
                                     "live_trading_enabled": True})
    assert "confirm_mainnet" in client.post("/api/auto/start", json={"mode": "live"}).get_json()["error"]
    assert client.post("/api/auto/start", json={"mode": "live", "confirm_mainnet": True}).status_code == 200


def test_auto_loop_closes_spot_position_after_hold(client, monkeypatch):
    from datetime import timedelta

    session = SpotSession(sell_price=120.0)
    monkeypatch.setattr(server, "live_broker_from_settings", lambda s: BinanceSpotBroker(SETTINGS, session=session))
    client.post("/api/config", json={"broker_provider": "binance", "live_trading_enabled": True,
                                     "live_trade_stake": 10, "auto_hold_minutes": 5})
    client.post("/api/auto/start", json={"mode": "live"})
    now = server.utcnow()
    auto = server.auto_trade_tick(now=now)
    assert [item["position"]["qty"] for item in auto["pending_live"]] == [0.0999]
    assert server.auto_trade_tick(now=now + timedelta(minutes=1))["pending_live"]
    auto = server.auto_trade_tick(now=now + timedelta(minutes=10))
    assert auto["realized_pnl"] == pytest.approx(0.0999 * 120 * 0.999 - 10.0, abs=1e-6)
    assert "LIVE_SETTLED" in [row["type"] for row in server.load_state()["trade_history"]]
