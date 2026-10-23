"""Pure decision logic for the automated trading loop (no I/O, easy to test).

app.server owns the background thread, state persistence and broker calls; it
asks this module what to close, whether a daily limit is hit, and what to open.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

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
        "paused_reason": "",
        "wins_today": 0,
        "losses_today": 0,
        "loss_streak": 0,
        "cooldown_until": None,
        "closed_trades": [],
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
        auto.update(
            {
                "day": today,
                "realized_pnl": 0.0,
                "trades_today": 0,
                "halted_reason": "",
                "wins_today": 0,
                "losses_today": 0,
                "loss_streak": 0,
            }
        )
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


MAX_CLOSED_TRADES = 200


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def day_summary(auto: dict, now: datetime) -> str:
    """One-line recap of the previous UTC day, or "" if the day hasn't changed or nothing happened."""
    day = auto.get("day")
    if not day or day == now.astimezone(timezone.utc).date().isoformat():
        return ""
    trades, wins, losses = (int(auto.get(key) or 0) for key in ("trades_today", "wins_today", "losses_today"))
    if not (trades or wins or losses):
        return ""
    return "{}: {} trades opened, {} won / {} lost, realized P&L {:+.2f}.".format(
        day, trades, wins, losses, float(auto.get("realized_pnl") or 0.0)
    )


def record_close(auto: dict, settings: dict, *, symbol: str, side: str, pnl: object, now: datetime, mode: str) -> None:
    """Book a closed/settled trade: daily P&L, win/loss counters, loss streak, cooldown, history."""
    pnl = round(float(pnl), 2)
    auto["realized_pnl"] = round(float(auto.get("realized_pnl") or 0.0) + pnl, 2)
    if pnl > 0:
        auto["wins_today"] = int(auto.get("wins_today") or 0) + 1
        auto["loss_streak"] = 0
    elif pnl < 0:
        auto["losses_today"] = int(auto.get("losses_today") or 0) + 1
        auto["loss_streak"] = int(auto.get("loss_streak") or 0) + 1
        cooldown = float(settings.get("loss_cooldown_minutes") or 0)
        if cooldown > 0:
            auto["cooldown_until"] = iso(now + timedelta(minutes=cooldown))
    closed = list(auto.get("closed_trades") or [])
    closed.append({"closed_at": iso(now), "symbol": symbol, "side": side, "pnl": pnl, "mode": mode})
    auto["closed_trades"] = closed[-MAX_CLOSED_TRADES:]


def in_trading_hours(now: datetime, start: object, end: object) -> bool:
    """UTC hour window [start, end). start == end means always; start > end wraps past midnight."""
    start, end = int(start or 0), int(end or 0)
    if start == end or (start == 0 and end == 24):
        return True
    hour = now.astimezone(timezone.utc).hour
    return start <= hour < end if start < end else (hour >= start or hour < end)


def blocking_reason(auto: dict, settings: dict, now: datetime) -> Tuple[str, bool]:
    """Why no new trade may open right now, and whether that halts trading for the rest of the day."""
    reason = limit_breached(auto, settings)
    if reason:
        return reason, True
    max_trades = int(settings.get("max_trades_per_day") or 0)
    if max_trades and int(auto.get("trades_today") or 0) >= max_trades:
        return f"Max trades per day reached ({max_trades}).", True
    max_streak = int(settings.get("max_loss_streak") or 0)
    streak = int(auto.get("loss_streak") or 0)
    if max_streak and streak >= max_streak:
        return f"{streak} losses in a row (limit {max_streak}).", True
    until = parse_iso(auto.get("cooldown_until"))
    if until is not None and now < until:
        return f"Cooling down after a loss until {auto['cooldown_until']}.", False
    start, end = int(settings.get("trading_hours_start") or 0), int(settings.get("trading_hours_end") or 0)
    if not in_trading_hours(now, start, end):
        return f"Outside trading hours ({start:02d}:00-{end:02d}:00 UTC).", False
    return "", False


def performance(closed_trades: List[dict]) -> dict:
    """Win rate and P&L per symbol plus a cumulative equity curve from closed auto trades."""
    by_symbol: dict = {}
    equity, curve, wins = 0.0, [], 0
    for trade in closed_trades:
        pnl = float(trade.get("pnl") or 0.0)
        row = by_symbol.setdefault(trade["symbol"], {"symbol": trade["symbol"], "trades": 0, "wins": 0, "pnl": 0.0})
        row["trades"] += 1
        row["wins"] += 1 if pnl > 0 else 0
        row["pnl"] = round(row["pnl"] + pnl, 2)
        wins += 1 if pnl > 0 else 0
        equity = round(equity + pnl, 2)
        curve.append(equity)
    for row in by_symbol.values():
        row["win_rate"] = round(row["wins"] / row["trades"], 4)
    total = len(closed_trades)
    return {
        "trades": total,
        "wins": wins,
        "win_rate": round(wins / total, 4) if total else None,
        "pnl": equity,
        "by_symbol": sorted(by_symbol.values(), key=lambda row: row["pnl"], reverse=True),
        "equity_curve": curve,
    }
