"""Trade events land in the CSV journal and are pushed to alert channels."""

import csv
import io

import pytest

from app import journal, notifications, server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMUNITY_LOG_DIR", str(tmp_path))
    for name in ("DISCORD_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    server.app.config.update(TESTING=True)
    with server.app.test_client() as test_client:
        test_client.post("/api/reset")
        test_client.post("/api/config", json={"symbols": [{"symbol": "frxEURUSD", "asset_class": "FOREX"}]})
        yield test_client


def open_paper_trade(client):
    symbol = "frxEURUSD"
    payload = {"symbol": symbol, "side": "BUY", "exposure": 250, "price": 1.1}
    response = client.post("/api/paper-trades/open", json=payload)
    assert response.status_code == 200, response.get_json()
    return symbol


def test_paper_trade_is_appended_to_csv(client):
    symbol = open_paper_trade(client)
    rows = list(csv.DictReader(journal.journal_path().open(encoding="utf-8")))
    assert [(r["type"], r["symbol"], r["side"], r["exposure"]) for r in rows] == [("OPEN", symbol, "BUY", "250.0")]


def test_export_endpoint_returns_csv(client):
    open_paper_trade(client)
    open_paper_trade(client)
    response = client.get("/api/journal.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
    assert [r["type"] for r in rows] == ["OPEN", "OPEN"]


def test_export_falls_back_to_history_without_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMUNITY_LOG_DIR", str(tmp_path / "empty"))
    text = journal.export_csv([{"type": "OPEN", "symbol": "B"}, {"type": "OPEN", "symbol": "A"}])
    assert [r["symbol"] for r in csv.DictReader(io.StringIO(text))] == ["A", "B"]


def test_trade_events_are_sent_to_configured_channels(client, monkeypatch):
    sent = []
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.invalid/webhook")
    monkeypatch.setattr(notifications, "send_discord", lambda message, embed=None: sent.append(message) or True)
    monkeypatch.setattr(notifications, "send_telegram", lambda message: True)
    monkeypatch.setattr(
        server, "notify_event", lambda entry: notifications.notify_event(entry, background=False)
    )
    symbol = open_paper_trade(client)
    assert len(sent) == 1
    assert "Paper trade opened" in sent[0] and symbol in sent[0] and "$250.00" in sent[0]


def test_no_channels_means_no_delivery(monkeypatch):
    for name in ("DISCORD_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    assert notifications.notify_event({"type": "OPEN", "symbol": "X"}, background=False) is False


def test_discord_receives_markdown_not_html(monkeypatch):
    captured = {}

    class Ok:
        status_code = 204

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.invalid/webhook")
    monkeypatch.setattr(notifications.requests, "post", lambda url, json, timeout: captured.update(json) or Ok())
    assert notifications.send_discord("<b>Trade</b>")
    assert captured["content"] == "**Trade**"
