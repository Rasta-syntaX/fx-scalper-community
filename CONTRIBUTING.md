# Contributing to FX Scalper Community Edition

First off, thanks for taking the time to contribute! 🦀

## Code of Conduct

Be respectful, constructive, and inclusive. We're all here to learn and build cool stuff.

## How to Contribute

### 1. Find or Create an Issue
- Check [existing issues](https://github.com/Rasta-syntaX/fx-scalper-community/issues) first
- If you're fixing a bug or adding a feature, open an issue to discuss it first

### 2. Fork & Branch
```bash
git checkout -b feature/your-feature-name
```

### 3. Make Changes
- Keep the code style consistent with the existing codebase
- Add comments for non-obvious logic
- Update the README if adding new configuration options

### 4. Test
- Test with a Deriv **demo** account first (never real money for testing!)
- Run the backend checks from the repo root: `python -m pytest tests/ -v` and `flake8 backend/`
- Ensure the frontend builds without errors: `cd frontend && npm run build`

### 5. Commit & PR
```bash
git add .
git commit -m "feat: description of your change"
git push origin feature/your-feature-name
```
Open a pull request against the `main` branch.

## Development Setup

```bash
# Backend
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements-dev.txt
cp .env.example .env
cd backend && python -m app.server   # API on http://127.0.0.1:5001

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Project Structure

```
backend/
├── app/
│   ├── server.py         # Flask API, rule engine, paper/live trade routes
│   ├── deriv_service.py  # Deriv REST + WebSocket client (accounts, proposals, buys)
│   ├── market_data.py    # Candle providers: live Deriv and JSON replay
│   ├── snapshot.py       # Candles -> indicator snapshot consumed by the engine
│   └── indicators.py     # EMA, RSI, ATR, ADX, Bollinger, VWAP (stdlib only)
├── data/                 # store.json (runtime state) + replay_sample.json
└── webhooks.py           # Discord / Telegram helpers
frontend/
└── src/
    ├── App.vue           # Single-page dashboard
    └── styles.css
tests/                    # pytest suite (run from the repo root)
```

## Feature Ideas

Check the [issues labeled "good first issue"](https://github.com/Rasta-syntaX/fx-scalper-community/labels/good%20first%20issue) for starter tasks.

---

**One rule**: Keep it open source friendly. No proprietary SaaS features (MT5, multi-user, scalper mode) belong here.
