from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SymbolState:
    """单个币种当天的阈值和通知状态。"""

    threshold: float
    notified: bool = False
    last_notify_time: str | None = None
    first_breakout_time: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SymbolState":
        """从 JSON 结构恢复 SymbolState。"""
        return cls(
            threshold=float(data["threshold"]),
            notified=bool(data.get("notified", False)),
            last_notify_time=data.get("lastNotifyTime"),
            first_breakout_time=data.get("firstBreakoutTime"),
        )

    def to_dict(self) -> dict[str, Any]:
        """把 SymbolState 序列化成 JSON 结构。"""
        return {
            "threshold": self.threshold,
            "notified": self.notified,
            "lastNotifyTime": self.last_notify_time,
            "firstBreakoutTime": self.first_breakout_time,
        }


@dataclass
class MonitorState:
    """当前交易日的持久化状态。"""

    date: str
    last_threshold_refresh_time: str | None = None
    symbols: dict[str, SymbolState] = field(default_factory=dict)

    @classmethod
    def empty(cls, today: str) -> "MonitorState":
        """为新的一天或首次运行创建空状态。"""
        return cls(date=today)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MonitorState":
        """从 JSON 内容解析监控状态。"""
        symbols = {
            symbol.upper(): SymbolState.from_dict(symbol_data)
            for symbol, symbol_data in data.get("symbols", {}).items()
        }
        return cls(
            date=str(data["date"]),
            last_threshold_refresh_time=data.get("lastThresholdRefreshTime"),
            symbols=symbols,
        )

    def to_dict(self) -> dict[str, Any]:
        """把监控状态序列化成 JSON 数据。"""
        return {
            "date": self.date,
            "lastThresholdRefreshTime": self.last_threshold_refresh_time,
            "symbols": {symbol: state.to_dict() for symbol, state in sorted(self.symbols.items())},
        }

    def needs_refresh(self, today: str, symbols: list[str], ignore_missing_symbols: bool = False) -> bool:
        """日期变化、缺少 symbol，或残留旧 symbol 时都需要刷新。"""
        if self.date != today:
            return True
        expected = {symbol.upper() for symbol in symbols}
        current = set(self.symbols.keys())
        if ignore_missing_symbols:
            return not current or not current.issubset(expected)
        return current != expected

    def replace_thresholds(self, today: str, refreshed_at: datetime, thresholds: dict[str, float]) -> None:
        """替换当天全部阈值；同日刷新时保留已有币种的通知状态。"""
        preserve_existing = self.date == today
        previous_symbols = self.symbols
        self.date = today
        self.last_threshold_refresh_time = refreshed_at.isoformat()
        self.symbols = {
            symbol: self._build_symbol_state(
                symbol=symbol,
                threshold=threshold,
                previous=previous_symbols.get(symbol) if preserve_existing else None,
            )
            for symbol, threshold in sorted(thresholds.items())
        }

    def mark_notified(self, symbol: str, notified_at: datetime) -> None:
        """把某个币种标记为当天已通知。"""
        self.symbols[symbol].notified = True
        if self.symbols[symbol].first_breakout_time is None:
            self.symbols[symbol].first_breakout_time = notified_at.isoformat()
        self.symbols[symbol].last_notify_time = notified_at.isoformat()

    @staticmethod
    def _build_symbol_state(symbol: str, threshold: float, previous: SymbolState | None) -> SymbolState:
        if previous is None:
            return SymbolState(threshold=threshold, notified=False, last_notify_time=None, first_breakout_time=None)
        return SymbolState(
            threshold=threshold,
            notified=previous.notified,
            last_notify_time=previous.last_notify_time,
            first_breakout_time=previous.first_breakout_time,
        )


class StateStore:
    """负责把 MonitorState 读写到磁盘。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, today: str) -> MonitorState:
        """读取状态文件；不存在时返回当天空状态。"""
        if not self.path.exists():
            return MonitorState.empty(today)
        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return MonitorState.from_dict(data)

    def save(self, state: MonitorState) -> None:
        """用原子写入方式保存状态。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_name(f"{self.path.name}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(state.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, self.path)
