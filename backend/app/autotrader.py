"""Pure decision logic for the automated trading loop (no I/O, easy to test).

app.server owns the background thread, state persistence and broker calls; it
asks this module what to close, whether a daily limit is hit, and what to open.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

DIRECTION_SIDES = {"both": {"BUY", "SELL"}, "buy": {"BUY"}, "sell": {"SELL"}}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_auto_state() -> dict:
    return {
        "running": False,
        "mode": "paper",
        "day": "",
        "realized_pnl": 0.0,
        "trades_today": 0,
        "halted_reason": "",
        "started_at": None,
        "last_tick": None,
        "last_error": "",
        "pending_live": [],
    }


def parse_iso(value: object) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def roll_day(auto: dict, now: datetime) -> dict:
    """Reset the daily counters at UTC midnight."""
    today = now.astimezone(timezone.utc).date().isoformat()
    if auto.get("day") != today:
        auto.update({"day": today, "realized_pnl": 0.0, "trades_today": 0, "halted_reason": ""})
    return auto


def pending_stake(auto: dict) -> float:
    return sum(float(item.get("stake") or 0.0) for item in auto.get("pending_live", []))


def limit_breached(auto: dict, settings: dict) -> str:
    """Daily profit target / loss limit. Unsettled live stakes count as at risk."""
    realized = float(auto.get("realized_pnl") or 0.0)
    target = float(settings.get("daily_profit_target") or 0.0)
    limit = float(settings.get("daily_loss_limit") or 0.0)
    if target > 0 and realized >= target:
        return f"Daily profit target reached ({realized:.2f} >= {target:.2f})."
    if limit > 0 and pending_stake(auto) - realized >= limit:
        return f"Daily loss limit reached ({realized:.2f} realized, {pending_stake(auto):.2f} at risk)."
    return ""


def paper_pnl(position: dict, price: float) -> float:
    entry = float(position["entry_price"])
    move = (float(price) - entry) / entry * float(position["exposure"])
    return round(move if position["side"] == "BUY" else -move, 2)


def due_positions(portfolio: List[dict], now: datetime, hold_minutes: float) -> List[dict]:
    """Auto-opened paper positions whose holding time is up."""
    cutoff = now - timedelta(minutes=float(hold_minutes))
    due = []
    for position in portfolio:
        opened = parse_iso(position.get("opened_at"))
        if position.get("auto") and opened is not None and opened <= cutoff:
            due.append(position)
    return due


def pick_entries(market: List[dict], portfolio: List[dict], settings: dict, open_count: int) -> List[dict]:
    """Signals to act on: allowed direction, one position per symbol, under max_open_positions."""
    sides = DIRECTION_SIDES.get(str(settings.get("trade_direction") or "both"), DIRECTION_SIDES["both"])
    held = {position["symbol"] for position in portfolio}
    room = max(0, int(settings.get("max_open_positions", 6)) - open_count)
    picks = []
    for row in market:
        if len(picks) >= room:
            break
        if row.get("decision") in sides and row["symbol"] not in held:
            picks.append(row)
            held.add(row["symbol"])
    return picks
