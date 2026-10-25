# Changelog

## Unreleased

### Added
- Binance as a public market-data source (scans, backtests, paper auto-trading, CLI `--source binance`).
- Binance Spot broker: testnet by default, buys only, market BUY sized in quote currency and closed by the auto-trader after the hold time or with *Sell now*. Exchange filters and fill-based P&L with fees.
- Mainnet confirmation before live auto-trading on Binance; write-only Binance keys.
- Fee-aware backtests (`fee_pct`, net return, net drawdown); 0.1% per side default on Binance.
- Broker lifecycle: `settles_itself`, `sides` and `close_trade` for position-style brokers.
- Dashboard: tabs, mobile layout with bottom tab bar, 10-second status polling with stale indicator, toasts, confirm dialog, light/dark theme, demo data button, symbol picker, candle chart with trade markers, journal table.
- API: `GET /api/candles`, `GET /api/journal`, `POST /api/demo`, `POST /api/live-positions/<ref>/close`.
- `SECURITY.md`, Dependabot.

## Earlier

- Security hardening, candle backtester, payout-aware economics, paper-first auto-trader with risk guards, alerts and CSV journal, CLI backtester, contributor docs.
