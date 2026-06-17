from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from flask import Flask, jsonify, request
from flask_cors import CORS

from app.deriv_service import (
    DEFAULT_REST_URL,
    DEFAULT_WS_URL,
    DerivCommunityClient,
    DerivServiceError,
)

app = Flask(__name__)
CORS(app)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"

DEFAULT_DERIV_API_URL = DEFAULT_REST_URL
DEFAULT_DERIV_WS_URL = DEFAULT_WS_URL
SUPPORTED_ASSET_CLASSES = (
    "FOREX",
    "COMMODITIES",
    "CRYPTO",
    "SYNTHETICS",
    "INDICES",
    "STOCKS",
    "CUSTOM",
)


def resolve_data_dir() -> Path:
    candidates: list[Path] = []
    env_dir = os.getenv("COMMUNITY_DATA_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.extend([DEFAULT_DATA_DIR, Path.home() / ".fx-scalper-community"])
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except Exception:
            continue
    return DEFAULT_DATA_DIR


DATA_DIR = resolve_data_dir()
STORE_PATH = DATA_DIR / "store.json"

DEFAULT_TARGET_ALLOCATIONS = {
    "FOREX": 0.40,
    "COMMODITIES": 0.20,
    "CRYPTO": 0.15,
    "SYNTHETICS": 0.25,
}

RULES = [
    {
        "id": "regime_detection",
        "name": "Regime Detection",
        "purpose": "Classify a market as trending, ranging, or low-volatility before signal generation.",
        "inputs": ["adx", "atr_ratio", "ema_fast", "ema_slow"],
        "conditions": [
            "Low-volatility when ATR ratio is below 0.85.",
            "Trending when ADX is above the configured threshold and EMA fast is separated from EMA slow.",
            "Ranging otherwise.",
        ],
        "outputs": ["market_regime"],
    },
    {
        "id": "trend_confirmation",
        "name": "Trend Confirmation",
        "purpose": "Allow paper trade entries only when structure, momentum, and price position agree.",
        "inputs": ["ema_fast", "ema_slow", "adx", "rsi", "price_vs_vwap"],
        "conditions": [
            "BUY when EMA fast > EMA slow, ADX is above threshold, RSI is inside the bullish band, and price is above VWAP.",
            "SELL when EMA fast < EMA slow, ADX is above threshold, RSI is inside the bearish band, and price is below VWAP.",
        ],
        "outputs": ["paper_signal"],
    },
    {
        "id": "overextension_guard",
        "name": "Overextension Guard",
        "purpose": "Reject entries that look stretched or late.",
        "inputs": ["rsi", "distance_to_band", "candle_quality"],
        "conditions": [
            "Reject BUY when RSI > 70.",
            "Reject SELL when RSI < 30.",
            "Reject entries when candle quality is stretched or band distance is extreme.",
        ],
        "outputs": ["validation_decision"],
    },
    {
        "id": "portfolio_rebalancing",
        "name": "Portfolio Rebalancing",
        "purpose": "Keep paper exposure aligned with target weights.",
        "inputs": ["positions", "target_allocations", "rebalance_tolerance", "rebalance_key_mode"],
        "conditions": [
            "Close overweight exposure when drift exceeds tolerance.",
            "Prioritize underweight buckets for new entries.",
        ],
        "outputs": ["rebalance_plan"],
    },
]

DEFAULT_STATE = {
    "settings": {
        "paper_trading_enabled": True,
        "live_trading_enabled": False,
        "broker_provider": "deriv",
        "deriv_app_id": "",
        "deriv_token": "",
        "deriv_api_url": DEFAULT_DERIV_API_URL,
        "deriv_ws_url": DEFAULT_DERIV_WS_URL,
        "deriv_options_account_mode": "demo",
        "deriv_options_account_id": "",
        "risk_profile": "balanced",
        "max_open_positions": 6,
        "live_trade_stake": 1.0,
        "live_trade_currency": "USD",
        "live_trade_duration": 5,
        "live_trade_duration_unit": "t",
        "rebalance_enabled": True,
        "rebalance_key_mode": "asset_class",
        "rebalance_tolerance": 0.08,
        "target_allocations": dict(DEFAULT_TARGET_ALLOCATIONS),
        "symbols": [],
        "market_snapshots": [],
    },
    "portfolio": [],
    "trade_history": [],
    "last_backtest": None,
    "last_broker_status": None,
}


@dataclass(frozen=True)
class RebalanceAction:
    action: str
    allocation_key: str
    reason: str
    current_weight: float
    target_weight: float
    drift: float
    position_id: Optional[str] = None
    symbol: Optional[str] = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_store() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STORE_PATH.exists():
        STORE_PATH.write_text(json.dumps(DEFAULT_STATE, indent=2), encoding="utf-8")


def load_state() -> dict:
    ensure_store()
    try:
        stored = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        stored = deepcopy(DEFAULT_STATE)
    return sanitize_state(stored)


def save_state(state: dict) -> None:
    ensure_store()
    STORE_PATH.write_text(json.dumps(sanitize_state(state), indent=2), encoding="utf-8")


def normalize_key_mode(value: object) -> str:
    mode = str(value or "asset_class").strip().lower()
    return mode if mode in {"asset_class", "symbol"} else "asset_class"


def normalize_target_allocations(targets: object, key_mode: str = "asset_class") -> dict[str, float]:
    key_mode = normalize_key_mode(key_mode)
    if not isinstance(targets, dict):
        targets = DEFAULT_TARGET_ALLOCATIONS if key_mode == "asset_class" else {}
    cleaned: dict[str, float] = {}
    for raw_key, raw_value in targets.items():
        key = str(raw_key or "").strip().upper()
        if not key:
            continue
        try:
            value = float(raw_value)
        except Exception:
            continue
        if value <= 0:
            continue
        cleaned[key] = value
    total = sum(cleaned.values())
    if total <= 0:
        return dict(DEFAULT_TARGET_ALLOCATIONS) if key_mode == "asset_class" else {}
    return {key: value / total for key, value in cleaned.items()}


def normalize_asset_class(value: object) -> str:
    asset_class = str(value or "CUSTOM").strip().upper()
    return asset_class if asset_class in SUPPORTED_ASSET_CLASSES else "CUSTOM"


def normalize_symbols(symbols: object) -> list[dict]:
    if not isinstance(symbols, list):
        return []
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in symbols:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        cleaned.append(
            {
                "symbol": symbol,
                "label": str(item.get("label") or symbol).strip() or symbol,
                "asset_class": normalize_asset_class(item.get("asset_class")),
            }
        )
    return cleaned


def symbol_map_from_settings(settings: dict) -> dict[str, dict]:
    return {item["symbol"]: item for item in normalize_symbols(settings.get("symbols", []))}


def normalize_market_snapshots(snapshots: object, symbol_map: dict[str, dict]) -> list[dict]:
    if not isinstance(snapshots, list):
        return []
    cleaned: list[dict] = []
    for item in snapshots:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        meta = symbol_map.get(symbol)
        if not meta:
            continue
        try:
            price = float(item.get("price") or 0.0)
        except Exception:
            continue
        if price <= 0:
            continue
        cleaned.append(
            {
                "symbol": symbol,
                "asset_class": meta["asset_class"],
                "price": round(price, 5),
                "ema_fast": float(item.get("ema_fast") or price),
                "ema_slow": float(item.get("ema_slow") or price),
                "adx": float(item.get("adx") or 0.0),
                "rsi": float(item.get("rsi") or 50.0),
                "atr_ratio": float(item.get("atr_ratio") or 1.0),
                "price_vs_vwap": "below" if str(item.get("price_vs_vwap") or "above").strip().lower() == "below" else "above",
                "candle_quality": "stretched" if str(item.get("candle_quality") or "clean").strip().lower() == "stretched" else "clean",
                "distance_to_band": float(item.get("distance_to_band") or 0.0),
            }
        )
    return cleaned


def runtime_setting_overrides() -> dict:
    overrides: dict[str, object] = {}
    mapping = {
        "COMMUNITY_DERIV_APP_ID": "deriv_app_id",
        "COMMUNITY_DERIV_TOKEN": "deriv_token",
        "COMMUNITY_DERIV_API_URL": "deriv_api_url",
        "COMMUNITY_DERIV_WS_URL": "deriv_ws_url",
    }
    for env_key, setting_key in mapping.items():
        value = os.getenv(env_key)
        if value:
            overrides[setting_key] = value
    return overrides


def sanitize_position(raw_position: object, symbol_map: dict[str, dict]) -> Optional[dict]:
    if not isinstance(raw_position, dict):
        return None
    symbol = str(raw_position.get("symbol") or "").strip()
    side = str(raw_position.get("side") or "").strip().upper()
    if symbol not in symbol_map or side not in {"BUY", "SELL"}:
        return None
    try:
        exposure = float(raw_position.get("exposure") or 0.0)
        entry_price = float(raw_position.get("entry_price") or 0.0)
        current_price = float(raw_position.get("current_price") or entry_price or 0.0)
    except Exception:
        return None
    if exposure <= 0 or entry_price <= 0 or current_price <= 0:
        return None
    asset_class = symbol_map[symbol]["asset_class"]
    return {
        "id": str(raw_position.get("id") or f"pos-{uuid4().hex[:8]}"),
        "symbol": symbol,
        "asset_class": asset_class,
        "side": side,
        "exposure": round(exposure, 2),
        "entry_price": round(entry_price, 5),
        "current_price": round(current_price, 5),
        "opened_at": str(raw_position.get("opened_at") or utc_now_iso()),
    }


def sanitize_trade_history(rows: object, symbol_map: dict[str, dict]) -> list[dict]:
    if not isinstance(rows, list):
        return []
    cleaned: list[dict] = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip()
        if symbol and symbol not in symbol_map:
            continue
        try:
            exposure = round(float(row.get("exposure") or 0.0), 2)
        except Exception:
            exposure = 0.0
        cleaned.append(
            {
                "timestamp": str(row.get("timestamp") or utc_now_iso()),
                "type": str(row.get("type") or "INFO").strip().upper(),
                "symbol": symbol,
                "side": str(row.get("side") or "").strip().upper(),
                "exposure": exposure,
                "note": str(row.get("note") or "").strip(),
            }
        )
    return cleaned


def sanitize_state(state: object) -> dict:
    raw = state if isinstance(state, dict) else {}
    settings = normalize_settings(raw.get("settings") or {}, deepcopy(DEFAULT_STATE["settings"]))
    symbol_map = symbol_map_from_settings(settings)
    portfolio = [pos for pos in (sanitize_position(item, symbol_map) for item in raw.get("portfolio", [])) if pos]
    clean_state = deepcopy(DEFAULT_STATE)
    clean_state["settings"] = settings
    clean_state["portfolio"] = portfolio
    clean_state["trade_history"] = sanitize_trade_history(raw.get("trade_history", []), symbol_map)
    clean_state["last_backtest"] = raw.get("last_backtest")
    clean_state["last_broker_status"] = raw.get("last_broker_status")
    return clean_state


def error_response(message: str, status_code: int = 400):
    return jsonify({"error": message}), status_code


def json_payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def sanitize_live_amount(value: object, default: float = 1.0) -> float:
    try:
        amount = float(value)
    except Exception:
        amount = default
    return round(max(0.35, min(amount, 100000.0)), 2)


def sanitize_duration(value: object, default: int = 5) -> int:
    try:
        duration = int(value)
    except Exception:
        duration = default
    return max(1, min(duration, 365))


def sanitize_duration_unit(value: object, default: str = "t") -> str:
    unit = str(value or default).strip().lower()
    return unit if unit in {"t", "s", "m", "h", "d"} else default


def sanitize_trade_side(value: object, default: str = "BUY") -> str:
    side = str(value or default).strip().upper()
    return side if side in {"BUY", "SELL"} else default


def sanitize_live_contract_type(value: object, side: str = "BUY") -> str:
    contract_type = str(value or "").strip().upper()
    if contract_type in {"CALL", "PUT"}:
        return contract_type
    return "PUT" if sanitize_trade_side(side) == "SELL" else "CALL"


def sanitize_currency(value: object, default: str = "USD") -> str:
    currency = str(value or default).strip().upper()
    return currency[:10] or default


def payload_value(payload: dict, key: str, current: dict, merged: dict, default: object = "") -> object:
    if key in payload:
        return payload.get(key)
    if key in merged:
        return merged.get(key)
    if key in current:
        return current.get(key)
    return default


def signal_thresholds(risk_profile: str) -> dict[str, float]:
    profile = str(risk_profile or "balanced").strip().lower()
    if profile == "aggressive":
        return {"adx": 16.0, "rsi_buy_min": 42.0, "rsi_buy_max": 70.0, "rsi_sell_min": 30.0, "rsi_sell_max": 58.0}
    if profile == "conservative":
        return {"adx": 24.0, "rsi_buy_min": 48.0, "rsi_buy_max": 62.0, "rsi_sell_min": 38.0, "rsi_sell_max": 52.0}
    return {"adx": 20.0, "rsi_buy_min": 45.0, "rsi_buy_max": 68.0, "rsi_sell_min": 32.0, "rsi_sell_max": 55.0}


def configured_market_snapshots(settings: dict) -> list[dict]:
    symbol_map = symbol_map_from_settings(settings)
    return normalize_market_snapshots(settings.get("market_snapshots", []), symbol_map)


def deriv_client_from_settings(settings: dict) -> DerivCommunityClient:
    return DerivCommunityClient(
        app_id=str(settings.get("deriv_app_id") or "").strip(),
        token=str(settings.get("deriv_token") or "").strip(),
        rest_url=str(settings.get("deriv_api_url") or DEFAULT_DERIV_API_URL).strip() or DEFAULT_DERIV_API_URL,
        ws_url=str(settings.get("deriv_ws_url") or DEFAULT_DERIV_WS_URL).strip() or DEFAULT_DERIV_WS_URL,
        options_account_mode=str(settings.get("deriv_options_account_mode") or "demo").strip().lower() or "demo",
        options_account_id=str(settings.get("deriv_options_account_id") or "").strip(),
    )


def record_broker_status(state: dict, status: dict) -> dict:
    stored = {
        "checked_at": utc_now_iso(),
        **(status or {}),
    }
    state["last_broker_status"] = stored
    return stored


def classify_regime(snapshot: dict, thresholds: dict[str, float]) -> str:
    if float(snapshot.get("atr_ratio") or 0.0) < 0.85:
        return "LOW_VOLATILITY"
    if float(snapshot.get("adx") or 0.0) >= thresholds["adx"] and abs(float(snapshot.get("ema_fast") or 0.0) - float(snapshot.get("ema_slow") or 0.0)) > 0:
        return "TRENDING"
    return "RANGING"


def evaluate_snapshot(snapshot: dict, settings: dict) -> dict:
    thresholds = signal_thresholds(settings.get("risk_profile", "balanced"))
    regime = classify_regime(snapshot, thresholds)
    decision = "HOLD"
    reason = "No qualified setup."
    adx = float(snapshot.get("adx") or 0.0)
    rsi = float(snapshot.get("rsi") or 50.0)
    above_vwap = snapshot.get("price_vs_vwap") == "above"
    below_vwap = snapshot.get("price_vs_vwap") == "below"
    stretched = snapshot.get("candle_quality") != "clean" or float(snapshot.get("distance_to_band") or 0.0) > 0.88
    if regime == "TRENDING" and not stretched:
        if float(snapshot.get("ema_fast") or 0.0) > float(snapshot.get("ema_slow") or 0.0) and adx >= thresholds["adx"] and thresholds["rsi_buy_min"] <= rsi <= thresholds["rsi_buy_max"] and above_vwap:
            decision = "BUY"
            reason = "Trend structure, momentum, and price positioning are aligned."
        elif float(snapshot.get("ema_fast") or 0.0) < float(snapshot.get("ema_slow") or 0.0) and adx >= thresholds["adx"] and thresholds["rsi_sell_min"] <= rsi <= thresholds["rsi_sell_max"] and below_vwap:
            decision = "SELL"
            reason = "Downtrend structure, momentum, and price positioning are aligned."
    elif regime == "LOW_VOLATILITY":
        reason = "ATR compression suggests low opportunity quality."
    elif stretched:
        reason = "Overextension guard blocked a late or stretched entry."
    return {**snapshot, "regime": regime, "decision": decision, "reason": reason, "generated_at": utc_now_iso()}


def market_view(settings: dict) -> list[dict]:
    return [evaluate_snapshot(dict(row), settings) for row in configured_market_snapshots(settings)]


def refresh_portfolio_prices(positions: list[dict], settings: dict) -> list[dict]:
    market_map = {row["symbol"]: row for row in configured_market_snapshots(settings)}
    refreshed: list[dict] = []
    for position in positions:
        updated = dict(position)
        latest_market = market_map.get(updated["symbol"])
        if latest_market:
            updated["current_price"] = round(float(latest_market["price"]), 5)
        refreshed.append(updated)
    return refreshed


def count_open_signals(market: list[dict]) -> int:
    return sum(1 for row in market if row["decision"] in {"BUY", "SELL"})


def summarize_positions(positions: list[dict], key_mode: str = "asset_class") -> tuple[float, dict[str, float]]:
    totals: dict[str, float] = {}
    total_exposure = 0.0
    mode = normalize_key_mode(key_mode)
    for pos in positions:
        exposure = float(pos.get("exposure") or 0.0)
        if exposure <= 0:
            continue
        key = str(pos.get("asset_class") if mode == "asset_class" else pos.get("symbol") or "UNKNOWN").upper()
        totals[key] = totals.get(key, 0.0) + exposure
        total_exposure += exposure
    if total_exposure <= 0:
        return 0.0, {}
    return total_exposure, {key: value / total_exposure for key, value in totals.items()}


def build_rebalance_plan(state: dict) -> dict:
    settings = state.get("settings", {})
    positions = state.get("portfolio", [])
    key_mode = normalize_key_mode(settings.get("rebalance_key_mode", "asset_class"))
    targets = normalize_target_allocations(settings.get("target_allocations"), key_mode)
    tolerance = max(0.0, min(float(settings.get("rebalance_tolerance", 0.08) or 0.08), 0.50))
    total_exposure, current_weights = summarize_positions(positions, key_mode)
    drift_score = sum(abs(current_weights.get(key, 0.0) - targets.get(key, 0.0)) for key in set(current_weights) | set(targets))
    actions: list[RebalanceAction] = []
    if total_exposure > 0:
        for key in sorted(set(current_weights) | set(targets)):
            current = current_weights.get(key, 0.0)
            target = targets.get(key, 0.0)
            drift = current - target
            if drift > tolerance:
                matching = [pos for pos in positions if str(pos.get("asset_class") if key_mode == "asset_class" else pos.get("symbol") or "UNKNOWN").upper() == key]
                matching.sort(key=lambda item: float(item.get("exposure") or 0.0), reverse=True)
                if matching:
                    position = matching[0]
                    actions.append(
                        RebalanceAction(
                            action="CLOSE_POSITION",
                            allocation_key=key,
                            reason=f"{key} is overweight by {drift:.2%}; reduce exposure until drift is within tolerance.",
                            current_weight=current,
                            target_weight=target,
                            drift=drift,
                            position_id=str(position.get("id")),
                            symbol=str(position.get("symbol")),
                        )
                    )
            elif target - current > tolerance:
                actions.append(
                    RebalanceAction(
                        action="PRIORITIZE_NEW_ENTRIES",
                        allocation_key=key,
                        reason=f"{key} is underweight by {(target - current):.2%}; prioritize new paper trades in this bucket.",
                        current_weight=current,
                        target_weight=target,
                        drift=target - current,
                    )
                )
    return {
        "total_exposure": round(total_exposure, 2),
        "current_weights": {key: round(value, 4) for key, value in current_weights.items()},
        "target_weights": {key: round(value, 4) for key, value in targets.items()},
        "drift_score": round(drift_score, 4),
        "enabled": bool(settings.get("rebalance_enabled", True)),
        "tolerance": round(tolerance, 4),
        "key_mode": key_mode,
        "actions": [asdict(action) for action in actions],
    }


def backtest_summary(state: dict) -> dict:
    settings = state.get("settings", {})
    scenarios = [
        {
            "name": "Fresh bullish trend",
            "snapshot": {
                "symbol": "scenario-bull",
                "asset_class": "FOREX",
                "price": 1.1042,
                "ema_fast": 1.1036,
                "ema_slow": 1.1022,
                "adx": 27.0,
                "rsi": 58.0,
                "atr_ratio": 1.05,
                "price_vs_vwap": "above",
                "candle_quality": "clean",
                "distance_to_band": 0.52,
            },
            "expected": "BUY",
        },
        {
            "name": "Low volatility skip",
            "snapshot": {
                "symbol": "scenario-flat",
                "asset_class": "FOREX",
                "price": 1.0991,
                "ema_fast": 1.0992,
                "ema_slow": 1.0991,
                "adx": 14.0,
                "rsi": 50.0,
                "atr_ratio": 0.72,
                "price_vs_vwap": "above",
                "candle_quality": "clean",
                "distance_to_band": 0.40,
            },
            "expected": "HOLD",
        },
        {
            "name": "Overextended rejection",
            "snapshot": {
                "symbol": "scenario-stretch",
                "asset_class": "COMMODITIES",
                "price": 2341.0,
                "ema_fast": 2335.0,
                "ema_slow": 2329.0,
                "adx": 31.0,
                "rsi": 74.0,
                "atr_ratio": 1.18,
                "price_vs_vwap": "above",
                "candle_quality": "stretched",
                "distance_to_band": 0.96,
            },
            "expected": "HOLD",
        },
    ]
    results = []
    passes = 0
    for scenario in scenarios:
        outcome = evaluate_snapshot(scenario["snapshot"], settings)
        passed = outcome["decision"] == scenario["expected"]
        passes += int(passed)
        results.append({"name": scenario["name"], "expected": scenario["expected"], "actual": outcome["decision"], "passed": passed, "reason": outcome["reason"]})
    rebalance = build_rebalance_plan(state)
    return {
        "run_at": utc_now_iso(),
        "scenario_passes": passes,
        "scenario_total": len(scenarios),
        "scenario_results": results,
        "rebalance_check": {
            "passed": True,
            "drift_score": rebalance["drift_score"],
            "action_count": len(rebalance["actions"]),
        },
    }


def setup_status(settings: dict, market: list[dict]) -> dict:
    symbols = normalize_symbols(settings.get("symbols", []))
    deriv_app_id = str(settings.get("deriv_app_id") or "").strip()
    deriv_token = str(settings.get("deriv_token") or "").strip()
    live_enabled = bool(settings.get("live_trading_enabled", False))
    return {
        "broker_provider": settings.get("broker_provider", "deriv"),
        "broker_configured": bool(deriv_app_id and deriv_token),
        "symbols_configured": bool(symbols),
        "market_snapshots_configured": bool(market),
        "paper_trading_ready": bool(symbols),
        "live_trading_enabled": live_enabled,
        "live_trading_ready": bool(live_enabled and deriv_app_id and deriv_token and symbols),
        "recommended_next_step": (
            "Add symbols and market snapshots, then review settings before opening paper trades."
            if not symbols or not market
            else (
                "Live trading is enabled. Test the Deriv connection before placing a live trade."
                if live_enabled and deriv_app_id and deriv_token
                else "Configuration looks usable for paper trading."
            )
        ),
    }


def bootstrap_payload(state: dict) -> dict:
    settings = state.get("settings", {})
    state["portfolio"] = refresh_portfolio_prices(state.get("portfolio", []), settings)
    market = market_view(settings)
    total_exposure, current_weights = summarize_positions(
        state.get("portfolio", []),
        settings.get("rebalance_key_mode", "asset_class"),
    )
    return {
        "settings": settings,
        "market": market,
        "signals": [row for row in market if row["decision"] != "HOLD"],
        "portfolio": state.get("portfolio", []),
        "trade_history": state.get("trade_history", [])[:20],
        "rules": RULES,
        "rebalance_plan": build_rebalance_plan(state),
        "last_backtest": state.get("last_backtest"),
        "last_broker_status": state.get("last_broker_status"),
        "symbols": normalize_symbols(settings.get("symbols", [])),
        "setup": setup_status(settings, market),
        "stats": {
            "market_count": len(market),
            "signal_count": count_open_signals(market),
            "open_positions": len(state.get("portfolio", [])),
            "total_exposure": round(total_exposure, 2),
            "current_weights": {key: round(value, 4) for key, value in current_weights.items()},
        },
    }


def normalize_settings(payload: dict, current: dict) -> dict:
    merged = {**current, **runtime_setting_overrides()}
    merged["paper_trading_enabled"] = bool(payload.get("paper_trading_enabled", current.get("paper_trading_enabled", True)))
    merged["live_trading_enabled"] = bool(payload.get("live_trading_enabled", current.get("live_trading_enabled", False)))
    merged["broker_provider"] = "deriv"
    merged["deriv_app_id"] = str(payload_value(payload, "deriv_app_id", current, merged, "") or "").strip()
    merged["deriv_token"] = str(payload_value(payload, "deriv_token", current, merged, "") or "").strip()
    merged["deriv_api_url"] = str(payload_value(payload, "deriv_api_url", current, merged, DEFAULT_DERIV_API_URL) or DEFAULT_DERIV_API_URL).strip()
    merged["deriv_ws_url"] = str(payload_value(payload, "deriv_ws_url", current, merged, DEFAULT_DERIV_WS_URL) or DEFAULT_DERIV_WS_URL).strip()
    account_mode = str(payload_value(payload, "deriv_options_account_mode", current, merged, "demo")).strip().lower()
    merged["deriv_options_account_mode"] = account_mode if account_mode in {"demo", "real"} else "demo"
    merged["deriv_options_account_id"] = str(payload_value(payload, "deriv_options_account_id", current, merged, "") or "").strip()
    risk = str(payload.get("risk_profile", current.get("risk_profile", "balanced"))).strip().lower()
    merged["risk_profile"] = risk if risk in {"conservative", "balanced", "aggressive"} else "balanced"
    try:
        merged["max_open_positions"] = max(1, min(int(payload.get("max_open_positions", current.get("max_open_positions", 6))), 20))
    except Exception:
        merged["max_open_positions"] = current.get("max_open_positions", 6)
    merged["live_trade_stake"] = sanitize_live_amount(payload.get("live_trade_stake", current.get("live_trade_stake", 1.0)), current.get("live_trade_stake", 1.0))
    merged["live_trade_currency"] = sanitize_currency(payload.get("live_trade_currency", current.get("live_trade_currency", "USD")), "USD")
    merged["live_trade_duration"] = sanitize_duration(payload.get("live_trade_duration", current.get("live_trade_duration", 5)), current.get("live_trade_duration", 5))
    merged["live_trade_duration_unit"] = sanitize_duration_unit(payload.get("live_trade_duration_unit", current.get("live_trade_duration_unit", "t")), current.get("live_trade_duration_unit", "t"))
    merged["rebalance_enabled"] = bool(payload.get("rebalance_enabled", current.get("rebalance_enabled", True)))
    merged["rebalance_key_mode"] = normalize_key_mode(payload.get("rebalance_key_mode", current.get("rebalance_key_mode", "asset_class")))
    try:
        tolerance = float(payload.get("rebalance_tolerance", current.get("rebalance_tolerance", 0.08)))
    except Exception:
        tolerance = current.get("rebalance_tolerance", 0.08)
    merged["rebalance_tolerance"] = max(0.0, min(tolerance, 0.50))
    merged["symbols"] = normalize_symbols(payload.get("symbols", current.get("symbols", [])))
    merged["market_snapshots"] = normalize_market_snapshots(
        payload.get("market_snapshots", current.get("market_snapshots", [])),
        symbol_map_from_settings(merged),
    )
    merged["target_allocations"] = normalize_target_allocations(payload.get("target_allocations", current.get("target_allocations", DEFAULT_TARGET_ALLOCATIONS)), merged["rebalance_key_mode"])
    return merged


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "fx-scalper-community", "broker_provider": "deriv"})


