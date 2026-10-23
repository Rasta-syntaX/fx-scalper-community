# Roadmap

Ideas for where the community edition goes next. Comment on or open an issue before starting
something big so work isn't duplicated.

## Good first issues

- **Spread in the backtester:** subtract a configurable spread (in pips or %) from each trade.
- **More replay fixtures:** record candle files for other symbols/timeframes into `backend/data/`.
- **CLI `--csv`:** let `python -m app.cli backtest` write trades to a CSV file.
- **Slack or email alerts:** add a channel next to Discord/Telegram in `backend/app/notifications.py`.
- **Dark/light theme toggle** for the dashboard.
- **Journal filters:** export only one symbol or date range from `GET /api/journal.csv`.
- **Tests:** more rule-engine edge cases in `tests/`.

## Bigger projects

- **Another broker adapter** behind `LiveBroker` (see [docs/ADDING_A_BROKER.md](docs/ADDING_A_BROKER.md)).
- **Parameter sweep:** run the backtest over a grid of indicator settings and rank the results,
  with a held-out period to catch overfitting.
- **Pluggable strategies:** let contributors drop in a strategy module next to the default rule engine.
- **Trailing stop / take-profit** for paper auto-trades instead of a fixed hold time.
- **Session-aware stats:** win rate split by London/NY/Asia session.

## Done

- Real candle backtest with payout-aware scoring and a CLI
- Paper-first auto-trader with daily limits, trade direction, max trades/day, loss-streak halt,
  loss cooldown and UTC trading hours
- Performance panel, equity curves and daily summary alerts
- Discord/Telegram alerts and CSV trade journal
- Broker adapter interface (Deriv first)
- Token never returned by the API, optional API key, local-only CORS
