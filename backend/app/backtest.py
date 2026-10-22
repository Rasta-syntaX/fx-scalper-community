"""Walk-forward backtest over real candles, using the same rule engine as live scans.

At every bar the engine sees only the trailing `window` candles. A BUY/SELL
signal enters at the next bar's open (no look-ahead) and exits at the close
`horizon` bars later, like a fixed-duration contract. Positions never overlap.
Returns are raw price moves in percent; broker payouts and spreads are not
modelled, so treat the win rate as "direction was right", not as profit.
"""

from typing import Callable, Dict, List, Mapping, Optional, Sequence

from app.market_data import Candle, MarketDataError
from app.snapshot import IndicatorSettings, build_snapshot, minimum_candles

MAX_TRADES_RETURNED = 50
DIRECTIONS = {"both": {"BUY", "SELL"}, "buy": {"BUY"}, "sell": {"SELL"}}


def clamp_int(value: object, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def contiguous_tail(candles: Sequence[Candle]) -> List[Candle]:
    """Longest run of strictly increasing epochs ending at the last candle.

    Replay fixtures are cycled when shorter than the requested count; the
    seam would otherwise read as a price gap.
    """
    if not candles:
        return []
    start = len(candles) - 1
    while start > 0 and candles[start - 1].epoch < candles[start].epoch:
        start -= 1
    return list(candles[start:])


def _max_drawdown(returns: Sequence[float]) -> float:
    peak = equity = drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def run_backtest(
    symbol: str,
    asset_class: str,
    candles: Sequence[Candle],
    settings: Optional[Mapping],
    evaluate: Callable[[dict, Mapping], dict],
    horizon: int = 5,
    window: int = 100,
    direction: str = "both",
) -> Dict[str, object]:
    settings = settings or {}
    config = IndicatorSettings.from_settings(settings)
    candles = contiguous_tail(candles)
    window = max(int(window), minimum_candles(config))
    horizon = max(1, int(horizon))
    allowed = DIRECTIONS.get(str(direction or "both").lower(), DIRECTIONS["both"])
    if len(candles) < window + horizon + 1:
        raise MarketDataError(
            "{} needs at least {} contiguous candles for a {}-bar window and {}-bar exit, got {}".format(
                symbol, window + horizon + 1, window, horizon, len(candles)
            )
        )

    trades: List[dict] = []
    evaluated = signals = skipped = 0
    index = window - 1
    while index + horizon < len(candles):
        try:
            snapshot = build_snapshot(symbol, asset_class, candles[index - window + 1:index + 1], config)
        except MarketDataError:
            skipped += 1
            index += 1
            continue
        evaluated += 1
        decision = evaluate(snapshot, settings).get("decision")
        if decision not in allowed:
            index += 1
            continue
        signals += 1
        entry_bar, exit_bar = candles[index + 1], candles[index + horizon]
        move = (exit_bar.close - entry_bar.open) / entry_bar.open * 100.0
        result = move if decision == "BUY" else -move
        trades.append(
            {
                "side": decision,
                "entry_epoch": entry_bar.epoch,
                "exit_epoch": exit_bar.epoch,
                "entry": round(entry_bar.open, 5),
                "exit": round(exit_bar.close, 5),
                "return_pct": round(result, 4),
            }
        )
        index += horizon

    returns = [trade["return_pct"] for trade in trades]
    wins = sum(1 for value in returns if value > 0)
    return {
        "symbol": symbol,
        "asset_class": asset_class,
        "candles": len(candles),
        "period_start": candles[0].epoch,
        "period_end": candles[-1].epoch,
        "window": window,
        "horizon_bars": horizon,
        "bars_evaluated": evaluated,
        "bars_skipped": skipped,
        "signals": signals,
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "win_rate": round(wins / len(trades), 4) if trades else None,
        "avg_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
        "total_return_pct": round(sum(returns), 4),
        "max_drawdown_pct": round(_max_drawdown(returns), 4),
        "best_pct": max(returns) if returns else None,
        "worst_pct": min(returns) if returns else None,
        "recent_trades": trades[-MAX_TRADES_RETURNED:],
    }