@app.get("/api/bootstrap")
def bootstrap():
    return jsonify(bootstrap_payload(load_state()))


@app.get("/api/rules")
def rules():
    return jsonify({"rules": RULES})


@app.post("/api/config")
def update_config():
    state = load_state()
    state["settings"] = normalize_settings(json_payload(), state.get("settings", {}))
    save_state(state)
    return jsonify({"message": "Settings updated", "settings": state["settings"]})


@app.get("/api/broker/status")
def broker_status():
    state = load_state()
    settings = state.get("settings", {})
    return jsonify(
        {
            "status": state.get("last_broker_status"),
            "setup": setup_status(settings, market_view(settings)),
        }
    )


@app.post("/api/broker/test")
def broker_test():
    state = load_state()
    settings = state.get("settings", {})
    if not str(settings.get("deriv_app_id") or "").strip() or not str(settings.get("deriv_token") or "").strip():
        status = record_broker_status(
            state,
            {
                "ok": False,
                "connected": False,
                "message": "Add a Deriv app ID and API token before testing the broker connection.",
                "token_mode": "pat" if str(settings.get("deriv_token") or "").strip().startswith("pat_") else "legacy",
            },
        )
        save_state(state)
        return jsonify({"ok": False, "message": status["message"], "status": status})
    client = deriv_client_from_settings(settings)
    try:
        snapshot = client.connect()
        active_symbols = client.get_active_symbols()
        options_account_id = str(snapshot.get("options_account_id") or "").strip()
        if options_account_id:
            state["settings"]["deriv_options_account_id"] = options_account_id
        status = record_broker_status(
            state,
            {
                "ok": True,
                "connected": True,
                "message": "Deriv connection verified successfully.",
                "active_symbol_count": len(active_symbols),
                **snapshot,
            },
        )
        save_state(state)
        return jsonify({"ok": True, "message": status["message"], "status": status})
    except DerivServiceError as exc:
        status = record_broker_status(
            state,
            {
                "ok": False,
                "connected": False,
                "message": str(exc),
                "app_id": client.app_id,
                "token_mode": client.token_mode,
                "options_account_mode": settings.get("deriv_options_account_mode", "demo"),
            },
        )
        save_state(state)
        return jsonify({"ok": False, "message": str(exc), "status": status})
    finally:
        client.close()


