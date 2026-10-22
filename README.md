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

## 🔔 Webhook Alerts

Get trade notifications sent to Discord or Telegram:

**Discord**: Create a webhook in your server settings → Integrations → Webhooks, paste the URL into `DISCORD_WEBHOOK_URL`.

**Telegram**: Create a bot via [@BotFather](https://t.me/botfather), get the token, find your chat ID, set both in `.env`.

Both can run simultaneously.

---

## 📊 Trade Journal

The bot logs every trade to `logs/trade_log.csv`. You can also export your journal from the web dashboard.

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

**Ideas for contributions:**
- Add new indicators or trading strategies
- Improve the web UI
- Write tests
- Add more notification channels (Slack, email)
- Backtesting engine
- Better error recovery

---

## 📜 License

MIT — see [LICENSE](LICENSE). Free to use, modify, and distribute.

---

## 💬 Community

- **GitHub Issues**: Bug reports & feature requests
- **Discussions**: Strategy sharing & Q&A

Built with ❤️ by [Rasta-syntaX](https://github.com/Rasta-syntaX)
