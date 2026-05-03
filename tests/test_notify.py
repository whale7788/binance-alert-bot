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


def test_telegram_notifier_formats_negative_breakout_percent_without_double_sign(monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"]["text"])
        return make_response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(TelegramConfig(bot_token="token", chat_id="chat"))

    assert (
        notifier.send_breakout_summary(
            [
                {
                    "symbol": "AAVE-USDT-SWAP",
                    "current_price": 94.11,
                    "threshold": 97.98,
                    "status": "今日已突破",
                }
            ],
            datetime(2026, 4, 11, 8, 30),
        )
        is True
    )

    assert len(calls) == 1
    assert "(-3.95%)" in calls[0]
    assert "+-3.95%" not in calls[0]


def test_telegram_notifier_adds_breakout_ordinal_for_all_breakout_lines(monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"]["text"])
        return make_response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(TelegramConfig(bot_token="token", chat_id="chat"))

    assert (
        notifier.send_breakout_summary(
            [
                {
                    "symbol": "BTC-USDT-SWAP",
                    "current_price": 101.0,
                    "threshold": 100.0,
                    "status": "新突破",
                    "breakout_time": "2026-04-11T08:30:00+00:00",
                    "breakout_ordinal": 1,
                },
                {
                    "symbol": "ETH-USDT-SWAP",
                    "current_price": 202.0,
                    "threshold": 200.0,
                    "status": "新突破",
                    "breakout_time": "2026-04-11T08:31:00+00:00",
                    "breakout_ordinal": 2,
                },
                {
                    "symbol": "AAVE-USDT-SWAP",
                    "current_price": 94.11,
                    "threshold": 97.98,
                    "status": "今日已突破",
                    "breakout_time": "2026-04-11T08:32:00+00:00",
                    "breakout_ordinal": 3,
                },
            ],
            datetime(2026, 4, 11, 8, 30),
        )
        is True
    )

    assert len(calls) == 1
    assert "[第1个突破] BTC-USDT-SWAP" in calls[0]
    assert "[第2个突破] ETH-USDT-SWAP" in calls[0]
    assert "[第3个突破] AAVE-USDT-SWAP" in calls[0]


def test_telegram_notifier_routes_breakout_statuses_to_split_chats(monkeypatch) -> None:
    payloads: list[dict] = []

    def fake_post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return make_response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(
        TelegramConfig(
            bot_token="token",
            chat_id="fallback-chat",
            new_breakout_chat_id="new-chat",
            existing_breakout_chat_id="existing-chat",
        )
    )

    assert (
        notifier.send_breakout_summary(
            [
                {
                    "symbol": "BTC-USDT-SWAP",
                    "current_price": 101.0,
                    "threshold": 100.0,
                    "status": "新突破",
                },
                {
                    "symbol": "ETH-USDT-SWAP",
                    "current_price": 202.0,
                    "threshold": 200.0,
                    "status": "今日已突破",
                },
            ],
            datetime(2026, 4, 11, 8, 30),
        )
        is True
    )

    assert [payload["chat_id"] for payload in payloads] == ["new-chat", "existing-chat"]
    assert "BTC-USDT-SWAP" in payloads[0]["text"]
    assert "ETH-USDT-SWAP" not in payloads[0]["text"]
    assert "ETH-USDT-SWAP" in payloads[1]["text"]
    assert "BTC-USDT-SWAP" not in payloads[1]["text"]


def test_telegram_notifier_sends_five_minute_drop_alerts_to_drop_chat(monkeypatch) -> None:
    payloads: list[dict] = []

    def fake_post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return make_response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(
        TelegramConfig(
            bot_token="token",
            chat_id="fallback-chat",
            five_minute_drop_chat_id="drop-chat",
        )
    )

    assert (
        notifier.send_five_minute_drop_alerts(
            [
                {
                    "symbol": "BTCUSDT",
                    "open_price": 100.0,
                    "close_price": 94.5,
                }
            ],
            datetime(2026, 4, 11, 8, 30),
        )
        is True
    )

    assert [payload["chat_id"] for payload in payloads] == ["drop-chat"]
    assert "[5分钟急跌预警] 1个" in payloads[0]["text"]
    assert "BTCUSDT  100 -> 94.5  (-5.50%)" in payloads[0]["text"]


def test_telegram_notifier_keeps_display_order_but_uses_first_breakout_ordinal(monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"]["text"])
        return make_response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(TelegramConfig(bot_token="token", chat_id="chat"))

    assert (
        notifier.send_breakout_summary(
            [
                {
                    "symbol": "B-USDT-SWAP",
                    "current_price": 13.0,
                    "threshold": 10.0,
                    "status": "今日已突破",
                    "breakout_time": "2026-04-11T09:00:00+00:00",
                    "breakout_ordinal": 2,
                },
                {
                    "symbol": "A-USDT-SWAP",
                    "current_price": 12.0,
                    "threshold": 10.0,
                    "status": "今日已突破",
                    "breakout_time": "2026-04-11T08:00:00+00:00",
                    "breakout_ordinal": 1,
                },
            ],
            datetime(2026, 4, 11, 10, 0),
        )
        is True
    )

    assert len(calls) == 1
    assert calls[0].index("B-USDT-SWAP") < calls[0].index("A-USDT-SWAP")
    assert "[第1个突破] A-USDT-SWAP" in calls[0]
    assert "[第2个突破] B-USDT-SWAP" in calls[0]


def test_telegram_notifier_splits_large_breakout_summary(monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"]["text"])
        return make_response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(TelegramConfig(bot_token="token", chat_id="chat"))
    notifier.BREAKOUT_SUMMARY_MAX_CHARS = 120

    breakouts = [
        {
            "symbol": f"LONG-SYMBOL-{index:02d}-USDT-SWAP",
            "current_price": 100.0 + index,
            "threshold": 90.0,
            "status": "今日已突破",
            "breakout_ordinal": index + 1,
        }
        for index in range(4)
    ]

    assert notifier.send_breakout_summary(breakouts, datetime(2026, 4, 11, 8, 30)) is True

    assert len(calls) > 1
    assert calls[0].startswith("[1/")
    assert all("[突破名单] 4个" in call for call in calls)
    assert all("今日已突破" in call for call in calls)
