from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import AppConfig
from .exchange import ExchangeClient
from .notify import TelegramNotifier
from .state import MonitorState, StateStore
from .strategy import breakout_delta, calculate_threshold, candle_change_percent, is_breakout, is_single_candle_drop


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
        if self.config.five_minute_drop_enabled or self.config.continuous_breakout_enabled:
            added = self._backfill_five_minute_drop_watchlist(now)
            if added:
                self._save_state(f"breakout watchlist backfill for {added} existing breakouts")

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
                IntervalTrigger(
                    minutes=self.config.breakout_summary_interval_minutes,
                    timezone=self.config.zoneinfo,
                ),
                id="breakout-summary",
                replace_existing=True,
            )
        if self.config.five_minute_drop_enabled:
            self.scheduler.add_job(
                self.check_five_minute_drops,
                IntervalTrigger(
                    seconds=self.config.five_minute_drop_check_interval_seconds,
                    timezone=self.config.zoneinfo,
                ),
                id="five-minute-drop-check",
                replace_existing=True,
                next_run_time=self._now(),
            )
        self.scheduler.start()
        LOGGER.info(
            "Scheduler started: refresh_time=%s, check_interval_minutes=%d, breakout_summary_interval_hours=%g, "
            "five_minute_drop_enabled=%s",
            refresh_time.strftime("%H:%M"),
            self.config.check_interval_minutes,
            self.config.breakout_summary_interval_hours,
            self.config.five_minute_drop_enabled,
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

        if self.config.monitor_all:
            try:
                self.symbols = self._apply_ignored_symbols(self.exchange.get_usdt_perpetual_symbols())
            except Exception:
                LOGGER.exception("Failed to refresh symbol list")

        state = self._state()
        last_refreshed = state.last_threshold_refresh_time
        last_refresh_cycle = (
            self._breakout_cycle_date(datetime.fromisoformat(last_refreshed)) if last_refreshed else None
        )
        if not state.needs_refresh(today=today, symbols=self.symbols, ignore_missing_symbols=True) and last_refresh_cycle == today:
            LOGGER.info("Skipping threshold refresh because thresholds are already current for UTC day %s", today)
            return

        LOGGER.info("Refreshing thresholds for %d symbols", len(self.symbols))
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

        sorted_thresholds = sorted(thresholds.items(), key=lambda item: item[1], reverse=True)
        sample = ", ".join(f"{symbol}={threshold:g}" for symbol, threshold in sorted_thresholds[:5])
        LOGGER.info(
            "Threshold refresh complete: refreshed=%d failed=%d utc_day=%s sample_top_thresholds=%s",
            len(thresholds),
            len(self.symbols) - len(thresholds),
            today,
            sample or "n/a",
        )

        self._state().replace_thresholds(today=today, refreshed_at=now, thresholds=thresholds)
        self._save_state("threshold refresh")

    def check_prices(self) -> None:
        """检查是否有新的突破，并在有新突破时推送完整名单。"""
        now = self._now()
        self._ensure_current_thresholds(now, context="price check")
        state = self._state()
        removed_from_watchlist = state.prune_breakout_watchlist(now, self._watchlist_days())
        if removed_from_watchlist:
            LOGGER.info("Pruned %d symbols from breakout watchlist before price check", removed_from_watchlist)

        LOGGER.info("Checking prices for %d symbols", len(state.symbols))
        current_prices = self.exchange.get_current_prices(state.symbols.keys())
        missing_prices = sorted(set(state.symbols.keys()) - set(current_prices.keys()))
        if missing_prices:
            LOGGER.warning(
                "Missing current prices for %d symbols during price check; sample=%s",
                len(missing_prices),
                ", ".join(missing_prices[:10]),
            )
        new_breakouts: list[dict[str, float | str | int]] = []
        compared_count = 0
        for symbol, symbol_state in list(state.symbols.items()):
            try:
                if symbol_state.notified:
                    continue
                if symbol not in current_prices:
                    continue
                current_price = current_prices[symbol]
                compared_count += 1
                delta, percent = breakout_delta(current_price, symbol_state.threshold)
                LOGGER.debug(
                    "Price check: symbol=%s current=%g threshold=%g delta=%+.6g pct=%+.2f notified=%s",
                    symbol,
                    current_price,
                    symbol_state.threshold,
                    delta,
                    percent,
                    symbol_state.notified,
                )
                if not is_breakout(current_price, symbol_state.threshold):
                    continue

                LOGGER.info(
                    "Breakout detected: symbol=%s current_price=%g threshold=%g delta=%+.6g pct=%+.2f",
                    symbol,
                    current_price,
                    symbol_state.threshold,
                    delta,
                    percent,
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

        LOGGER.info(
            "Price check complete: total_symbols=%d compared=%d already_notified=%d missing_prices=%d new_breakouts=%d",
            len(state.symbols),
            compared_count,
            sum(1 for symbol_state in state.symbols.values() if symbol_state.notified),
            len(missing_prices),
            len(new_breakouts),
        )
        if not new_breakouts:
            if removed_from_watchlist:
                self._save_state("breakout watchlist pruning")
            return

        continuous_breakouts = self._collect_continuous_breakouts(new_breakouts, state, now)
        todays_breakout_count = sum(1 for symbol_state in state.symbols.values() if symbol_state.notified)
        notification_breakouts = self._assign_breakout_ordinals(
            self._sort_breakouts(new_breakouts),
            start=todays_breakout_count + 1,
        )

        if self.notifier.send_breakout_summary(notification_breakouts, now):
            if continuous_breakouts:
                if self.notifier.send_continuous_breakout_alerts(continuous_breakouts, now):
                    LOGGER.info("Continuous breakout alerts sent for %d symbols", len(continuous_breakouts))
                else:
                    LOGGER.error("Continuous breakout alert notification failed")
            for item in new_breakouts:
                symbol = str(item["symbol"])
                state.mark_notified(symbol, now)
                state.record_breakout_watch(symbol, now)
            self._save_state(f"breakout summary for {len(new_breakouts)} symbols")
            LOGGER.info("Breakout summary sent and state updated for %d new symbols", len(new_breakouts))
        else:
            LOGGER.error("Breakout summary notification failed; state not marked as notified")

    def check_five_minute_drops(self) -> None:
        """监控突破池里币种的当前 5m K 线盘中急跌。"""
        if not self.config.five_minute_drop_enabled:
            LOGGER.info("Skipping 5m drop check because it is disabled")
            return

        now = self._now()
        state = self._state()
        added = self._backfill_five_minute_drop_watchlist(now)
        removed = state.prune_breakout_watchlist(now, self._watchlist_days())
        if removed:
            LOGGER.info("Pruned %d symbols from 5m drop watchlist", removed)

        if not state.breakout_watchlist:
            LOGGER.info("No symbols in 5m drop watchlist")
            if added or removed:
                self._save_state("5m drop watchlist maintenance")
            return

        watch_items = list(state.breakout_watchlist.items())
        max_workers = min(self.config.five_minute_drop_max_workers, len(watch_items))
        alerts_by_symbol: dict[str, dict[str, float | str | datetime]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._build_five_minute_drop_alert,
                    symbol,
                    watch_state.last_drop_alert_kline_open_time,
                ): symbol
                for symbol, watch_state in watch_items
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    alert = future.result()
                except Exception:
                    LOGGER.exception("Failed to check 5m drop for %s; continuing with remaining symbols", symbol)
                    continue
                if alert is not None:
                    alerts_by_symbol[symbol] = alert

        alerts = [alerts_by_symbol[symbol] for symbol, _ in watch_items if symbol in alerts_by_symbol]

        LOGGER.info(
            "5m drop check complete: watchlist=%d removed=%d workers=%d alerts=%d",
            len(state.breakout_watchlist),
            removed,
            max_workers,
            len(alerts),
        )
        if not alerts:
            if added or removed:
                self._save_state("5m drop watchlist maintenance")
            return

        if self.notifier.send_five_minute_drop_alerts(alerts, now):
            for item in alerts:
                state.mark_drop_alerted(str(item["symbol"]), item["kline_open_time"])
            self._save_state(f"5m drop alerts for {len(alerts)} symbols")
            LOGGER.info("5m drop alerts sent and state updated for %d symbols", len(alerts))
        else:
            LOGGER.error("5m drop alert notification failed; alert state not updated")
            if added or removed:
                self._save_state("5m drop watchlist maintenance")

    def _backfill_five_minute_drop_watchlist(self, now: datetime) -> int:
        """把今天已经突破但尚未入池的币种补进最近突破观察池。"""
        state = self._state()
        added = 0
        for symbol, symbol_state in state.symbols.items():
            if not symbol_state.notified or symbol in state.breakout_watchlist:
                continue
            breakout_time = self._parse_state_time(
                symbol_state.first_breakout_time or symbol_state.last_notify_time,
                fallback=now,
            )
            state.record_breakout_watch(symbol, breakout_time)
            added += 1
        if added:
            LOGGER.info("Backfilled %d existing breakout symbols into breakout watchlist", added)
        return added

    def _collect_continuous_breakouts(
        self,
        new_breakouts: list[dict[str, float | str | int]],
        state: MonitorState,
        now: datetime,
    ) -> list[dict[str, float | str]]:
        """从本轮新突破里筛出最近一周内再次突破的币种。"""
        if not self.config.continuous_breakout_enabled:
            return []

        alerts: list[dict[str, float | str]] = []
        cutoff = now - self._watchlist_window()
        today = self._breakout_cycle_date(now)
        for item in self._sort_breakouts(new_breakouts):
            symbol = str(item["symbol"])
            previous = state.breakout_watchlist.get(symbol)
            if previous is None:
                continue

            previous_breakout_time = self._parse_state_time(previous.last_breakout_time, fallback=now)
            if previous_breakout_time < cutoff:
                continue
            if self._breakout_cycle_date(previous_breakout_time) == today:
                continue

            alerts.append(
                {
                    "symbol": symbol,
                    "current_price": float(item["current_price"]),
                    "threshold": float(item["threshold"]),
                    "breakout_time": str(item.get("breakout_time", now.isoformat())),
                    "previous_breakout_time": previous_breakout_time.isoformat(),
                }
            )
        return alerts

    def _watchlist_window(self):
        """返回最近突破观察池需要保留的最长时间窗口。"""
        return timedelta(days=self._watchlist_days())

    def _watchlist_days(self) -> int:
        """返回最近突破观察池需要保留的最长天数。"""
        return max(
            self.config.five_minute_drop_watch_days,
            self.config.continuous_breakout_watch_days,
        )

    def _build_five_minute_drop_alert(
        self,
        symbol: str,
        last_drop_alert_kline_open_time: str | None,
    ) -> dict[str, float | str | datetime] | None:
        """读取当前 5m K 线并判断是否需要急跌预警。"""
        latest_kline = self.exchange.get_latest_kline(symbol, interval="5m")
        kline_open_time = latest_kline.open_time.isoformat()
        if last_drop_alert_kline_open_time == kline_open_time:
            return None

        percent = candle_change_percent(latest_kline.open_price, latest_kline.close_price)
        LOGGER.debug(
            "5m intrabar drop check: symbol=%s open=%g current=%g pct=%+.2f threshold=-%g kline_open=%s",
            symbol,
            latest_kline.open_price,
            latest_kline.close_price,
            percent,
            self.config.five_minute_drop_percent,
            kline_open_time,
        )
        if not is_single_candle_drop(
            latest_kline.open_price,
            latest_kline.close_price,
            self.config.five_minute_drop_percent,
        ):
            return None

        return {
            "symbol": symbol,
            "open_price": latest_kline.open_price,
            "close_price": latest_kline.close_price,
            "drop_percent": percent,
            "kline_open_time": latest_kline.open_time,
        }

    def send_periodic_summary(self) -> None:
        """定时推送今日已突破币种的最新涨幅概览。"""
        now = self._now()
        self._ensure_current_thresholds(now, context="periodic summary")
        state = self._state()

        summary_breakouts = self._sort_breakouts_by_percent(self._collect_notified_breakouts(state))
        if not summary_breakouts:
            LOGGER.info("No today's breakouts for periodic summary")
            return

        top_sample = ", ".join(
            f"{item['symbol']}({breakout_delta(float(item['current_price']), float(item['threshold']))[1]:+.2f}%)"
            for item in summary_breakouts[:5]
        )
        LOGGER.info(
            "Preparing periodic breakout summary: symbols=%d top_sample=%s",
            len(summary_breakouts),
            top_sample or "n/a",
        )
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
            LOGGER.info("Monitoring all %s USDT perpetual symbols: count=%d", self.config.exchange.upper(), len(symbols))
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
        missing_prices = sorted(
            symbol for symbol, symbol_state in state.symbols.items() if symbol_state.notified and symbol not in current_prices
        )
        if missing_prices:
            LOGGER.warning(
                "Missing current prices for %d already-broken symbols; sample=%s",
                len(missing_prices),
                ", ".join(missing_prices[:10]),
            )
        for symbol, symbol_state in list(state.symbols.items()):
            if not symbol_state.notified:
                continue
            try:
                if symbol not in current_prices:
                    continue
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
        if state.needs_refresh(today=today, symbols=self.symbols, ignore_missing_symbols=True) or last_refresh_cycle != today:
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
    def _parse_state_time(value: str | None, fallback: datetime) -> datetime:
        """解析状态文件里的时间，缺失或损坏时回退到当前时间。"""
        if not value:
            return fallback
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return fallback
        if parsed.tzinfo is None and fallback.tzinfo is not None:
            return parsed.replace(tzinfo=fallback.tzinfo)
        return parsed

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
