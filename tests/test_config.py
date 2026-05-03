import shutil

import pytest
from pydantic import ValidationError

from binance_alert_bot.config import load_config


def test_example_config_loads_with_telegram_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.delenv("TELEGRAM_NEW_BREAKOUT_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_EXISTING_BREAKOUT_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_FIVE_MINUTE_DROP_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_5M_DROP_CHAT_ID", raising=False)
    config_path = tmp_path / "config.toml"
    shutil.copyfile("config.example.toml", config_path)

    config = load_config(config_path)

    assert config.exchange == "okx"
    assert config.monitor_all is False
    assert config.symbols == ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    assert config.ignored_symbols == ["INTC-USDT-SWAP", "SNDK-USDT-SWAP", "CRWV-USDT-SWAP"]
    assert config.threshold_days == 10
    assert config.telegram.bot_token == "token"
    assert config.telegram.chat_id == "chat"
    assert config.telegram.new_breakout_chat_id == ""
    assert config.telegram.existing_breakout_chat_id == ""
    assert config.telegram.five_minute_drop_chat_id == ""
    assert config.five_minute_drop_enabled is False
    assert config.five_minute_drop_percent == 5.0
    assert config.five_minute_drop_watch_days == 7
    assert config.five_minute_drop_check_interval_seconds == 15
    assert config.five_minute_drop_max_workers == 20
    assert config.five_minute_drop_check_interval_minutes == 5


def test_split_breakout_chat_ids_can_replace_default_chat_id(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_NEW_BREAKOUT_CHAT_ID", "new-chat")
    monkeypatch.setenv("TELEGRAM_EXISTING_BREAKOUT_CHAT_ID", "existing-chat")
    monkeypatch.delenv("TELEGRAM_FIVE_MINUTE_DROP_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_5M_DROP_CHAT_ID", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
monitor_all = false
symbols = ["BTC-USDT-SWAP"]
check_interval_minutes = 15
threshold_days = 10
threshold_refresh_time = "00:05"
timezone = "UTC"
state_path = "data/state.json"
log_file = "logs/monitor.log"
log_level = "INFO"

[telegram]
bot_token = ""
chat_id = ""
new_breakout_chat_id = ""
existing_breakout_chat_id = ""
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.telegram.bot_token == "token"
    assert config.telegram.chat_id == ""
    assert config.telegram.new_breakout_chat_id == "new-chat"
    assert config.telegram.existing_breakout_chat_id == "existing-chat"


def test_breakout_summary_interval_accepts_half_hour(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.delenv("TELEGRAM_FIVE_MINUTE_DROP_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_5M_DROP_CHAT_ID", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
monitor_all = false
symbols = ["BTC-USDT-SWAP"]
check_interval_minutes = 15
breakout_summary_interval_hours = 0.5
threshold_days = 10
threshold_refresh_time = "00:05"
timezone = "UTC"
state_path = "data/state.json"
log_file = "logs/monitor.log"
log_level = "INFO"

[telegram]
bot_token = ""
chat_id = ""
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.breakout_summary_interval_hours == 0.5
    assert config.breakout_summary_interval_minutes == 30


def test_missing_telegram_config_reports_clear_error(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_NEW_BREAKOUT_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_EXISTING_BREAKOUT_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_FIVE_MINUTE_DROP_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_5M_DROP_CHAT_ID", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
monitor_all = false
symbols = ["BTC-USDT-SWAP"]
check_interval_minutes = 15
threshold_days = 10
threshold_refresh_time = "00:05"
timezone = "UTC"
state_path = "data/state.json"
log_file = "logs/monitor.log"
log_level = "INFO"

[telegram]
bot_token = ""
chat_id = ""
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="Missing Telegram configuration"):
        load_config(config_path)


def test_exchange_must_be_supported(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.delenv("TELEGRAM_NEW_BREAKOUT_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_EXISTING_BREAKOUT_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_FIVE_MINUTE_DROP_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_5M_DROP_CHAT_ID", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
exchange = "bybit"
monitor_all = false
symbols = ["BTC-USDT-SWAP"]
check_interval_minutes = 15
threshold_days = 10
threshold_refresh_time = "00:05"
timezone = "UTC"
state_path = "data/state.json"
log_file = "logs/monitor.log"
log_level = "INFO"

[telegram]
bot_token = ""
chat_id = ""
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="exchange must be one of"):
        load_config(config_path)


def test_five_minute_drop_chat_id_uses_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_NEW_BREAKOUT_CHAT_ID", "new-chat")
    monkeypatch.setenv("TELEGRAM_EXISTING_BREAKOUT_CHAT_ID", "existing-chat")
    monkeypatch.setenv("TELEGRAM_FIVE_MINUTE_DROP_CHAT_ID", "drop-chat")
    monkeypatch.delenv("TELEGRAM_5M_DROP_CHAT_ID", raising=False)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
monitor_all = false
symbols = ["BTC-USDT-SWAP"]
check_interval_minutes = 15
five_minute_drop_enabled = true
threshold_days = 10
threshold_refresh_time = "00:05"
timezone = "UTC"
state_path = "data/state.json"
log_file = "logs/monitor.log"
log_level = "INFO"

[telegram]
bot_token = ""
chat_id = ""
new_breakout_chat_id = ""
existing_breakout_chat_id = ""
five_minute_drop_chat_id = ""
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.five_minute_drop_enabled is True
    assert config.telegram.five_minute_drop_chat_id == "drop-chat"
