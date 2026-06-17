# FX Scalper Community

FX Scalper Community is a public-safe, watered-down companion application for paper trading, simplified rule workflows, and portfolio simulation. It preserves the product shape and workflow while intentionally removing private alpha, live broker execution, and sensitive operational tooling.

## Included

- Flask backend with JSON file persistence
- Vue 3 frontend with a glassmorphic dashboard
- Paper trading only
- Simplified public rule engine
- Portfolio rebalancing by asset class or symbol
- Built-in scenario backtests

## Excluded

- Live Deriv or MT5 trading
- Private confluence logic and execution infrastructure
- Credential storage, subscriptions, and production secrets

## Structure

- `backend/` API, paper portfolio engine, rebalancing, and backtests
- `frontend/` Vue dashboard
- `docker-compose.yml` local multi-container setup

## Local Development

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m app.server
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend default: `http://localhost:5173`

Backend default: `http://localhost:5001/api/health`

## Docker

```bash
docker compose up --build
```

## Private-Style Hosting

You can publish the app under your own domain without exposing the GitHub repository in the user-facing experience.

Example public URL:

- `https://www.fx-scalper.com/communityedition/`

### Frontend build for a subpath

Build the frontend with a public base path that matches your site path:

```bash
cd frontend
VITE_PUBLIC_BASE_PATH=/communityedition/ npm run build
```

If your reverse proxy exposes the backend under the same subpath, the frontend will automatically call:

- `/communityedition/api/bootstrap`
- `/communityedition/api/config`
- `/communityedition/api/paper-trades/open`

If you want the frontend to call a different API origin or path, set:

```bash
VITE_API_BASE_URL=https://www.fx-scalper.com/communityedition/api/ npm run build
```

### Reverse proxy shape

The simplest production pattern is:

- serve the built frontend at `/communityedition/`
- proxy `/communityedition/api/` to the Flask backend
- strip the `/communityedition` prefix before forwarding to Flask so the backend still receives `/api/...`

Example nginx location blocks:

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

### IIS / Cloudflare notes

- Cloudflare should point only to your domain; users never need the GitHub URL.
- IIS can host the built frontend files, while nginx or IIS URL Rewrite forwards `/communityedition/api/` to Flask.
- Do not place GitHub links in the app UI, footer, or public docs if you want the deployment to feel fully first-party.
- If you want true source anonymity, keep the repository private or mirror from a non-personal account before sharing broadly.

## Notes

This repository is meant for learning, paper trading, community extensions, and experimentation. It is not financial advice and should not be treated as a live-trading system.
