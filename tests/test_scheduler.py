from pathlib import Path

from binance_alert_bot.config import AppConfig, TelegramConfig
from binance_alert_bot.scheduler import BreakoutMonitor
from binance_alert_bot.state import StateStore


class FakeExchange:
    def __init__(self, prices: dict[str, float] | None = None, failing_price_symbol: str | None = None) -> None:
        self.prices = prices or {}
        self.failing_price_symbol = failing_price_symbol
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def get_usdt_perpetual_symbols(self) -> list[str]:
        return ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]

    def validate_symbols(self, requested_symbols: list[str]) -> list[str]:
        available = set(self.get_usdt_perpetual_symbols())
        return [symbol for symbol in requested_symbols if symbol in available]

    def get_daily_highs(self, symbol: str, limit: int = 10) -> list[float]:
        return [float(value) for value in range(1, limit + 1)]

    def get_current_price(self, symbol: str) -> float:
        if symbol == self.failing_price_symbol:
            raise RuntimeError("price failed")
        return self.prices[symbol]


class FakeNotifier:
    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.sent: list[list[tuple[str, str]]] = []
        self.sent_with_ordinals: list[list[tuple[str, str, int | None]]] = []

    def send_breakout_summary(self, breakouts, breakout_time) -> bool:
        self.sent.append([(item["symbol"], item["status"]) for item in breakouts])
        self.sent_with_ordinals.append(
            [(item["symbol"], item["status"], item.get("breakout_ordinal")) for item in breakouts]
        )
        return self.success


def make_config(tmp_path: Path, symbols: list[str] | None = None) -> AppConfig:
    return AppConfig(
        monitor_all=False,
        symbols=symbols or ["BTC-USDT-SWAP"],
        ignored_symbols=[],
        check_interval_minutes=15,
        breakout_summary_interval_hours=0,
        threshold_days=10,
        threshold_refresh_time="00:05",
        timezone="UTC",
        state_path=tmp_path / "state.json",
        log_file=tmp_path / "monitor.log",
        log_level="INFO",
        telegram=TelegramConfig(bot_token="token", chat_id="chat"),
    )


def test_initialize_refreshes_missing_thresholds(tmp_path) -> None:
    config = make_config(tmp_path)
    monitor = BreakoutMonitor(config, FakeExchange(), FakeNotifier(), StateStore(config.state_path))

    monitor.initialize()

    assert monitor.state is not None
    assert monitor.state.symbols["BTC-USDT-SWAP"].threshold == 10.0
    assert config.state_path.exists()


def test_breakout_sends_once_per_day(tmp_path) -> None:
    config = make_config(tmp_path)
    notifier = FakeNotifier(success=True)
    monitor = BreakoutMonitor(
        config,
        FakeExchange(prices={"BTC-USDT-SWAP": 16.0}),
        notifier,
        StateStore(config.state_path),
    )
    monitor.initialize()

    monitor.check_prices()
    monitor.check_prices()

    assert notifier.sent == [[("BTC-USDT-SWAP", "新突破")]]
    assert monitor.state is not None
    assert monitor.state.symbols["BTC-USDT-SWAP"].notified is True


def test_notification_failure_does_not_mark_notified(tmp_path) -> None:
    config = make_config(tmp_path)
    notifier = FakeNotifier(success=False)
    monitor = BreakoutMonitor(
        config,
        FakeExchange(prices={"BTC-USDT-SWAP": 16.0}),
        notifier,
        StateStore(config.state_path),
    )
    monitor.initialize()

    monitor.check_prices()

    assert notifier.sent == [[("BTC-USDT-SWAP", "新突破")]]
    assert monitor.state is not None
    assert monitor.state.symbols["BTC-USDT-SWAP"].notified is False


