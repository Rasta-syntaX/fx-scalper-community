# FX Scalper Community Edition 🦀

A free, open-source automated trading bot for **Deriv.com** options. Run your own instance, contribute features, and learn algorithmic trading.

> **Looking for the cloud SaaS version?** Check out [FX Scalper Cloud](https://fxscalper.io) — multi-user, MT5 support, signal master with quant sniper accuracy, portfolio rebalancing, and more.

---

## ✨ Features

| Feature | Community | Cloud |
|---------|-----------|-------|
| Deriv Options automated trading | ✅ | ✅ |
| Technical indicators (EMA, RSI, MACD, BB) | ✅ | ✅ |
| Market regime detection (trending/ranging) | ✅ | ✅ |
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
git clone https://github.com/Rasta-syntaX/fx-scalper-ass-community-edition.git
cd fx-scalper-ass-community-edition

# Backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Deriv API token
```

### 2. Run Backend

```bash
python backend/app.py
```

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

Opens on **http://localhost:5000**.

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
                    │  (TA-Lib)   │
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