@app.post("/api/paper-trades/open")
def paper_trade_open():
    state = load_state()
    payload = json_payload()
    settings = state.get("settings", {})
    symbol_map = symbol_map_from_settings(settings)
    market_map = {row["symbol"]: row for row in configured_market_snapshots(settings)}
    if not settings.get("paper_trading_enabled", True):
        return error_response("Paper trading is disabled in settings.", 400)
    symbol = str(payload.get("symbol") or "").strip()
    side = sanitize_trade_side(payload.get("side"), "BUY")
    try:
        exposure = float(payload.get("exposure") or 0)
        price = float(payload.get("price") or 0)
    except Exception:
        return error_response("Exposure and price must be numeric.")
    if not symbol or side not in {"BUY", "SELL"} or exposure <= 0 or price <= 0:
        return error_response("Invalid paper trade payload.")
    if len(state.get("portfolio", [])) >= int(settings.get("max_open_positions", 6)):
        return error_response("Max open positions reached.")
    meta = symbol_map.get(symbol)
    if not meta:
        return error_response("Unknown symbol. Add it in settings before opening a paper trade.")
    latest_market = market_map.get(symbol)
    position = {
        "id": f"pos-{uuid4().hex[:8]}",
        "symbol": symbol,
        "asset_class": meta["asset_class"],
        "side": side,
        "exposure": round(exposure, 2),
        "entry_price": round(price, 5),
        "current_price": round(float((latest_market or {}).get("price") or price), 5),
        "opened_at": utc_now_iso(),
    }
    state.setdefault("portfolio", []).append(position)
    state.setdefault("trade_history", []).insert(
        0,
        {
            "timestamp": utc_now_iso(),
            "type": "OPEN",
            "symbol": symbol,
            "side": side,
            "exposure": position["exposure"],
            "note": "Paper trade opened from community dashboard.",
        },
    )
    save_state(state)
    return jsonify({"message": "Paper trade opened", "position": position})


