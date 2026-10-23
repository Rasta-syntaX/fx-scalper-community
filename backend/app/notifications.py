"""
Discord & Telegram trade notifications.

app.server calls notify_event() for every journal entry. Both channels can run
simultaneously; each is enabled by its environment variables and silently
skipped otherwise.
"""
import os
import re
import threading
from datetime import datetime, timezone

import requests


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_ts() -> str:
    return _utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')


def _discord_text(message: str) -> str:
    """Discord uses Markdown, not HTML."""
    return re.sub(r"</?b>", "**", message)


def channels_configured() -> bool:
    discord = bool(os.getenv('DISCORD_WEBHOOK_URL', '').strip())
    telegram = bool(os.getenv('TELEGRAM_BOT_TOKEN', '').strip() and os.getenv('TELEGRAM_CHAT_ID', '').strip())
    return discord or telegram


def send_discord(message: str, embed: dict = None) -> bool:
    """Send a plain message or embedded message to a Discord webhook."""
    url = os.getenv('DISCORD_WEBHOOK_URL', '').strip()
    if not url:
        return False
    payload = {"content": _discord_text(message)[:2000]}
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
        "timestamp": _utcnow().isoformat(),
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
        "timestamp": _utcnow().isoformat(),
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


EVENT_TITLES = {
    "OPEN": ("🟢", "Paper trade opened"),
    "LIVE_OPEN": ("🚀", "Live trade submitted"),
    "LIVE_ERROR": ("⚠️", "Live trade failed"),
    "REBALANCE_CLOSE": ("🔁", "Position closed by rebalance"),
    "AUTO_START": ("▶️", "Auto-trader started"),
    "AUTO_STOP": ("⏹️", "Auto-trader stopped"),
    "AUTO_OPEN": ("🤖", "Auto-trader opened a trade"),
    "AUTO_CLOSE": ("🤖", "Auto-trader closed a paper trade"),
    "LIVE_SETTLED": ("🏁", "Live contract settled"),
    "AUTO_HALT": ("🛑", "Auto-trader halted for the day"),
    "AUTO_ERROR": ("⚠️", "Auto-trader error"),
    "DAILY_SUMMARY": ("📅", "Auto-trader daily summary"),
}


def format_event(entry: dict) -> str:
    emoji, title = EVENT_TITLES.get(entry.get("type", ""), ("ℹ️", str(entry.get("type") or "Event")))
    lines = [f"{emoji} <b>{title}</b>"]
    if entry.get("symbol"):
        lines.append(f"Symbol: {entry['symbol']} {entry.get('side') or ''}".rstrip())
    try:
        lines.append(f"Amount: ${float(entry.get('exposure') or 0):.2f}")
    except (TypeError, ValueError):
        pass
    if entry.get("note"):
        lines.append(str(entry["note"]))
    lines.append(f"Time: {entry.get('timestamp') or _fmt_ts()}")
    return "\n".join(lines)


def _deliver(message: str) -> None:
    send_discord(message)
    send_telegram(message)


def notify_event(entry: dict, background: bool = True) -> bool:
    """Send a journal entry to every configured channel. Returns False if none is configured."""
    if entry.get("type") not in EVENT_TITLES or not channels_configured():
        return False
    message = format_event(entry)
    if background:
        threading.Thread(target=_deliver, args=(message,), daemon=True).start()
    else:
        _deliver(message)
    return True
