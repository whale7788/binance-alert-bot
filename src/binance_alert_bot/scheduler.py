from __future__ import annotations

import logging
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import AppConfig
from .exchange import OkxClient
from .notify import TelegramNotifier
from .state import MonitorState, StateStore
from .strategy import breakout_delta, calculate_threshold, is_breakout


LOGGER = logging.getLogger(__name__)


class BreakoutMonitor:
    """协调阈值刷新、价格检查和通知发送。"""

    def __init__(
        self,
        config: AppConfig,
        exchange: OkxClient,
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

        self.state = self.state_store.load(today=now.date().isoformat())
        LOGGER.info("Loaded state for date=%s with %d symbols", self.state.date, len(self.state.symbols))
        if self.state.needs_refresh(today=now.date().isoformat(), symbols=self.symbols):
            LOGGER.info("Threshold state is missing or stale; refreshing immediately")
            self.refresh_thresholds()
        else:
            LOGGER.info("Today's thresholds already exist; skipping startup refresh")

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
        today = now.date().isoformat()
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
        today = now.date().isoformat()
        state = self._state()
        if state.needs_refresh(today=today, symbols=self.symbols):
            LOGGER.info("State is stale before price check; refreshing thresholds")
            self.refresh_thresholds()
            state = self._state()

        LOGGER.info("Checking prices for %d symbols", len(state.symbols))
        new_breakouts: list[dict[str, float | str]] = []
        for symbol, symbol_state in list(state.symbols.items()):
            try:
                if symbol_state.notified:
                    continue
                current_price = self.exchange.get_current_price(symbol)
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

        summary_breakouts = self._sort_breakouts(self._collect_notified_breakouts(state) + new_breakouts)

        if self.notifier.send_breakout_summary(summary_breakouts, now):
            for item in new_breakouts:
                state.mark_notified(str(item["symbol"]), now)
            self._save_state(f"breakout summary for {len(summary_breakouts)} symbols")
            LOGGER.info("Breakout summary sent and state updated for %d new symbols", len(new_breakouts))
        else:
            LOGGER.error("Breakout summary notification failed; state not marked as notified")

    def send_periodic_summary(self) -> None:
        """定时推送今日已突破币种的最新涨幅概览。"""
        now = self._now()
        today = now.date().isoformat()
        state = self._state()
        if state.needs_refresh(today=today, symbols=self.symbols):
            LOGGER.info("State is stale before periodic summary; refreshing thresholds")
            self.refresh_thresholds()
            state = self._state()

        summary_breakouts = self._sort_breakouts_by_percent(self._collect_notified_breakouts(state))
        if not summary_breakouts:
            LOGGER.info("No today's breakouts for periodic summary")
            return

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
        for symbol, symbol_state in list(state.symbols.items()):
            if not symbol_state.notified:
                continue
            try:
                todays_breakouts.append(
                    {
                        "status": "今日已突破",
                        "symbol": symbol,
                        "current_price": self.exchange.get_current_price(symbol),
                        "threshold": symbol_state.threshold,
                        "breakout_time": symbol_state.first_breakout_time or symbol_state.last_notify_time or "",
                    }
                )
            except Exception:
                LOGGER.exception("Failed to refresh current price for already-broken symbol %s", symbol)
        return todays_breakouts

    def _state(self) -> MonitorState:
        """按需创建内存中的空状态。"""
        if self.state is None:
            self.state = MonitorState.empty(self._now().date().isoformat())
        return self.state

    def _now(self) -> datetime:
        """返回配置时区下的当前时间。"""
        return datetime.now(self.config.zoneinfo)

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