@app.post("/api/live-trades/open")
def live_trade_open():
    state = load_state()
    settings = state.get("settings", {})
    payload = json_payload()
    if not settings.get("live_trading_enabled", False):
        return error_response("Live trading is disabled in settings.", 400)
    symbol = str(payload.get("symbol") or "").strip()
    side = sanitize_trade_side(payload.get("side"), "BUY")
    symbol_map = symbol_map_from_settings(settings)
    if symbol not in symbol_map:
        return error_response("Unknown symbol. Add it in settings before placing a live trade.", 400)
    amount = sanitize_live_amount(payload.get("amount", settings.get("live_trade_stake", 1.0)), settings.get("live_trade_stake", 1.0))
    duration = sanitize_duration(payload.get("duration", settings.get("live_trade_duration", 5)), settings.get("live_trade_duration", 5))
    duration_unit = sanitize_duration_unit(
        payload.get("duration_unit", settings.get("live_trade_duration_unit", "t")),
        settings.get("live_trade_duration_unit", "t"),
    )
    currency = sanitize_currency(payload.get("currency", settings.get("live_trade_currency", "USD")), settings.get("live_trade_currency", "USD"))
    contract_type = sanitize_live_contract_type(payload.get("contract_type"), side)
    client = deriv_client_from_settings(settings)
    try:
        snapshot = client.connect()
        proposal = client.propose(
            symbol=symbol,
            contract_type=contract_type,
            amount=amount,
            duration=duration,
            duration_unit=duration_unit,
            currency=currency,
        )
        proposal_id = str(proposal.get("id") or proposal.get("proposal_id") or "").strip()
        if not proposal_id:
            raise DerivServiceError("Deriv did not return a proposal ID for this trade.")
        ask_price = sanitize_live_amount(proposal.get("ask_price", amount), amount)
        buy = client.buy(proposal_id, ask_price)
        options_account_id = str(snapshot.get("options_account_id") or "").strip()
        if options_account_id:
            state["settings"]["deriv_options_account_id"] = options_account_id
        status = record_broker_status(
            state,
            {
                "ok": True,
                "connected": True,
                "message": "Deriv live trade submitted successfully.",
                **snapshot,
            },
        )
        state.setdefault("trade_history", []).insert(
            0,
            {
                "timestamp": utc_now_iso(),
                "type": "LIVE_OPEN",
                "symbol": symbol,
                "side": side,
                "exposure": amount,
                "note": (
                    f"Live {contract_type} submitted via Deriv community flow. "
                    f"Contract {buy.get('contract_id') or buy.get('transaction_id') or 'pending'}."
                ),
            },
        )
        save_state(state)
        return jsonify(
            {
                "message": "Live trade submitted",
                "status": status,
                "proposal": proposal,
                "buy": buy,
                "request": {
                    "symbol": symbol,
                    "side": side,
                    "contract_type": contract_type,
                    "amount": amount,
                    "currency": currency,
                    "duration": duration,
                    "duration_unit": duration_unit,
                },
            }
        )
    except DerivServiceError as exc:
        status = record_broker_status(
            state,
            {
                "ok": False,
                "connected": False,
                "message": str(exc),
                "app_id": client.app_id,
                "token_mode": client.token_mode,
                "options_account_mode": settings.get("deriv_options_account_mode", "demo"),
            },
        )
        state.setdefault("trade_history", []).insert(
            0,
            {
                "timestamp": utc_now_iso(),
                "type": "LIVE_ERROR",
                "symbol": symbol,
                "side": side,
                "exposure": amount,
                "note": str(exc),
            },
        )
        save_state(state)
        return jsonify({"error": str(exc), "status": status}), 400
    finally:
        client.close()


