from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.interval import IntervalTrigger

from binance_alert_bot.config import AppConfig, TelegramConfig
from binance_alert_bot.scheduler import BreakoutMonitor
from binance_alert_bot.state import MonitorState, StateStore, SymbolState


class FakeExchange:
    def __init__(
        self,
        prices: dict[str, float] | None = None,
        failing_price_symbol: str | None = None,
        daily_highs: dict[str, list[float]] | None = None,
    ) -> None:
        self.prices = prices or {}
        self.failing_price_symbol = failing_price_symbol
        self.daily_highs = daily_highs or {}
        self.daily_high_calls = 0
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def get_usdt_perpetual_symbols(self) -> list[str]:
        return ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]

    def validate_symbols(self, requested_symbols: list[str]) -> list[str]:
        available = set(self.get_usdt_perpetual_symbols())
        return [symbol for symbol in requested_symbols if symbol in available]

    def get_daily_highs(self, symbol: str, limit: int = 10) -> list[float]:
        self.daily_high_calls += 1
        if symbol in self.daily_highs:
            return self.daily_highs[symbol]
        return [float(value) for value in range(1, limit + 1)]

    def get_current_price(self, symbol: str) -> float:
        if symbol == self.failing_price_symbol:
            raise RuntimeError("price failed")
        return self.prices[symbol]

    def get_current_prices(self, symbols) -> dict[str, float]:
        prices: dict[str, float] = {}
        for symbol in symbols:
            if symbol == self.failing_price_symbol:
                continue
            prices[symbol] = self.prices[symbol]
        return prices


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


def test_start_schedules_half_hour_periodic_summary(tmp_path) -> None:
    config = make_config(tmp_path).model_copy(update={"breakout_summary_interval_hours": 0.5})
    monitor = BreakoutMonitor(
        config,
        FakeExchange(prices={"BTC-USDT-SWAP": 9.0}),
        FakeNotifier(success=True),
        StateStore(config.state_path),
    )
    monitor.initialize()

    monitor.start()

    try:
        job = monitor.scheduler.get_job("breakout-summary")
        assert job is not None
        assert isinstance(job.trigger, IntervalTrigger)
        assert job.trigger.interval.total_seconds() == 30 * 60
    finally:
        monitor.shutdown()


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


def test_breakout_cycle_date_tracks_utc_day_for_1dutc_strategy() -> None:
    local_now = datetime(2026, 4, 18, 7, 59, tzinfo=ZoneInfo("Asia/Hong_Kong"))
    next_local_now = datetime(2026, 4, 18, 8, 0, tzinfo=ZoneInfo("Asia/Hong_Kong"))

    assert BreakoutMonitor._breakout_cycle_date(local_now) == "2026-04-17"
    assert BreakoutMonitor._breakout_cycle_date(next_local_now) == "2026-04-18"


def test_check_prices_refreshes_when_last_threshold_refresh_is_previous_utc_day(tmp_path) -> None:
    config = make_config(tmp_path)
    notifier = FakeNotifier(success=True)
    exchange = FakeExchange(prices={"BTC-USDT-SWAP": 9.0})
    monitor = BreakoutMonitor(config, exchange, notifier, StateStore(config.state_path))
    monitor.symbols = ["BTC-USDT-SWAP"]
    monitor.state = MonitorState(
        date="2026-04-18",
        last_threshold_refresh_time="2026-04-17T23:59:00+00:00",
        symbols={"BTC-USDT-SWAP": SymbolState(threshold=999.0, notified=False)},
    )
    monitor._now = lambda: datetime(2026, 4, 18, 0, 0, tzinfo=ZoneInfo("UTC"))  # type: ignore[method-assign]

    monitor.check_prices()

    assert monitor.state is not None
    assert monitor.state.symbols["BTC-USDT-SWAP"].threshold == 10.0
    assert notifier.sent == []


def test_refresh_thresholds_skips_duplicate_refresh_for_current_utc_day(tmp_path) -> None:
    config = make_config(tmp_path)
    notifier = FakeNotifier(success=True)
    exchange = FakeExchange(prices={"BTC-USDT-SWAP": 16.0})
    monitor = BreakoutMonitor(config, exchange, notifier, StateStore(config.state_path))

    monitor.initialize()
    monitor.check_prices()
    calls_after_initialize = exchange.daily_high_calls

    monitor.refresh_thresholds()

    assert exchange.daily_high_calls == calls_after_initialize
    assert monitor.state is not None
    assert monitor.state.symbols["BTC-USDT-SWAP"].notified is True


def test_check_prices_does_not_refresh_midday_only_for_new_symbol_listings(tmp_path) -> None:
    config = make_config(tmp_path, symbols=["BTC-USDT-SWAP"])
    notifier = FakeNotifier(success=True)
    exchange = FakeExchange(prices={"BTC-USDT-SWAP": 16.0, "ETH-USDT-SWAP": 17.0})
    monitor = BreakoutMonitor(config, exchange, notifier, StateStore(config.state_path))
    monitor.symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    monitor.state = MonitorState(
        date="2026-04-18",
        last_threshold_refresh_time="2026-04-18T00:05:00+00:00",
        symbols={"BTC-USDT-SWAP": SymbolState(threshold=10.0, notified=True, last_notify_time="2026-04-18T00:10:00+00:00", first_breakout_time="2026-04-18T00:10:00+00:00")},
    )
    monitor._now = lambda: datetime(2026, 4, 18, 12, 0, tzinfo=ZoneInfo("UTC"))  # type: ignore[method-assign]

    monitor.check_prices()

    assert exchange.daily_high_calls == 0
    assert notifier.sent == []
