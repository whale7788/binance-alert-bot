from __future__ import annotations

import os
import tomllib
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class TelegramConfig(BaseModel):
    """Telegram 通知配置。"""

    bot_token: str = ""
    chat_id: str = ""
    new_breakout_chat_id: str = ""
    existing_breakout_chat_id: str = ""
    five_minute_drop_chat_id: str = ""
    continuous_breakout_chat_id: str = ""

    @model_validator(mode="after")
    def apply_environment(self) -> "TelegramConfig":
        """允许环境变量覆盖配置文件。"""
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", self.bot_token).strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", self.chat_id).strip()
        self.new_breakout_chat_id = os.getenv(
            "TELEGRAM_NEW_BREAKOUT_CHAT_ID",
            self.new_breakout_chat_id,
        ).strip()
        self.existing_breakout_chat_id = os.getenv(
            "TELEGRAM_EXISTING_BREAKOUT_CHAT_ID",
            self.existing_breakout_chat_id,
        ).strip()
        self.five_minute_drop_chat_id = os.getenv(
            "TELEGRAM_FIVE_MINUTE_DROP_CHAT_ID",
            os.getenv("TELEGRAM_5M_DROP_CHAT_ID", self.five_minute_drop_chat_id),
        ).strip()
        self.continuous_breakout_chat_id = os.getenv(
            "TELEGRAM_CONTINUOUS_BREAKOUT_CHAT_ID",
            self.continuous_breakout_chat_id,
        ).strip()
        return self

    def require_ready(self) -> None:
        """在配置缺失时尽早报错。"""
        missing = []
        if not self.bot_token:
            missing.append("TELEGRAM_BOT_TOKEN or telegram.bot_token")
        if not self.chat_id and not (self.new_breakout_chat_id and self.existing_breakout_chat_id):
            missing.append(
                "TELEGRAM_CHAT_ID or telegram.chat_id, or both "
                "TELEGRAM_NEW_BREAKOUT_CHAT_ID/telegram.new_breakout_chat_id and "
                "TELEGRAM_EXISTING_BREAKOUT_CHAT_ID/telegram.existing_breakout_chat_id"
            )
        if missing:
            raise ValueError("Missing Telegram configuration: " + ", ".join(missing))

    def chat_id_for_breakout_status(self, status: str) -> str:
        """按突破状态选择发送频道，未单独配置时回落到默认频道。"""
        if status == "新突破":
            return self.new_breakout_chat_id or self.chat_id
        return self.existing_breakout_chat_id or self.chat_id

    def chat_id_for_five_minute_drop(self) -> str:
        """返回 5 分钟急跌监控频道，未单独配置时回落到默认频道。"""
        return self.five_minute_drop_chat_id or self.chat_id

    def chat_id_for_continuous_breakout(self) -> str:
        """返回连续突破频道，未单独配置时回落到默认频道。"""
        return self.continuous_breakout_chat_id or self.chat_id


class AppConfig(BaseModel):
    """应用完整配置。"""

    model_config = ConfigDict(extra="forbid")

    exchange: str = "okx"
    exchange_proxy_url: str = ""
    monitor_all: bool = False
    symbols: list[str] = Field(default_factory=list)
    ignored_symbols: list[str] = Field(default_factory=list)
    check_interval_minutes: int = Field(default=30, ge=1)
    breakout_summary_interval_hours: float = Field(default=0, ge=0, le=24)
    continuous_breakout_enabled: bool = False
    continuous_breakout_watch_days: int = Field(default=7, ge=1)
    five_minute_drop_enabled: bool = False
    five_minute_drop_percent: float = Field(default=5.0, gt=0, le=100)
    five_minute_drop_watch_days: int = Field(default=7, ge=1)
    five_minute_drop_check_interval_seconds: int = Field(default=15, ge=5)
    five_minute_drop_max_workers: int = Field(default=20, ge=1, le=100)
    five_minute_drop_check_interval_minutes: int = Field(default=5, ge=1)
    breakout_chart_enabled: bool = True
    breakout_chart_interval: str = "4h"
    breakout_chart_candles: int = Field(default=80, ge=1, le=1500)
    breakout_chart_include_incomplete: bool = True
    breakout_chart_max_workers: int = Field(default=6, ge=1, le=100)
    threshold_days: int = Field(default=10, ge=1)
    threshold_refresh_time: time
    timezone: str = "UTC"
    state_path: Path = Path("data/state.json")
    log_file: Path = Path("logs/monitor.log")
    log_level: str = "INFO"
    telegram: TelegramConfig

    @field_validator("symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value: Any) -> list[str]:
        """把监控币种列表规范成大写代码。"""
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("symbols must be a list")
        return [str(symbol).strip().upper() for symbol in value if str(symbol).strip()]

    @field_validator("ignored_symbols", mode="before")
    @classmethod
    def normalize_ignored_symbols(cls, value: Any) -> list[str]:
        """把忽略的合约列表规范成大写代码。"""
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("ignored_symbols must be a list")
        return [str(symbol).strip().upper() for symbol in value if str(symbol).strip()]

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """确保时区能被 zoneinfo 正确识别。"""
        ZoneInfo(value)
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """规范日志级别。"""
        level = value.strip().upper()
        valid = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if level not in valid:
            raise ValueError(f"log_level must be one of {sorted(valid)}")
        return level

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str) -> str:
        exchange = value.strip().lower()
        valid = {"okx", "binance"}
        if exchange not in valid:
            raise ValueError(f"exchange must be one of {sorted(valid)}")
        return exchange

    @field_validator("breakout_chart_interval")
    @classmethod
    def normalize_breakout_chart_interval(cls, value: str) -> str:
        interval = value.strip().lower()
        if not interval:
            raise ValueError("breakout_chart_interval must not be empty")
        return interval

    @model_validator(mode="after")
    def validate_monitor_scope(self) -> "AppConfig":
        """monitor_all 为 false 时必须提供 symbols。"""
        self.exchange_proxy_url = os.getenv("EXCHANGE_PROXY_URL", self.exchange_proxy_url).strip()
        if not self.monitor_all and not self.symbols:
            raise ValueError("symbols must not be empty when monitor_all is false")
        self.telegram.require_ready()
        if self.five_minute_drop_enabled and not self.telegram.chat_id_for_five_minute_drop():
            raise ValueError(
                "Missing Telegram configuration: TELEGRAM_FIVE_MINUTE_DROP_CHAT_ID/"
                "telegram.five_minute_drop_chat_id or TELEGRAM_CHAT_ID/telegram.chat_id"
            )
        if self.continuous_breakout_enabled and not self.telegram.chat_id_for_continuous_breakout():
            raise ValueError(
                "Missing Telegram configuration: TELEGRAM_CONTINUOUS_BREAKOUT_CHAT_ID/"
                "telegram.continuous_breakout_chat_id or TELEGRAM_CHAT_ID/telegram.chat_id"
            )
        return self

    @property
    def zoneinfo(self) -> ZoneInfo:
        """返回解析后的时区对象。"""
        return ZoneInfo(self.timezone)

    @property
    def breakout_summary_interval_minutes(self) -> float:
        """返回今日已突破概览的分钟间隔。"""
        return self.breakout_summary_interval_hours * 60


def load_config(path: str | Path) -> AppConfig:
    """读取并校验 TOML 配置。"""
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    try:
        return AppConfig.model_validate(raw)
    except ValidationError:
        raise
    except ValueError as exc:
        raise ValueError(f"Invalid config {config_path}: {exc}") from exc
