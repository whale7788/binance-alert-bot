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


class ArkhamConfig(BaseModel):
    """Arkham 数据源配置，支持环境变量覆盖。"""

    client_key: str = ""
    api_base: str = "https://api.arkm.com"
    min_usd_value: float = 0.0
    limit: int = Field(default=100, ge=1, le=500)
    flow: str = "all"

    @model_validator(mode="after")
    def apply_environment(self) -> "ArkhamConfig":
        """允许通过环境变量注入 Arkham client key。"""
        self.client_key = os.getenv("ARKHAM_CLIENT_KEY", self.client_key).strip()
        return self


class TransferRuleConfig(BaseModel):
    """一条链上大额转账筛选规则。"""

    chain: str | None = None
    asset: str | None = None
    min_amount: float | None = Field(default=None, gt=0)
    min_usd_value: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "TransferRuleConfig":
        """至少需要提供一个阈值。"""
        if self.min_amount is None and self.min_usd_value is None:
            raise ValueError("transfer rule requires min_amount or min_usd_value")
        return self


class TransfersConfig(BaseModel):
    """链上大额转账监控配置。"""

    enabled: bool = False
    poll_interval_seconds: int = Field(default=60, ge=10)
    source: str = "arkham"
    ignored_assets: list[str] = Field(default_factory=list)
    auto_blacklist_top_n: int = Field(default=50, ge=0, le=250)
    auto_blacklist_stablecoin_variants: bool = True
    auto_blacklist_wrapped_variants: bool = True
    auto_blacklist_staked_variants: bool = True
    arkham: ArkhamConfig = Field(default_factory=ArkhamConfig)
    rules: list[TransferRuleConfig] = Field(default_factory=list)

    @field_validator("ignored_assets", mode="before")
    @classmethod
    def normalize_ignored_assets(cls, value: Any) -> list[str]:
        """把忽略资产列表规范成大写代码。"""
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("transfers.ignored_assets must be a list")
        return [str(asset).strip().upper() for asset in value if str(asset).strip()]

    @model_validator(mode="after")
    def validate_enabled_config(self) -> "TransfersConfig":
        """启用 transfer monitor 时校验必要字段。"""
        if not self.enabled:
            return self
        if self.source != "arkham":
            raise ValueError("transfers.source currently only supports 'arkham'")
        if not self.arkham.client_key:
            raise ValueError("Missing Arkham configuration: ARKHAM_CLIENT_KEY or transfers.arkham.client_key")
        if not self.rules:
            raise ValueError("transfers.rules must not be empty when transfers.enabled is true")
        return self


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
    transfers: TransfersConfig = Field(default_factory=TransfersConfig)

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
