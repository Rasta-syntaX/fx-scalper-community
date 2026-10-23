"""Command-line tools for contributors.

    cd backend
    python -m app.cli backtest --replay data/replay_sample.json --symbol frxEURUSD --payout 85

Omit --replay to pull candles from Deriv's public API instead.
"""

import argparse
import json
import os
import sys
from copy import deepcopy
from typing import List, Optional

from app.backtest import run_backtest
from app.server import DEFAULT_STATE, MarketDataError, evaluate_snapshot, provider_from_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="FX Scalper community tools")
    commands = parser.add_subparsers(dest="command", required=True)
    backtest = commands.add_parser("backtest", help="walk-forward backtest of the rule engine over candles")
    backtest.add_argument("--symbol", action="append", required=True, help="repeat for several symbols")
    backtest.add_argument("--asset-class", default="FOREX")
    backtest.add_argument("--replay", help="replay JSON file (default: live Deriv candles)")
    backtest.add_argument("--granularity", type=int, default=300, help="candle size in seconds")
    backtest.add_argument("--candles", type=int, default=1000)
    backtest.add_argument("--horizon", type=int, default=5, help="exit after this many bars")
    backtest.add_argument("--window", type=int, default=100, help="trailing candles the rules see")
    backtest.add_argument("--direction", choices=["both", "buy", "sell"], default="both")
    backtest.add_argument("--payout", type=float, default=0.0, help="broker payout %% on a win, e.g. 85")
    backtest.add_argument("--json", action="store_true", help="print the full JSON report")
    return parser


def print_table(results: List[dict], errors: List[dict]) -> None:
    payout = any(row.get("payout") for row in results)
    header = f"{'symbol':<14}{'trades':>7}{'win %':>8}{'total %':>10}{'max DD %':>10}"
    if payout:
        header += f"{'net/$1':>9}{'BE win %':>10}"
    print(header)
    for row in results:
        win = "-" if row["win_rate"] is None else f"{row['win_rate'] * 100:.1f}"
        line = f"{row['symbol']:<14}{row['trades']:>7}{win:>8}"
        line += f"{row['total_return_pct']:>10.3f}{row['max_drawdown_pct']:>10.3f}"
        if payout:
            line += f"{row['net_per_stake']:>9.2f}{row['break_even_win_rate'] * 100:>10.1f}"
        print(line)
    for error in errors:
        print(f"{error['symbol']:<14}error: {error['error']}")


def backtest(args: argparse.Namespace) -> int:
    settings = deepcopy(DEFAULT_STATE["settings"])
    if args.replay:
        settings.update({"market_source": "replay", "market_replay_file": os.path.abspath(args.replay)})
    else:
        settings["market_source"] = "deriv"
    settings["trade_direction"] = args.direction
    results, errors = [], []
    try:
        provider = provider_from_settings(settings)
    except MarketDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for symbol in args.symbol:
        try:
            candles = provider.get_candles(symbol, granularity=args.granularity, count=args.candles)
            results.append(
                run_backtest(
                    symbol, args.asset_class, candles, settings, evaluate_snapshot,
                    horizon=args.horizon, window=args.window, direction=args.direction,
                    payout=(args.payout / 100.0) or None,
                )
            )
        except MarketDataError as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
    if args.json:
        print(json.dumps({"results": results, "errors": errors}, indent=2))
    else:
        print_table(results, errors)
    return 1 if errors and not results else 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return backtest(args)


if __name__ == "__main__":
    sys.exit(main())