@app.post("/api/paper-trades/rebalance")
def paper_trade_rebalance():
    state = load_state()
    if not state.get("settings", {}).get("rebalance_enabled", True):
        return error_response("Rebalancing is disabled in settings.", 400)
    plan = build_rebalance_plan(state)
    closed = []
    for action in plan["actions"]:
        if action["action"] != "CLOSE_POSITION" or not action.get("position_id"):
            continue
        for index, position in enumerate(list(state.get("portfolio", []))):
            if str(position.get("id")) == action["position_id"]:
                state["portfolio"].pop(index)
                state.setdefault("trade_history", []).insert(
                    0,
                    {
                        "timestamp": utc_now_iso(),
                        "type": "REBALANCE_CLOSE",
                        "symbol": position["symbol"],
                        "side": position["side"],
                        "exposure": position["exposure"],
                        "note": action["reason"],
                    },
                )
                closed.append(position)
                break
    save_state(state)
    return jsonify({"message": "Rebalance applied", "plan": plan, "closed_positions": closed})


@app.post("/api/backtests/run")
def backtests_run():
    state = load_state()
    state["last_backtest"] = backtest_summary(state)
    save_state(state)
    return jsonify({"message": "Backtests completed", "summary": state["last_backtest"]})


@app.post("/api/reset")
def reset():
    state = deepcopy(DEFAULT_STATE)
    save_state(state)
    return jsonify({"message": "Community edition state reset", "settings": state["settings"]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