def test_one_symbol_price_failure_does_not_stop_other_symbols(tmp_path) -> None:
    config = make_config(tmp_path, symbols=["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    notifier = FakeNotifier(success=True)
    monitor = BreakoutMonitor(
        config,
        FakeExchange(prices={"ETH-USDT-SWAP": 16.0}, failing_price_symbol="BTC-USDT-SWAP"),
        notifier,
        StateStore(config.state_path),
    )
    monitor.initialize()

    monitor.check_prices()

    assert notifier.sent == [[("ETH-USDT-SWAP", "新突破")]]


def test_multiple_breakouts_are_sent_in_one_summary(tmp_path) -> None:
    config = make_config(tmp_path, symbols=["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    notifier = FakeNotifier(success=True)
    monitor = BreakoutMonitor(
        config,
        FakeExchange(prices={"BTC-USDT-SWAP": 16.0, "ETH-USDT-SWAP": 17.0}),
        notifier,
        StateStore(config.state_path),
    )
    monitor.initialize()

    monitor.check_prices()

    assert notifier.sent == [[("BTC-USDT-SWAP", "新突破"), ("ETH-USDT-SWAP", "新突破")]]
    assert monitor.state is not None
    assert monitor.state.symbols["BTC-USDT-SWAP"].notified is True
    assert monitor.state.symbols["ETH-USDT-SWAP"].notified is True


def test_new_breakout_summary_does_not_include_symbols_already_broken_today(tmp_path) -> None:
    config = make_config(tmp_path, symbols=["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    notifier = FakeNotifier(success=True)
    exchange = FakeExchange(prices={"BTC-USDT-SWAP": 16.0, "ETH-USDT-SWAP": 9.0})
    monitor = BreakoutMonitor(config, exchange, notifier, StateStore(config.state_path))
    monitor.initialize()
    monitor.check_prices()

    exchange.prices = {"BTC-USDT-SWAP": 18.0, "ETH-USDT-SWAP": 16.0}
    monitor.check_prices()

    assert notifier.sent == [
        [("BTC-USDT-SWAP", "新突破")],
        [("ETH-USDT-SWAP", "新突破")],
    ]
    assert monitor.state is not None
    assert monitor.state.symbols["BTC-USDT-SWAP"].notified is True
    assert monitor.state.symbols["ETH-USDT-SWAP"].notified is True


def test_new_breakout_ordinals_accumulate_across_notifications(tmp_path) -> None:
    config = make_config(tmp_path, symbols=["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    notifier = FakeNotifier(success=True)
    exchange = FakeExchange(prices={"BTC-USDT-SWAP": 16.0, "ETH-USDT-SWAP": 9.0})
    monitor = BreakoutMonitor(config, exchange, notifier, StateStore(config.state_path))
    monitor.initialize()

    monitor.check_prices()

    exchange.prices = {"BTC-USDT-SWAP": 18.0, "ETH-USDT-SWAP": 16.0}
    monitor.check_prices()

    assert notifier.sent_with_ordinals[0][0][0] == "BTC-USDT-SWAP"
    assert notifier.sent_with_ordinals[0][0][2] == 1
    assert notifier.sent_with_ordinals[1][0][0] == "ETH-USDT-SWAP"
    assert notifier.sent_with_ordinals[1][0][2] == 2


def test_sort_breakouts_uses_breakout_time_only() -> None:
    breakouts = [
        {
            "status": "今日已突破",
            "symbol": "B-USDT-SWAP",
            "current_price": 13.0,
            "threshold": 10.0,
            "breakout_time": "2026-04-12T10:00:00+00:00",
        },
        {
            "status": "今日已突破",
            "symbol": "A-USDT-SWAP",
            "current_price": 12.0,
            "threshold": 10.0,
            "breakout_time": "2026-04-12T09:00:00+00:00",
        },
        {
            "status": "新突破",
            "symbol": "C-USDT-SWAP",
            "current_price": 14.0,
            "threshold": 10.0,
            "breakout_time": "2026-04-12T10:00:00+00:00",
        },
    ]

    sorted_breakouts = BreakoutMonitor._sort_breakouts(breakouts)

    assert [item["symbol"] for item in sorted_breakouts] == [
        "A-USDT-SWAP",
        "B-USDT-SWAP",
        "C-USDT-SWAP",
    ]


def test_periodic_summary_sends_todays_breakouts_without_new_breakouts(tmp_path) -> None:
    config = make_config(tmp_path)
    notifier = FakeNotifier(success=True)
    monitor = BreakoutMonitor(
        config,
        FakeExchange(prices={"BTC-USDT-SWAP": 16.0}),
        notifier,
        StateStore(config.state_path),
    )
    monitor.initialize()
    monitor.check_prices()

    monitor.send_periodic_summary()

    assert notifier.sent == [
        [("BTC-USDT-SWAP", "新突破")],
        [("BTC-USDT-SWAP", "今日已突破")],
    ]


def test_periodic_summary_sort_uses_percent_desc() -> None:
    breakouts = [
        {
            "status": "今日已突破",
            "symbol": "A-USDT-SWAP",
            "current_price": 11.0,
            "threshold": 10.0,
            "breakout_time": "2026-04-12T09:00:00+00:00",
        },
        {
            "status": "今日已突破",
            "symbol": "B-USDT-SWAP",
            "current_price": 13.0,
            "threshold": 10.0,
            "breakout_time": "2026-04-12T10:00:00+00:00",
        },
        {
            "status": "今日已突破",
            "symbol": "C-USDT-SWAP",
            "current_price": 12.0,
            "threshold": 10.0,
            "breakout_time": "2026-04-12T08:00:00+00:00",
        },
    ]

    sorted_breakouts = BreakoutMonitor._sort_breakouts_by_percent(breakouts)

    assert [item["symbol"] for item in sorted_breakouts] == [
        "B-USDT-SWAP",
        "C-USDT-SWAP",
        "A-USDT-SWAP",
    ]


def test_resolve_symbols_excludes_ignored_symbols(tmp_path) -> None:
    config = AppConfig(
        monitor_all=False,
        symbols=["BTC-USDT-SWAP", "INTC-USDT-SWAP", "SNDK-USDT-SWAP"],
        ignored_symbols=["INTC-USDT-SWAP", "SNDK-USDT-SWAP"],
        check_interval_minutes=15,
        breakout_summary_interval_hours=0,
        threshold_days=10,
        threshold_refresh_time="00:05",
        timezone="UTC",
        state_path=tmp_path / "state.json",
        log_file=tmp_path / "monitor.log",
        log_level="INFO",
        telegram=TelegramConfig(bot_token="token", chat_id="chat"),
    )
    monitor = BreakoutMonitor(config, FakeExchange(), FakeNotifier(), StateStore(config.state_path))

    assert monitor._resolve_symbols() == ["BTC-USDT-SWAP"]


def test_refresh_thresholds_reapplies_ignored_symbols_in_monitor_all_mode(tmp_path) -> None:
    config = AppConfig(
        monitor_all=True,
        symbols=[],
        ignored_symbols=["INTC-USDT-SWAP"],
        check_interval_minutes=15,
        breakout_summary_interval_hours=0,
        threshold_days=10,
        threshold_refresh_time="00:05",
        timezone="UTC",
        state_path=tmp_path / "state.json",
        log_file=tmp_path / "monitor.log",
        log_level="INFO",
        telegram=TelegramConfig(bot_token="token", chat_id="chat"),
    )
    monitor = BreakoutMonitor(config, FakeExchange(), FakeNotifier(), StateStore(config.state_path))

    monitor.initialize()

    assert "INTC-USDT-SWAP" not in monitor.symbols
