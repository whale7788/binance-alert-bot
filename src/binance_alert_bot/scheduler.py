from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import AppConfig
from .exchange import ExchangeClient
from .notify import TelegramNotifier
from .state import MonitorState, StateStore
from .strategy import breakout_delta, calculate_threshold, is_breakout


LOGGER = logging.getLogger(__name__)
UTC = ZoneInfo("UTC")


class BreakoutMonitor:
    """协调阈值刷新、价格检查和通知发送。"""

    def __init__(
        self,
        config: AppConfig,
        exchange: ExchangeClient,
        notifier: TelegramNotifier,
        state_store: StateStore,
    ) -> None:
        self.config = config
        self.exchange = exchange
        self.notifier = notifier
        self.state_store = state_store
        self.symbols: list[str] = []
        self.state: MonitorState | None = None
        self.scheduler = BackgroundScheduler(timezone=config.zoneinfo)

    def initialize(self) -> None:
        """启动前准备监控币种和当天状态。"""
        now = self._now()
        self.symbols = self._resolve_symbols()
        if not self.symbols:
            raise RuntimeError("No valid symbols to monitor")

        self.state = self.state_store.load(today=self._breakout_cycle_date(now))
        LOGGER.info("Loaded state for date=%s with %d symbols", self.state.date, len(self.state.symbols))
        self._ensure_current_thresholds(now, context="startup")

    def start(self) -> None:
        """注册定时任务并启动调度器。"""
        refresh_time = self.config.threshold_refresh_time
        self.scheduler.add_job(
            self.refresh_thresholds,
            CronTrigger(hour=refresh_time.hour, minute=refresh_time.minute, timezone=self.config.zoneinfo),
            id="daily-threshold-refresh",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.check_prices,
            IntervalTrigger(minutes=self.config.check_interval_minutes, timezone=self.config.zoneinfo),
            id="price-check",
            replace_existing=True,
            next_run_time=self._now(),
        )
        if self.config.breakout_summary_interval_hours > 0:
            self.scheduler.add_job(
                self.send_periodic_summary,
                CronTrigger(
                    hour=f"*/{self.config.breakout_summary_interval_hours}",
                    minute=0,
                    timezone=self.config.zoneinfo,
                ),
                id="breakout-summary",
                replace_existing=True,
            )
        self.scheduler.start()
        LOGGER.info(
            "Scheduler started: refresh_time=%s, check_interval_minutes=%d, breakout_summary_interval_hours=%d",
            refresh_time.strftime("%H:%M"),
            self.config.check_interval_minutes,
            self.config.breakout_summary_interval_hours,
        )

    def run_forever(self) -> None:
        """持续运行直到被手动中断。"""
        self.initialize()
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            LOGGER.info("Received KeyboardInterrupt; shutting down")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """停止调度器并释放资源。"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        self.exchange.close()
        LOGGER.info("Monitor stopped")

    def refresh_thresholds(self) -> None:
        """刷新当天的突破阈值。"""
        now = self._now()
        today = self._breakout_cycle_date(now)
        LOGGER.info("Refreshing thresholds for %d symbols", len(self.symbols))

        if self.config.monitor_all:
            try:
                self.symbols = self._apply_ignored_symbols(self.exchange.get_usdt_perpetual_symbols())
            except Exception:
                LOGGER.exception("Failed to refresh symbol list")

        thresholds: dict[str, float] = {}
        for symbol in self.symbols:
            try:
                highs = self.exchange.get_daily_highs(symbol, limit=self.config.threshold_days)
                thresholds[symbol] = calculate_threshold(highs)
                LOGGER.info("Threshold refreshed: symbol=%s threshold=%s", symbol, thresholds[symbol])
            except Exception:
                LOGGER.exception("Failed to refresh threshold for %s; skipping this symbol", symbol)

        if not thresholds:
            LOGGER.error("No thresholds were refreshed; keeping previous state")
            return

        self._state().replace_thresholds(today=today, refreshed_at=now, thresholds=thresholds)
        self._save_state("threshold refresh")

    def check_prices(self) -> None:
        """检查是否有新的突破，并在有新突破时推送完整名单。"""
        now = self._now()
        self._ensure_current_thresholds(now, context="price check")
        state = self._state()

        LOGGER.info("Checking prices for %d symbols", len(state.symbols))
        current_prices = self.exchange.get_current_prices(state.symbols.keys())
        new_breakouts: list[dict[str, float | str | int]] = []
        for symbol, symbol_state in list(state.symbols.items()):
            try:
                if symbol_state.notified:
                    continue
                current_price = current_prices[symbol]
                if not is_breakout(current_price, symbol_state.threshold):
                    LOGGER.debug(
                        "No breakout: symbol=%s current_price=%s threshold=%s",
                        symbol,
                        current_price,
                        symbol_state.threshold,
                    )
                    continue

                LOGGER.info(
                    "Breakout detected: symbol=%s current_price=%s threshold=%s",
                    symbol,
                    current_price,
                    symbol_state.threshold,
                )
                new_breakouts.append(
                    {
                        "status": "新突破",
                        "symbol": symbol,
                        "current_price": current_price,
                        "threshold": symbol_state.threshold,
                        "breakout_time": now.isoformat(),
                    }
                )
            except Exception:
                LOGGER.exception("Failed to process %s; continuing with remaining symbols", symbol)

        if not new_breakouts:
            return

        todays_breakout_count = sum(1 for symbol_state in state.symbols.values() if symbol_state.notified)
        notification_breakouts = self._assign_breakout_ordinals(
            self._sort_breakouts(new_breakouts),
            start=todays_breakout_count + 1,
        )

        if self.notifier.send_breakout_summary(notification_breakouts, now):
            for item in new_breakouts:
                state.mark_notified(str(item["symbol"]), now)
            self._save_state(f"breakout summary for {len(new_breakouts)} symbols")
            LOGGER.info("Breakout summary sent and state updated for %d new symbols", len(new_breakouts))
        else:
            LOGGER.error("Breakout summary notification failed; state not marked as notified")

    def send_periodic_summary(self) -> None:
        """定时推送今日已突破币种的最新涨幅概览。"""
        now = self._now()
        self._ensure_current_thresholds(now, context="periodic summary")
        state = self._state()

        summary_breakouts = self._sort_breakouts_by_percent(self._collect_notified_breakouts(state))
        if not summary_breakouts:
            LOGGER.info("No today's breakouts for periodic summary")
            return

        summary_breakouts = self._assign_breakout_ordinals(summary_breakouts)
        if self.notifier.send_breakout_summary(summary_breakouts, now):
            LOGGER.info("Periodic breakout summary sent for %d symbols", len(summary_breakouts))
        else:
            LOGGER.error("Periodic breakout summary notification failed")

    def _resolve_symbols(self) -> list[str]:
        """按配置返回本次实际要监控的币种。"""
        if self.config.monitor_all:
            symbols = self.exchange.get_usdt_perpetual_symbols()
        else:
            symbols = self.exchange.validate_symbols(self.config.symbols)

        symbols = self._apply_ignored_symbols(symbols)

        if self.config.monitor_all:
            LOGGER.info("Monitoring all OKX USDT perpetual symbols: count=%d", len(symbols))
        else:
            LOGGER.info("Monitoring configured symbol whitelist: %s", ", ".join(symbols))
        return symbols

    def _apply_ignored_symbols(self, symbols: list[str]) -> list[str]:
        """从候选合约中排除配置里的忽略名单。"""
        ignored = {symbol.strip().upper() for symbol in self.config.ignored_symbols}
        if not ignored:
            return symbols

        filtered = [symbol for symbol in symbols if symbol not in ignored]
        ignored_count = len(symbols) - len(filtered)
        if ignored_count:
            LOGGER.info("Ignored %d configured symbols: %s", ignored_count, ", ".join(sorted(ignored)))
        return filtered

    def _save_state(self, reason: str) -> None:
        """保存状态，失败时只记日志。"""
        try:
            self.state_store.save(self._state())
            LOGGER.info("State saved after %s", reason)
        except Exception:
            LOGGER.exception("Failed to save state after %s", reason)

    def _collect_notified_breakouts(self, state: MonitorState) -> list[dict[str, float | str]]:
        """收集今天已突破币种的最新价格。"""
        todays_breakouts: list[dict[str, float | str]] = []
        current_prices = self.exchange.get_current_prices(state.symbols.keys())
        for symbol, symbol_state in list(state.symbols.items()):
            if not symbol_state.notified:
                continue
            try:
                current_price = current_prices[symbol]
                todays_breakouts.append(
                    {
                        "status": "今日已突破",
                        "symbol": symbol,
                        "current_price": current_price,
                        "threshold": symbol_state.threshold,
                        "breakout_time": symbol_state.first_breakout_time or symbol_state.last_notify_time or "",
                    }
                )
            except Exception:
                LOGGER.exception("Failed to refresh current price for already-broken symbol %s", symbol)
        return todays_breakouts

    def _ensure_current_thresholds(self, now: datetime, context: str) -> None:
        """在进入核心流程前，确保当前 UTC 交易日的阈值已经刷新。"""
        state = self._state()
        today = self._breakout_cycle_date(now)
        last_refreshed = state.last_threshold_refresh_time
        last_refresh_cycle = (
            self._breakout_cycle_date(datetime.fromisoformat(last_refreshed)) if last_refreshed else None
        )
        if state.needs_refresh(today=today, symbols=self.symbols) or last_refresh_cycle != today:
            LOGGER.info(
                "Thresholds are stale before %s; refreshing thresholds (state_date=%s, last_refresh_cycle=%s, today=%s)",
                context,
                state.date,
                last_refresh_cycle,
                today,
            )
            self.refresh_thresholds()
        else:
            LOGGER.info("Thresholds already current for %s on UTC day %s", context, today)

    def _state(self) -> MonitorState:
        """按需创建内存中的空状态。"""
        if self.state is None:
            self.state = MonitorState.empty(self._now().date().isoformat())
        return self.state

    def _now(self) -> datetime:
        """返回配置时区下的当前时间。"""
        return datetime.now(self.config.zoneinfo)

    @staticmethod
    def _breakout_cycle_date(now: datetime) -> str:
        """把状态切换边界对齐到 1Dutc 的 UTC 交易日。"""
        return now.astimezone(UTC).date().isoformat()

    @staticmethod
    def _sort_breakouts(breakouts: list[dict[str, float | str]]) -> list[dict[str, float | str]]:
        """按首次突破时间升序排序。"""
        return sorted(breakouts, key=lambda item: str(item.get("breakout_time", "")))

    @staticmethod
    def _sort_breakouts_by_percent(breakouts: list[dict[str, float | str]]) -> list[dict[str, float | str]]:
        """按涨幅从高到低排序，涨幅相同时再按首次突破时间升序。"""

        def sort_key(item: dict[str, float | str]) -> tuple[float, str]:
            _, percent = breakout_delta(float(item["current_price"]), float(item["threshold"]))
            return (-percent, str(item.get("breakout_time", "")))

        return sorted(breakouts, key=sort_key)

    @staticmethod
    def _assign_breakout_ordinals(
        breakouts: list[dict[str, float | str]],
        start: int = 1,
    ) -> list[dict[str, float | str | int]]:
        """在不改变当前展示顺序的前提下，为每条记录补上当天累计突破序号。"""
        order_by_symbol = {
            str(item["symbol"]): index
            for index, item in enumerate(
                sorted(breakouts, key=lambda item: (str(item.get("breakout_time", "")), str(item.get("symbol", "")))),
                start=start,
            )
        }
        return [{**item, "breakout_ordinal": order_by_symbol[str(item["symbol"])]} for item in breakouts]
