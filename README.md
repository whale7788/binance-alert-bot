# Binance Alert Bot

一个本地运行的 Python 监控程序，用于检查 OKX USDT 永续合约白名单币种是否突破当日固定的近 10 根已完成日 K 高点，并通过 Telegram 发送提醒。

## 功能

- 每天固定时间刷新一次每个币种近 10 根已完成日 K 的最高价作为 `threshold`
- 按固定周期检查最新成交价是否 `> threshold`
- 同一币种同一天最多通知一次
- 状态持久化到本地 JSON，程序重启后不会丢失当日已通知状态
- 日志同时输出到控制台和文件

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## 配置

复制示例配置：

```powershell
Copy-Item config.example.toml config.toml
```

编辑 `config.toml`：

```toml
monitor_all = false
symbols = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
check_interval_minutes = 15
breakout_summary_interval_hours = 4
threshold_days = 10
threshold_refresh_time = "00:05"
timezone = "UTC"
```

Telegram 配置推荐放到环境变量：

```powershell
$env:TELEGRAM_BOT_TOKEN = "你的 bot token"
$env:TELEGRAM_CHAT_ID = "你的 chat id"
```

也可以填到 `config.toml` 的 `[telegram]` 中，但不要提交真实密钥。

## 运行

```powershell
python -m binance_alert_bot --config config.toml
```

或者使用安装后的命令：

```powershell
binance-alert-bot --config config.toml
```

## 测试

```powershell
pytest
```

## 链上大额转账扩展

项目里已经预留了一套可扩展的链上大额转账骨架，在这些文件下：

- `src/binance_alert_bot/transfers/models.py`
- `src/binance_alert_bot/transfers/provider.py`
- `src/binance_alert_bot/transfers/arkham.py`
- `src/binance_alert_bot/transfers/service.py`
- `src/binance_alert_bot/transfers/dedup.py`

这套结构是参考 `crypto-transfer` 的思路做的，但拆成了更容易替换数据源的接口层：

- `TransferSource`：统一数据源接口
- `TransferEvent`：统一转账事件模型
- `ThresholdRule`：统一阈值规则
- `DeduplicationCache`：TTL 去重
- `TransferMonitorService`：负责轮询、规则匹配和去重

后面如果要接：

- Arkham
- Etherscan
- TronGrid
- 自己的 RPC / WebSocket

都可以继续往 `transfers/` 下面加 provider，而不用改通知主流程。

如果要单独运行链上大额转账监控，可以新建配置：

```toml
[transfers]
enabled = true
poll_interval_seconds = 60
source = "arkham"
ignored_assets = ["BTC", "ETH", "SOL", "WBTC", "WETH", "STETH", "CBBTC", "WSOL"]
only_to_exchanges = false
exchange_labels = ["BINANCE", "OKX", "BYBIT", "COINBASE", "KRAKEN", "KUCOIN", "BITGET", "GATE", "HTX", "MEXC"]
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
min_usd_value = 1000000
```

然后使用独立入口：

```powershell
binance-transfer-bot --config config.toml
```

## 状态文件

默认状态文件为 `data/state.json`，结构大致如下：

```json
{
  "date": "2026-04-11",
  "lastThresholdRefreshTime": "2026-04-11T00:05:00+00:00",
  "symbols": {
    "BTC-USDT-SWAP": {
      "threshold": 123456.78,
      "notified": false,
      "lastNotifyTime": null
    }
  }
}
```
