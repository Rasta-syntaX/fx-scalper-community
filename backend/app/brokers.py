"""Live broker adapters.

The auto-trader and the live trade route only talk to a LiveBroker. Deriv is the
first implementation; to add another broker, subclass LiveBroker, implement
open_trade/trade_status/close, and register it in LIVE_BROKERS under the name
used by the `broker_provider` setting.

Two lifecycles exist. Deriv contracts expire and settle on their own
(settles_itself = True, the auto-trader polls trade_status). Exchange positions
such as Binance Spot stay open until the bot sells them (settles_itself = False,
the auto-trader calls close_trade after auto_hold_minutes).
"""

import hashlib
import hmac
import math
import time
from typing import Dict, Optional, Type
from urllib.parse import urlencode

import requests

from app.deriv_service import DerivCommunityClient, DerivServiceError


class BrokerError(RuntimeError):
    pass


class LiveBroker:
    name = "base"
    settles_itself = True
    sides = frozenset({"BUY", "SELL"})

    def __init__(self, settings: dict) -> None:
        self.settings = settings

    def describe(self) -> dict:
        return {"broker": self.name}

    def open_trade(self, *, symbol: str, side: str, amount: float, **options) -> dict:
        """Place a trade. Returns at least {"ref": broker trade id, "price": amount paid}."""
        raise NotImplementedError

    def trade_status(self, ref: str) -> dict:
        """{"settled": bool, "profit": float or None} for a trade returned by open_trade."""
        raise NotImplementedError

    def close_trade(self, position: dict) -> dict:
        """Close a position that does not settle itself. Returns {"profit": float}."""
        raise NotImplementedError

    def close(self) -> None:
        return None


class DerivBroker(LiveBroker):
    """Deriv rise/fall contracts (CALL for BUY, PUT for SELL) via DerivCommunityClient."""

    name = "deriv"

    def __init__(self, settings: dict) -> None:
        super().__init__(settings)
        self.client = DerivCommunityClient(
            app_id=settings.get("deriv_app_id", ""),
            token=settings.get("deriv_token", ""),
            rest_url=settings.get("deriv_api_url", ""),
            ws_url=settings.get("deriv_ws_url", ""),
            options_account_mode=settings.get("deriv_options_account_mode", "demo"),
            options_account_id=settings.get("deriv_options_account_id", ""),
        )
        self.account: Optional[dict] = None

    def describe(self) -> dict:
        return {
            "broker": self.name,
            "app_id": self.client.app_id,
            "token_mode": self.client.token_mode,
            "options_account_mode": self.settings.get("deriv_options_account_mode", "demo"),
        }

    def _connected(self) -> dict:
        if self.account is None:
            self.account = self.client.connect()
        return self.account

    def open_trade(self, *, symbol: str, side: str, amount: float, **options) -> dict:
        try:
            account = self._connected()
            contract_type = options.get("contract_type") or ("CALL" if side == "BUY" else "PUT")
            proposal = self.client.propose(
                symbol=symbol,
                contract_type=contract_type,
                amount=amount,
                duration=int(options.get("duration") or self.settings.get("live_trade_duration", 5)),
                duration_unit=str(options.get("duration_unit") or self.settings.get("live_trade_duration_unit", "t")),
                currency=str(options.get("currency") or self.settings.get("live_trade_currency", "USD")),
            )
            proposal_id = str(proposal.get("id") or proposal.get("proposal_id") or "").strip()
            if not proposal_id:
                raise BrokerError("Deriv did not return a proposal ID for this trade.")
            try:
                ask_price = float(proposal.get("ask_price", amount))
            except (TypeError, ValueError):
                ask_price = float(amount)
            buy = self.client.buy(proposal_id, ask_price)
        except DerivServiceError as exc:
            raise BrokerError(str(exc)) from exc
        return {
            "ref": str(buy.get("contract_id") or buy.get("transaction_id") or ""),
            "price": float(buy.get("buy_price") or ask_price),
            "contract_type": contract_type,
            "account": account,
            "proposal": proposal,
            "buy": buy,
        }

    def trade_status(self, ref: str) -> dict:
        try:
            self._connected()
            response = self.client.send({"proposal_open_contract": 1, "contract_id": int(ref)})
        except (DerivServiceError, ValueError) as exc:
            raise BrokerError(str(exc)) from exc
        contract = response.get("proposal_open_contract") or {}
        settled = bool(contract.get("is_sold")) or contract.get("status") in {"won", "lost", "sold"}
        try:
            profit = float(contract.get("profit")) if settled else None
        except (TypeError, ValueError):
            profit = None
        return {"settled": settled and profit is not None, "profit": profit, "status": contract.get("status")}

    def close(self) -> None:
        self.client.close()
        self.account = None


BINANCE_TESTNET_URL = "https://testnet.binance.vision"
BINANCE_MAINNET_URL = "https://api.binance.com"


def _step_floor(value: float, step: float) -> float:
    if step <= 0:
        return value
    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return round(math.floor(value / step + 1e-9) * step, decimals)


