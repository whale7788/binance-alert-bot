from datetime import datetime

import httpx

from binance_alert_bot.config import TelegramConfig
from binance_alert_bot.notify import TelegramNotifier


def make_response(status_code: int, json: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=json,
        request=httpx.Request("POST", "https://api.telegram.org/bottoken/sendMessage"),
    )


def test_telegram_notifier_returns_true_on_ok_response(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return make_response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(TelegramConfig(bot_token="token", chat_id="chat"))

    assert (
        notifier.send_breakout_summary(
            [{"symbol": "BTC-USDT-SWAP", "current_price": 101.0, "threshold": 100.0}],
            datetime(2026, 4, 11, 8, 30),
        )
        is True
    )


def test_telegram_notifier_returns_false_on_non_ok_response(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return make_response(200, json={"ok": False})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(TelegramConfig(bot_token="token", chat_id="chat"))

    assert (
        notifier.send_breakout_summary(
            [{"symbol": "BTC-USDT-SWAP", "current_price": 101.0, "threshold": 100.0}],
            datetime(2026, 4, 11, 8, 30),
        )
        is False
    )


def test_telegram_notifier_returns_false_on_http_error(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return make_response(500)

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(TelegramConfig(bot_token="token", chat_id="chat"))

    assert (
        notifier.send_breakout_summary(
            [{"symbol": "BTC-USDT-SWAP", "current_price": 101.0, "threshold": 100.0}],
            datetime(2026, 4, 11, 8, 30),
        )
        is False
    )
