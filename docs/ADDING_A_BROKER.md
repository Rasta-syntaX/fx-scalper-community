# Adding a broker

Live auto-trades go through a small adapter interface in
[`backend/app/brokers.py`](../backend/app/brokers.py). Deriv is the first implementation
(`DerivBroker`). Paper trading never touches an adapter.

## 1. Subclass `LiveBroker`

```python
class MyBroker(LiveBroker):
    name = "mybroker"

    def __init__(self, settings: dict) -> None:
        super().__init__(settings)
        # Read what you need from settings. Never log or return credentials.

    def describe(self) -> dict:
        return {"broker": self.name, "account": "demo"}

    def open_trade(self, *, symbol: str, side: str, amount: float, **options) -> dict:
        # side is "BUY" or "SELL", amount is the stake in account currency.
        return {"ref": "order-123", "price": amount, "contract_type": "CALL"}

    def trade_status(self, ref: str) -> dict:
        # profit is the realized P&L once the trade is closed, negative for a loss.
        return {"settled": True, "profit": 0.85}

    def close(self) -> None:
        pass  # close sockets/sessions
```

The contract the auto-trader relies on:

| Method | Must return |
|---|---|
| `open_trade` | `ref` (string id used for `trade_status`), `price` (amount actually staked/at risk), optional `contract_type` |
| `trade_status` | `settled` (bool) and `profit` (float, only meaningful once settled) |

Raise `BrokerError` for anything that goes wrong (auth, rejected order, network). The loop records
it as `last_error`, sends an `AUTO_ERROR` alert and keeps going. Don't let other exceptions escape.

A new adapter is created for every loop tick and `close()` is always called afterwards.

## Contracts vs positions

Brokers settle trades in one of two ways:

- **Self-settling contracts** (Deriv rise/fall): keep `settles_itself = True`. The auto-trader polls `trade_status(ref)` until it reports a profit.
- **Positions** (Binance Spot): set `settles_itself = False` and implement `close_trade(position)`. `open_trade` returns the position details (quantity, cost), and after `auto_hold_minutes` the auto-trader calls `close_trade`, which must return `{"profit": float}` from real fills minus fees.

Set `sides` to the directions your broker can open, e.g. `frozenset({"BUY"})` for spot. The auto-trader skips other signals and says so in its status instead of sending an order that would fail.

See `BinanceSpotBroker` in `backend/app/brokers.py` and `tests/test_binance.py` for a full example with HMAC signing, exchange filters and mocked HTTP.

## 2. Register it

```python
LIVE_BROKERS = {"deriv": DerivBroker, "mybroker": MyBroker}
```

`live_broker_from_settings` picks the adapter from the `broker_provider` setting (default `deriv`).

## 3. Test it without real money

- Unit-test with a fake: see `FakeBroker` in [`tests/test_autotrader.py`](../tests/test_autotrader.py),
  which drives a full open → settle → loss-limit cycle without a network.
- Then run the auto-trader in live mode against a **demo** account only.
- In your PR, say which account type you tested on. Never paste tokens, account ids or screenshots
  that show them.

## Scope

Community adapters should be for brokers with a public API that anyone can sign up for. MT5
bridges, multi-user features and hosted/cloud modes belong to the commercial edition and are out
of scope here (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
