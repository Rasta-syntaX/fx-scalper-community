"""Test bootstrap: make the backend package importable from the repo root.

CI runs "pytest tests/" from the repository root, so app.* lives one level down
in backend/.
"""

import os
import sys
import tempfile

import pytest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# Keep the suite away from the developer's real store.json. app.server resolves
# its data directory at import time, so this has to run before any test module
# imports it.
os.environ.setdefault("COMMUNITY_DATA_DIR", tempfile.mkdtemp(prefix="fx-scalper-community-tests-"))


@pytest.fixture
def make_candles():
    """Build OHLC rows from a list of closes."""

    def _make(closes, spread=0.0002, start=1700000000, step=300):
        rows = []
        for index, close in enumerate(closes):
            open_ = closes[index - 1] if index else close
            high = max(open_, close) + spread
            low = min(open_, close) - spread
            rows.append(
                {
                    "epoch": start + index * step,
                    "open": round(open_, 5),
                    "high": round(high, 5),
                    "low": round(low, 5),
                    "close": round(close, 5),
                }
            )
        return rows

    return _make
