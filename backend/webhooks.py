"""
webhooks.py — Send trade notifications to Discord & Telegram.

Used by the trading engine to broadcast trade events. Both channels
can run simultaneously; configure via environment variables.
"""
import os
import json
import requests
from datetime import datetime


def _fmt_ts() -> str:
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')


def send_discord(message: str, embed: dict = None) -> bool:
    """Send a plain message or embedded message to a Discord webhook."""
    url = os.getenv('DISCORD_WEBHOOK_URL', '').strip()
    if not url:
        return False
    payload = {"content": message[:2000]}
    if embed:
        payload["embeds"] = [embed]
    try:
        r = requests.post(url, json=payload, timeout=5)
        return r.status_code in (200, 204)
    except Exception:
        return False


def send_telegram(message: str) -> bool:
    """Send a text message via a Telegram bot."""
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": message[:4096],
            "parse_mode": "HTML",
        }, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def notify_trade_opened(symbol: str, direction: str, stake: float, price: float, regime: str):
    """Broadcast a trade-open event to all configured channels."""
    emoji = "🟢" if direction == "CALL" else "🔴"
    msg = (
        f"{emoji} <b>Trade Opened</b>\n"
        f"Symbol: {symbol}\n"
        f"Direction: {direction}\n"
        f"Stake: ${stake:.2f}\n"
        f"Entry: {price:.5f}\n"
        f"Regime: {regime}\n"
        f"Time: {_fmt_ts()}"
    )
    discord_embed = {
        "title": f"{emoji} Trade Opened: {symbol}",
        "color": 0x00ff00 if direction == "CALL" else 0xff0000,
        "fields": [
            {"name": "Direction", "value": direction, "inline": True},
            {"name": "Stake", "value": f"${stake:.2f}", "inline": True},
            {"name": "Entry", "value": f"{price:.5f}", "inline": True},
            {"name": "Regime", "value": regime, "inline": True},
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }
    send_discord(msg, discord_embed)
    send_telegram(f"<b>{emoji} Trade Opened</b>\n{symbol} {direction} | ${stake:.2f} @ {price:.5f}")


def notify_trade_closed(symbol: str, direction: str, profit: float, reason: str):
    """Broadcast a trade-close event to all configured channels."""
    emoji = "💰" if profit >= 0 else "💸"
    msg = (
        f"{emoji} <b>Trade Closed</b>\n"
        f"Symbol: {symbol}\n"
        f"Direction: {direction}\n"
        f"P&L: ${profit:.2f}\n"
        f"Reason: {reason}\n"
        f"Time: {_fmt_ts()}"
    )
    color = 0x00ff00 if profit >= 0 else 0xff0000
    discord_embed = {
        "title": f"{emoji} Trade Closed: {symbol}",
        "color": color,
        "fields": [
            {"name": "Direction", "value": direction, "inline": True},
            {"name": "P&L", "value": f"${profit:+.2f}", "inline": True},
            {"name": "Reason", "value": reason, "inline": False},
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }
    send_discord(msg, discord_embed)
    send_telegram(
        f"<b>{emoji} Trade Closed</b>\n{symbol} {direction} | "
        f"{'✅' if profit >= 0 else '❌'} ${profit:+.2f} — {reason}"
    )


def notify_error(symbol: str, error: str):
    """Broadcast an error event to all configured channels."""
    msg = (
        f"⚠️ <b>Trade Error</b>\n"
        f"Symbol: {symbol}\n"
        f"Error: {error}\n"
        f"Time: {_fmt_ts()}"
    )
    send_discord(msg)
    send_telegram(msg)
