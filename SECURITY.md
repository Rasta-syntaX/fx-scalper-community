# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private
[security advisory form](https://github.com/Rasta-syntaX/fx-scalper-community/security/advisories/new) instead.
We aim to reply within a week.

## Running the bot safely

- The server binds to `127.0.0.1` with debug off. Don't expose it to the internet. If you must, set `COMMUNITY_API_KEY`.
- Broker credentials are write-only: the API never returns them. They are stored in plain JSON under `backend/data/`, so protect that folder.
- Use demo/testnet accounts first. Binance keys must never have withdrawal permission; restrict them to your IP.
- Never commit `backend/data/`, `logs/` or any key, token or `.env` file.
