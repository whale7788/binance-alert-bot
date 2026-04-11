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
