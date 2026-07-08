# Contributing to FX Scalper Community Edition

First off, thanks for taking the time to contribute! 🦀

## Code of Conduct

Be respectful, constructive, and inclusive. We're all here to learn and build cool stuff.

## How to Contribute

### 1. Find or Create an Issue
- Check [existing issues](https://github.com/Rasta-syntaX/fx-scalper-ass-community-edition/issues) first
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
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Deriv demo token
python backend/app.py

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Project Structure

```
backend/
├── app.py            # Flask server & routes
├── trading_bot.py    # Core trading engine
├── deriv_api.py      # Deriv WebSocket client
├── indicators.py     # Technical indicators
frontend/
├── src/
│   ├── App.vue       # Main dashboard
│   ├── components/   # Vue components
│   └── ...
```

## Feature Ideas

Check the [issues labeled "good first issue"](https://github.com/Rasta-syntaX/fx-scalper-ass-community-edition/labels/good%20first%20issue) for starter tasks.

---

**One rule**: Keep it open source friendly. No proprietary SaaS features (MT5, multi-user, scalper mode) belong here.
