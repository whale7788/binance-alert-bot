from __future__ import annotations

import os
import tomllib
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class TelegramConfig(BaseModel):
    """Telegram 通知配置，支持从配置文件和环境变量读取。"""

    bot_token: str = ""
    chat_id: str = ""

    @model_validator(mode="after")
    def apply_environment(self) -> "TelegramConfig":
        """让环境变量覆盖配置文件中的同名字段。"""
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", self.bot_token).strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", self.chat_id).strip()
        return self

    def require_ready(self) -> None:
        """在通知配置缺失时尽早报错。"""
        missing = []
        if not self.bot_token:
            missing.append("TELEGRAM_BOT_TOKEN or telegram.bot_token")
        if not self.chat_id:
            missing.append("TELEGRAM_CHAT_ID or telegram.chat_id")
        if missing:
            raise ValueError("Missing Telegram configuration: " + ", ".join(missing))


class AppConfig(BaseModel):
    """应用的完整配置，包含调度、币种、存储和通知设置。"""

    model_config = ConfigDict(extra="forbid")

    monitor_all: bool = False
    symbols: list[str] = Field(default_factory=list)
    check_interval_minutes: int = Field(default=30, ge=1)
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
        """把用户输入的币种列表规范成大写代码。"""
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("symbols must be a list")
        return [str(symbol).strip().upper() for symbol in value if str(symbol).strip()]

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """确保配置的时区能被 zoneinfo 正确识别。"""
        ZoneInfo(value)
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """接受常见日志级别，并尽早拦截拼写错误。"""
        level = value.strip().upper()
        valid = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if level not in valid:
            raise ValueError(f"log_level must be one of {sorted(valid)}")
        return level

    @model_validator(mode="after")
    def validate_monitor_scope(self) -> "AppConfig":
        """要求二选一：要么监控全部，要么提供明确白名单。"""
        if not self.monitor_all and not self.symbols:
            raise ValueError("symbols must not be empty when monitor_all is false")
        self.telegram.require_ready()
        return self

    @property
    def zoneinfo(self) -> ZoneInfo:
        """返回解析后的时区对象，供调度器和时间戳使用。"""
        return ZoneInfo(self.timezone)


def load_config(path: str | Path) -> AppConfig:
    """读取 TOML 配置文件，并返回校验后的 AppConfig。"""
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    try:
        return AppConfig.model_validate(raw)
    except ValidationError:
        raise
    except ValueError as exc:
        raise ValueError(f"Invalid config {config_path}: {exc}") from exc
