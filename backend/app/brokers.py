"""Live broker adapters.

The auto-trader and the live trade route only talk to a LiveBroker. Deriv is the
first implementation; to add another broker, subclass LiveBroker, implement
open_trade/trade_status/close, and register it in LIVE_BROKERS under the name
used by the `broker_provider` setting.
"""

from typing import Dict, Optional, Type

from app.deriv_service import DerivCommunityClient, DerivServiceError


class BrokerError(RuntimeError):
    pass


class LiveBroker:
    name = "base"

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


LIVE_BROKERS: Dict[str, Type[LiveBroker]] = {"deriv": DerivBroker}


def live_broker_from_settings(settings: dict) -> LiveBroker:
    name = str(settings.get("broker_provider") or "deriv").strip().lower()
    broker_cls = LIVE_BROKERS.get(name)
    if broker_cls is None:
        raise BrokerError(f"Unknown broker '{name}'. Available: {', '.join(sorted(LIVE_BROKERS))}.")
    return broker_cls(settings)
