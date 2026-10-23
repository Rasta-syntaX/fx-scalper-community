# FX Scalper Community Edition 🦀

A free, open-source automated trading bot for **Deriv.com** options. Run your own instance, contribute features, and learn algorithmic trading.

> **Looking for the cloud SaaS version?** Check out [FX Scalper Cloud](https://fxscalper.io) — multi-user, MT5 support, signal master with quant sniper accuracy, portfolio rebalancing, and more.

---

## ✨ Features

| Feature | Community | Cloud |
|---------|-----------|-------|
| Deriv Options automated trading | ✅ | ✅ |
| Technical indicators (EMA, RSI, ADX, ATR, Bollinger, VWAP) | ✅ | ✅ |
| Market regime detection (trending/ranging) | ✅ | ✅ |
| Reads its own candles from Deriv (`POST /api/scan`) | ✅ | ✅ |
| Web dashboard | ✅ | ✅ |
| Discord/Telegram trade alerts | ✅ | ❌* |
| Trade journal CSV export | ✅ | ❌* |
| Demo mode (paper trading) | ✅ | ❌* |
| Docker one-click deploy | ✅ | ❌* |
| MT5 CFD trading | ❌ | ✅ |
| Quant sniper accuracy | ❌ | ✅ |
| Scalper mode ($ risk sizing, trailing SL) | ❌ | ✅ |
| Multi-user SaaS | ❌ | ✅ |
| Portfolio rebalancing | ❌ | ✅ |
| Push notifications | ❌ | ✅ |

\* Community-only features. Cloud has its own notification system.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- A [Deriv.com](https://deriv.com) account (demo or real)
- A Deriv API token ([get one here](https://app.deriv.com/account/api-token))

### 1. Clone & Setup

```bash
git clone https://github.com/Rasta-syntaX/fx-scalper-community.git
cd fx-scalper-community

# Backend
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
```

Your Deriv app ID and API token are entered in the dashboard under **Settings** (or exported as
`COMMUNITY_DERIV_APP_ID` / `COMMUNITY_DERIV_TOKEN` before starting the backend).

### 2. Run Backend

```bash
cd backend
python -m app.server
```

The API listens on **http://127.0.0.1:5001** (`FLASK_HOST` / `FLASK_PORT` to change it). The Vite
dev server proxies `/api` there automatically.

### 3. Run Frontend (separate terminal)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

### 🐳 Docker (one command)

```bash
docker compose up -d
```

Dashboard on **http://localhost:5173**, API on **http://localhost:5001**. Run `cp .env.example .env`
first — Compose reads it.

---

## ⚙️ Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DERIV_APP_ID` | `1089` | Deriv application ID |
| `DERIV_API_TOKEN` | — | Your Deriv API token (required) |
| `ACCOUNT_MODE` | `demo` | `demo` or `real` |
| `SYMBOLS` | `frxEURUSD,...` | Comma-separated trading symbols |
| `MAX_TRADES` | `3` | Max concurrent open trades |
| `STAKE_AMOUNT` | `1` | Trade stake in USD |
| `MAX_MULTIPLIER` | `100` | Max multiplier for options |
| `TRADE_DIRECTION` | `both` | `buy`, `sell`, or `both` |
| `DAILY_PROFIT_TARGET` | `0` | Stop after hitting this profit (0=off) |
| `DAILY_LOSS_LIMIT` | `0` | Stop after hitting this loss (0=off) |
| `DISCORD_WEBHOOK_URL` | — | Discord trade alert webhook |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token for alerts |
| `TELEGRAM_CHAT_ID` | — | Telegram chat/user ID |

---

## 📈 Market Data & Scanning

The rule engine evaluates *market snapshots*. `POST /api/scan` builds them for you: it fetches
candles, computes the indicators, and feeds the same rule engine the dashboard already uses.

```bash
curl -X POST http://localhost:5001/api/scan
```

Pick the data source with environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `COMMUNITY_MARKET_SOURCE` | `deriv` | `deriv` for live candles, `replay` for a JSON fixture |
| `COMMUNITY_REPLAY_FILE` | — | Path to the replay fixture (required when source is `replay`) |
| `COMMUNITY_DATA_DIR` | `backend/data` | Directory holding `store.json` |

The same values can be set through `POST /api/config` as `market_source`, `market_replay_file`,
`market_granularity` (candle size in seconds) and `market_candle_count`.

### Try it with no credentials

A sample candle fixture ships in the repo, so you can watch the engine produce signals without
a Deriv account:

```bash
cd backend
COMMUNITY_MARKET_SOURCE=replay \
COMMUNITY_REPLAY_FILE=data/replay_sample.json \
python -m app.server
```

Add `frxEURUSD` under Settings → Configured Symbols JSON, save, then press **Scan Market Now**.
The Signal Feed fills from real indicator maths: EMA fast/slow, ADX, RSI, ATR ratio, a VWAP
position, Bollinger band proximity and a candle quality check.

### Indicators

Implemented in `backend/app/indicators.py` using the standard library only — no TA-Lib, no
pandas, no numpy. Each function returns a series aligned to its input, using `None` while the
window is still warming up.

---

## 🔒 Security

This bot can place real trades, so treat the API like a wallet:

- The saved Deriv token is **write-only**: `/api/bootstrap` and `/api/config` return
  `deriv_token: ""` plus `deriv_token_set` / `deriv_token_mode`. Leave the field blank to keep the
  saved token, or press **Forget saved token** to clear it.
- Set `COMMUNITY_API_KEY` to require an `X-API-Key` header on every `/api/*` route except
  `/api/health`. Do this whenever the backend is reachable from anything other than your own machine.
- CORS only allows the local dashboard origins by default. Set `COMMUNITY_CORS_ORIGINS` if you host
  the frontend elsewhere.

---

## 📉 Backtesting

**Run Backtests** (or `POST /api/backtests/run`) replays the same rule engine used by live scans over
real candles from your market source, for every configured symbol:

- At each bar the engine only sees the trailing 100 candles, so there is no look-ahead.
- A BUY/SELL signal enters at the **next** bar's open and exits at the close `horizon_bars` later
  (default 5), like a fixed-duration contract. Positions never overlap.
- Reports trades, win rate, total/average move, max drawdown and recent trades per symbol.

```bash
curl -X POST localhost:5001/api/backtests/run -H 'Content-Type: application/json' \
  -d '{"horizon_bars": 5, "candle_count": 2000}'
```

Results are raw price moves, so the win rate means "direction was right", not "this would have
been profitable". Set **Payout %** (or `"payout_pct": 85`) to also score every trade as a $1
fixed-stake contract (+0.85 on a win, -1 on a loss). You then get `net_per_stake`,
`expectancy_per_stake`, `max_drawdown_stake` and `break_even_win_rate` (`1 / (1 + p)`, about 54% at 85%).
Spreads and slippage are still not modelled. Each result has an `equity_curve`, drawn as a chart
on the dashboard. The three fixed rule self-checks still run alongside.

### Backtest from the command line

No UI needed, handy for trying strategy changes:

```bash
cd backend
python -m app.cli backtest --replay data/replay_sample.json --symbol frxEURUSD --payout 85
python -m app.cli backtest --symbol frxEURUSD --symbol frxGBPUSD --horizon 3 --json   # live Deriv candles
```

Options: `--horizon`, `--window`, `--candles`, `--granularity`, `--direction both|buy|sell`, `--json`.

---

## 🤖 Auto-Trader

The **Auto-Trader** card (or `POST /api/auto/start` with `{"mode": "paper"}`) runs a background loop
every `auto_scan_interval_seconds` (default 300):

1. Settles pending live contracts and adds their profit/loss to today's realized P&L.
2. Scans the market, then closes auto-opened paper positions after `auto_hold_minutes`.
3. Stops opening trades for the rest of the UTC day once `daily_profit_target` or `daily_loss_limit`
   is hit (0 = off). Unsettled live stakes count as at risk toward the loss limit.
4. Opens one trade per new BUY/SELL signal allowed by `trade_direction` (`both`, `buy`, `sell`),
   up to `max_open_positions`.

- **Paper first:** live mode needs **Live trading enabled** in settings and an extra confirmation.
- **Kill switch:** **Stop** (`POST /api/auto/stop`) halts the loop immediately. Restarting the
  server never resumes trading on its own.
- **Brokers:** live orders go through `backend/app/brokers.py`. Deriv is the first adapter; add
  another by subclassing `LiveBroker` and registering it in `LIVE_BROKERS`.

### Risk guards

All are off at 0 and reset at UTC midnight unless noted.

| Setting | Effect |
|---|---|
| `max_trades_per_day` | Halts for the day after this many auto trades. |
| `max_loss_streak` | Halts for the day after this many losing trades in a row. |
| `loss_cooldown_minutes` | Pauses new entries for this long after any loss (carries over midnight). |
| `trading_hours_start` / `trading_hours_end` | Only opens trades in this UTC hour window, e.g. `7`–`16` for London/NY overlap. `22`–`6` wraps past midnight; equal values mean all day. |

A *halt* stops new entries until the next UTC day; a *pause* (cooldown, outside hours) lifts by
itself. Open positions are still managed and closed either way.

### Performance and daily summary

The card shows win rate and P&L per symbol plus an equity curve over the last 200 closed auto
trades (paper and live). At the first tick of each new UTC day the loop posts a
**daily summary** (trades, wins/losses, realized P&L) to the journal and to Discord/Telegram.

Every start, stop, open, close, settlement, halt, error and daily summary lands in the journal and the alerts.

---

## 🔔 Webhook Alerts

Get trade notifications sent to Discord or Telegram:

**Discord**: Create a webhook in your server settings → Integrations → Webhooks, paste the URL into `DISCORD_WEBHOOK_URL`.

**Telegram**: Create a bot via [@BotFather](https://t.me/botfather), get the token, find your chat ID, set both in `.env`.

Both can run simultaneously.

---

## 📊 Trade Journal

Every paper trade, live trade, live error and rebalance close is appended to `logs/trade_log.csv`
(override the folder with `COMMUNITY_LOG_DIR`). Download it with **Export CSV** under Recent Activity
or `GET /api/journal.csv`.

The same events are sent to Discord/Telegram when those variables are set.

---

## 🧪 Demo Mode

Set `ACCOUNT_MODE=demo` in your `.env` to trade on Deriv's demo account (virtual funds). Perfect for testing strategies risk-free.

---

## 🧪 Tests

```bash
pip install -r backend/requirements-dev.txt
python -m pytest tests/ -v
flake8 backend/app
```

The suite covers the indicator maths, both market data providers, and the frozen snapshot
contract — including an end-to-end trending-candles → BUY and falling-candles → SELL check
through the real rule engine and the real Flask API.

---

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Vue 3     │────▶│  Flask API   │────▶│  Deriv WS   │
│  Frontend   │     │   Backend    │     │   Client    │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                    ┌──────┴──────┐
                    │  Trading    │
                    │   Engine    │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │ Indicators  │
                    │  (stdlib)   │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │   Candles   │
                    │ Deriv/       │
                    │ replay       │
                    └─────────────┘
```

---

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

- **Add your broker:** [docs/ADDING_A_BROKER.md](docs/ADDING_A_BROKER.md) walks through a live-broker adapter.
- **Pick something up:** [ROADMAP.md](ROADMAP.md) lists good first issues and bigger projects.

---

## 📜 License

MIT — see [LICENSE](LICENSE). Free to use, modify, and distribute.

---

## 💬 Community

- **GitHub Issues**: Bug reports & feature requests
- **Discussions**: Strategy sharing & Q&A

Built with ❤️ by [Rasta-syntaX](https://github.com/Rasta-syntaX) and contributors
