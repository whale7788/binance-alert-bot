from pathlib import Path

from binance_alert_bot.config import load_config


def test_transfer_config_loads_when_enabled_with_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("ARKHAM_CLIENT_KEY", "arkham-key")
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

[transfers]
enabled = true
poll_interval_seconds = 60
source = "arkham"
ignored_assets = ["BTC", "ETH", "SOL", "WBTC", "WETH", "STETH", "CBBTC", "WSOL"]
auto_blacklist_top_n = 0
auto_blacklist_stablecoin_variants = true
auto_blacklist_wrapped_variants = true
auto_blacklist_staked_variants = true

[transfers.arkham]
client_key = ""
min_usd_value = 500000
limit = 100
flow = "all"

[[transfers.rules]]
chain = "ethereum"
asset = "USDT"
min_usd_value = 1000000
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.transfers.enabled is True
    assert config.transfers.arkham.client_key == "arkham-key"
    assert config.transfers.ignored_assets == ["BTC", "ETH", "SOL", "WBTC", "WETH", "STETH", "CBBTC", "WSOL"]
    assert config.transfers.auto_blacklist_top_n == 0
    assert config.transfers.auto_blacklist_stablecoin_variants is True
    assert config.transfers.auto_blacklist_wrapped_variants is True
    assert config.transfers.auto_blacklist_staked_variants is True
    assert len(config.transfers.rules) == 1
