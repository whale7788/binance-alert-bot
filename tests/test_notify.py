from datetime import datetime

import httpx

from binance_alert_bot.config import TelegramConfig
from binance_alert_bot.notify import TelegramNotifier
from binance_alert_bot.transfers.models import ThresholdRule, TransferEvent
from binance_alert_bot.transfers.service import MatchedTransfer


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


def test_telegram_notifier_can_send_transfer_summary(monkeypatch) -> None:
    def fake_post(*args, **kwargs):
        return make_response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(TelegramConfig(bot_token="token", chat_id="chat"))
    match = MatchedTransfer(
        event=TransferEvent(
            source="arkham",
            chain="ethereum",
            asset="USDT",
            amount=1_500_000.0,
            usd_value=1_500_000.0,
            tx_hash="0xabc",
            from_address="0xfrom",
            to_address="0xto",
            from_label="Binance",
            to_label="Whale",
        ),
        rule=ThresholdRule(chain="ethereum", asset="USDT", min_usd_value=1_000_000.0),
    )

    assert notifier.send_transfer_summary([match], datetime(2026, 4, 12, 8, 30)) is True


def test_telegram_notifier_splits_large_transfer_summary(monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"]["text"])
        return make_response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = TelegramNotifier(TelegramConfig(bot_token="token", chat_id="chat"))
    notifier.TRANSFER_SUMMARY_MAX_CHARS = 120
    matches = [
        MatchedTransfer(
            event=TransferEvent(
                source="arkham",
                chain="ethereum",
                asset="USDT",
                amount=1_500_000.0 + i,
                usd_value=1_500_000.0 + i,
                tx_hash=f"0x{i}",
                from_address="0xfrom",
                to_address="0xto",
                from_label="Binance",
                to_label="Whale",
            ),
            rule=ThresholdRule(min_usd_value=1_000_000.0),
        )
        for i in range(3)
    ]

    assert notifier.send_transfer_summary(matches, datetime(2026, 4, 12, 8, 30)) is True
    assert len(calls) > 1


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
                },
                {
                    "symbol": "ETH-USDT-SWAP",
                    "current_price": 202.0,
                    "threshold": 200.0,
                    "status": "新突破",
                    "breakout_time": "2026-04-11T08:31:00+00:00",
                },
                {
                    "symbol": "AAVE-USDT-SWAP",
                    "current_price": 94.11,
                    "threshold": 97.98,
                    "status": "今日已突破",
                    "breakout_time": "2026-04-11T08:32:00+00:00",
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
                },
                {
                    "symbol": "A-USDT-SWAP",
                    "current_price": 12.0,
                    "threshold": 10.0,
                    "status": "今日已突破",
                    "breakout_time": "2026-04-11T08:00:00+00:00",
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