class BinanceSpotBroker(LiveBroker):
    """Binance Spot, long only: a market BUY sized in quote currency, closed later by a market SELL.

    Testnet is the default. Mainnet needs binance_testnet=False. The API key never needs
    withdrawal permission; restrict it to your IP.
    """

    name = "binance"
    settles_itself = False
    sides = frozenset({"BUY"})

    def __init__(self, settings: dict, session: Optional[object] = None) -> None:
        super().__init__(settings)
        self.api_key = str(settings.get("binance_api_key") or "").strip()
        self.api_secret = str(settings.get("binance_api_secret") or "").strip()
        self.testnet = bool(settings.get("binance_testnet", True))
        mainnet = str(settings.get("binance_mainnet_url") or BINANCE_MAINNET_URL).rstrip("/")
        self.base_url = BINANCE_TESTNET_URL if self.testnet else mainnet
        self.session = session or requests
        self._filters: Dict[str, dict] = {}
        if not self.api_key or not self.api_secret:
            raise BrokerError("Add a Binance API key and secret before trading on Binance.")

    def describe(self) -> dict:
        return {"broker": self.name, "testnet": self.testnet, "base_url": self.base_url}

    def sign(self, params: dict) -> str:
        query = urlencode(params)
        signature = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return f"{query}&signature={signature}"

    def request(self, method: str, path: str, params: Optional[dict] = None, signed: bool = False) -> object:
        params = dict(params or {})
        url = self.base_url + path
        if signed:
            params.update({"timestamp": int(time.time() * 1000), "recvWindow": 5000})
            url = f"{url}?{self.sign(params)}"
            params = None
        try:
            response = self.session.request(
                method, url, params=params, headers={"X-MBX-APIKEY": self.api_key}, timeout=15
            )
        except requests.RequestException as exc:
            raise BrokerError(f"Binance request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code != 200:
            message = payload.get("msg") if isinstance(payload, dict) else ""
            if response.status_code == 451:
                message = "Binance is not available from this location."
            raise BrokerError(f"Binance HTTP {response.status_code}: {message or 'request rejected'}")
        return payload

    def account(self) -> dict:
        return self.request("GET", "/api/v3/account", signed=True)

    def symbol_filters(self, symbol: str) -> dict:
        if symbol not in self._filters:
            info = self.request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})
            rows = info.get("symbols") or []
            if not rows or rows[0].get("status") != "TRADING":
                raise BrokerError(f"{symbol} is not tradable on Binance Spot.")
            filters = {row["filterType"]: row for row in rows[0].get("filters", [])}
            lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
            notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
            self._filters[symbol] = {
                "step": float(lot.get("stepSize") or 0),
                "min_qty": float(lot.get("minQty") or 0),
                "min_notional": float(notional.get("minNotional") or 0),
                "base": rows[0].get("baseAsset", ""),
            }
        return self._filters[symbol]

    @staticmethod
    def _fill_summary(order: dict, base: str) -> dict:
        qty = float(order.get("executedQty") or 0)
        quote = float(order.get("cummulativeQuoteQty") or 0)
        base_fee = quote_fee = 0.0
        for fill in order.get("fills") or []:
            fee = float(fill.get("commission") or 0)
            if fill.get("commissionAsset") == base:
                base_fee += fee
            else:
                quote_fee += fee * (float(fill.get("price") or 0) if fill.get("commissionAsset") != "USDT" else 1.0)
        return {"qty": qty, "quote": quote, "base_fee": base_fee, "quote_fee": quote_fee}

    def open_trade(self, *, symbol: str, side: str, amount: float, **options) -> dict:
        symbol = symbol.upper()
        if side != "BUY":
            raise BrokerError("Binance Spot is buy-only in the community edition; SELL signals are skipped.")
        filters = self.symbol_filters(symbol)
        if amount < filters["min_notional"]:
            raise BrokerError(f"Stake {amount} is below the Binance minimum order of {filters['min_notional']}.")
        order = self.request(
            "POST", "/api/v3/order",
            {"symbol": symbol, "side": "BUY", "type": "MARKET", "quoteOrderQty": f"{amount:.8f}".rstrip("0")},
            signed=True,
        )
        fills = self._fill_summary(order, filters["base"])
        if fills["qty"] <= 0:
            raise BrokerError(f"Binance did not fill the {symbol} buy (status {order.get('status')}).")
        held = _step_floor(fills["qty"] - fills["base_fee"], filters["step"])
        return {
            "ref": str(order.get("orderId", "")),
            "price": round(fills["quote"], 8),
            "contract_type": "SPOT_BUY",
            "position": {
                "symbol": symbol,
                "qty": held,
                "cost": round(fills["quote"] + fills["quote_fee"], 8),
                "avg_price": round(fills["quote"] / fills["qty"], 8),
            },
        }

    def trade_status(self, ref: str) -> dict:
        return {"settled": False, "profit": None, "status": "open"}

    def close_trade(self, position: dict) -> dict:
        symbol = str(position.get("symbol") or "").upper()
        qty = _step_floor(float(position.get("qty") or 0), self.symbol_filters(symbol)["step"])
        if qty <= 0:
            raise BrokerError(f"Nothing to sell for {symbol}.")
        order = self.request(
            "POST", "/api/v3/order",
            {"symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": f"{qty:.8f}".rstrip("0").rstrip(".")},
            signed=True,
        )
        fills = self._fill_summary(order, self.symbol_filters(symbol)["base"])
        proceeds = fills["quote"] - fills["quote_fee"]
        return {"profit": round(proceeds - float(position.get("cost") or 0), 8), "proceeds": round(proceeds, 8)}


LIVE_BROKERS: Dict[str, Type[LiveBroker]] = {"deriv": DerivBroker, "binance": BinanceSpotBroker}


def live_broker_from_settings(settings: dict) -> LiveBroker:
    name = str(settings.get("broker_provider") or "deriv").strip().lower()
    broker_cls = LIVE_BROKERS.get(name)
    if broker_cls is None:
        raise BrokerError(f"Unknown broker '{name}'. Available: {', '.join(sorted(LIVE_BROKERS))}.")
    return broker_cls(settings)
