import shutil

import pytest
from pydantic import ValidationError

from binance_alert_bot.config import load_config


def test_example_config_loads_with_telegram_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    config_path = tmp_path / "config.toml"
    shutil.copyfile("config.example.toml", config_path)

    config = load_config(config_path)

    assert config.monitor_all is False
    assert config.symbols == ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    assert config.ignored_symbols == ["INTC-USDT-SWAP", "SNDK-USDT-SWAP", "CRWV-USDT-SWAP"]
    assert config.threshold_days == 10
    assert config.telegram.bot_token == "token"
    assert config.telegram.chat_id == "chat"


def test_missing_telegram_config_reports_clear_error(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
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
