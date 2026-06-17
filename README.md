# FX Scalper Community

FX Scalper Community is a self-hosted trading sandbox for rule evaluation, portfolio rebalancing, scenario backtests, paper execution, and optional Deriv live-order submission. It ships with a lightweight Flask backend and Vue 3 frontend so you can configure your own workspace, add your own Deriv credentials, define your own tradable symbols, and test your own market snapshots locally.

## What It Does

- stores your workspace configuration locally
- supports paper-trade entry and portfolio tracking
- supports Deriv connection testing and optional live-order submission
- evaluates market snapshots with a simplified public rule stack
- generates rebalance actions from configurable target allocations
- runs built-in scenario backtests for quick validation
- supports deployment at the domain root or under a subpath

## Important Default Behavior

This project does **not** ship with a preloaded broker account, symbol list, or live market feed. A fresh install starts with an empty workspace so you can configure it for your own environment.

To use it effectively, you should provide:

- your own Deriv app ID
- your own Deriv API token
- your own symbol definitions
- your own market snapshot data

## Project Structure

- `backend/`: Flask API, local state store, paper-trade engine, Deriv broker layer, rebalance logic, and backtests
- `frontend/`: Vue 3 dashboard and build configuration
- `docker-compose.yml`: local multi-service stack for self-hosting

## Requirements

- Python 3.11 or newer recommended
- Node.js 20 or newer recommended
- npm

## Quick Start

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m app.server
```

The backend listens on `http://localhost:5001`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend listens on `http://localhost:5173`.

## Docker

Start the full stack with:

```bash
docker compose up --build
```

## First-Time Setup

Open the dashboard, go to **Settings**, and provide your own values.

### 1. Add Deriv Credentials

Enter:

- `Deriv App ID`
- `Deriv API Token`
- `Deriv REST URL`
- `Deriv WebSocket URL`

These values are stored locally in the backend data file for your self-hosted instance.

You can also provide credentials through environment variables before starting the backend:

```bash
export COMMUNITY_DERIV_APP_ID=your_app_id
export COMMUNITY_DERIV_TOKEN=your_token
export COMMUNITY_DERIV_API_URL=https://api.derivws.com
export COMMUNITY_DERIV_WS_URL=wss://ws.derivws.com/websockets/v3
export COMMUNITY_DATA_DIR=$HOME/.fx-scalper-community
python3 -m app.server
```

`COMMUNITY_DATA_DIR` is optional and can be used when you want the backend state file stored outside the repository directory.

### 2. Configure Symbols

Paste a JSON array in the **Configured Symbols JSON** field.

Example:

```json
[
  {
    "symbol": "frxEURUSD",
    "label": "EUR/USD",
    "asset_class": "FOREX"
  },
  {
    "symbol": "cryBTCUSD",
    "label": "BTC/USD",
    "asset_class": "CRYPTO"
  }
]
```

Supported asset classes include:

- `FOREX`
- `COMMODITIES`
- `CRYPTO`
- `SYNTHETICS`
- `INDICES`
- `STOCKS`
- `CUSTOM`

### 3. Configure Market Snapshots

Paste a JSON array in the **Market Snapshots JSON** field. Each snapshot should reference a configured symbol.

Example:

```json
[
  {
    "symbol": "frxEURUSD",
    "price": 1.0865,
    "ema_fast": 1.0862,
    "ema_slow": 1.0851,
    "adx": 22,
    "rsi": 55,
    "atr_ratio": 1.04,
    "price_vs_vwap": "above",
    "candle_quality": "clean",
    "distance_to_band": 0.45
  },
  {
    "symbol": "cryBTCUSD",
    "price": 67220,
    "ema_fast": 67080,
    "ema_slow": 66990,
    "adx": 27,
    "rsi": 60,
    "atr_ratio": 1.09,
    "price_vs_vwap": "above",
    "candle_quality": "clean",
    "distance_to_band": 0.52
  }
]
```

### 4. Save Settings

After saving:

- the setup checklist updates automatically
- the signal feed evaluates your snapshots
- the paper-trade form uses your configured symbols
- rebalancing uses your portfolio and target allocation settings
- live-trade defaults are stored for optional broker execution

### 5. Test The Broker Connection

Open the **Broker Connection** panel and run **Test Deriv Connection** after saving your credentials.

The connection test:

- validates that your app ID and token can authenticate
- resolves the appropriate Deriv account flow for the token type
- stores the most recent broker status locally in the dashboard state
- helps confirm readiness before any live order is attempted

PAT tokens use the Deriv options-account flow. Non-PAT tokens use the standard WebSocket authorize flow.

### 6. Optional Live Trading

Live trading is disabled by default. To enable it:

- turn on **Live trading enabled** in **Settings**
- choose the correct options account mode: `demo` or `real`
- save your settings
- test the broker connection
- submit a live order from **Live Trade Entry** or directly from a qualified signal

The dashboard maps:

- `BUY` to Deriv `CALL`
- `SELL` to Deriv `PUT`

Live order defaults include:

- stake
- currency
- duration
- duration unit

These values can be adjusted in settings and are applied when submitting a live order.

## Deployment

The frontend can be deployed at the domain root or under a subpath such as:

- `https://www.fx-scalper.com/communityedition/`

### Build For A Subpath

```bash
cd frontend
VITE_PUBLIC_BASE_PATH=/communityedition/ npm run build
```

If the API is exposed at a custom URL, set an explicit base URL during the frontend build:

```bash
VITE_API_BASE_URL=https://www.fx-scalper.com/communityedition/api/ npm run build
```

### Reverse Proxy Example

When hosting under `/communityedition/`, configure your reverse proxy to:

- serve the frontend build output at `/communityedition/`
- forward `/communityedition/api/` to the Flask backend
- remove the `/communityedition` prefix before forwarding requests to Flask

Example nginx configuration:

```nginx
location /communityedition/ {
    alias C:/inetpub/wwwroot/fx-scalper-community/;
    try_files $uri $uri/ /communityedition/index.html;
}

location /communityedition/api/ {
    rewrite ^/communityedition/(api/.*)$ /$1 break;
    proxy_pass http://127.0.0.1:5001;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

This pattern works well with Cloudflare in front of nginx or IIS.

## Notes For Builders

- This project is designed as a self-hosted community base, not a managed service.
- It defaults to paper trading, local state persistence, and disabled live trading.
- It is intended to be configured, extended, and adapted to your own workflow.
- Broker credentials and workspace state are stored locally for your self-hosted instance unless you replace the storage layer.

## Disclaimer

FX Scalper Community is provided for experimentation, simulation, workflow development, and self-directed broker integration. It does not provide financial advice, and you are responsible for reviewing, validating, and safely operating any live connection you enable in your own environment.
