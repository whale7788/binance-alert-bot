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


class AppConfig(BaseModel):
    """应用完整配置。"""

    model_config = ConfigDict(extra="forbid")

    exchange: str = "okx"
    monitor_all: bool = False
    symbols: list[str] = Field(default_factory=list)
    ignored_symbols: list[str] = Field(default_factory=list)
    check_interval_minutes: int = Field(default=30, ge=1)
    breakout_summary_interval_hours: float = Field(default=0, ge=0, le=24)
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

    @model_validator(mode="after")
    def validate_monitor_scope(self) -> "AppConfig":
        """monitor_all 为 false 时必须提供 symbols。"""
        if not self.monitor_all and not self.symbols:
            raise ValueError("symbols must not be empty when monitor_all is false")
        self.telegram.require_ready()
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
