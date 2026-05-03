# Binance Alert Bot

一个本地运行的 Python 监控程序，用于检查 OKX USDT 永续合约白名单币种是否突破当日固定的近 10 根已完成日 K 高点，并通过 Telegram 发送提醒。

## 功能

- 每天固定时间刷新一次每个币种近 10 根已完成日 K 的最高价作为 `threshold`
- 按固定周期检查最新成交价是否 `> threshold`
- 同一币种同一天最多通知一次
- 可把最近 7 天内再次突破的币额外推送到“连续突破”频道
- 已突破币种会进入 7 天急跌监控池，可单独监控当前 5 分钟 K 线盘中跌幅
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
ignored_symbols = ["INTC-USDT-SWAP", "SNDK-USDT-SWAP", "CRWV-USDT-SWAP"]
check_interval_minutes = 15
breakout_summary_interval_hours = 4
continuous_breakout_enabled = true
continuous_breakout_watch_days = 7
five_minute_drop_enabled = true
five_minute_drop_percent = 5
five_minute_drop_watch_days = 7
five_minute_drop_check_interval_seconds = 15
five_minute_drop_max_workers = 20
threshold_days = 10
threshold_refresh_time = "00:05"
timezone = "UTC"
```

`breakout_summary_interval_hours` 支持小数，例如 `0.5` 表示每半小时推送一次“今日已突破”概览。

`continuous_breakout_enabled = true` 后，原来的“新突破”照常发送；如果某币最近 `continuous_breakout_watch_days` 天内已经突破过，并且不是同一个 UTC 交易日，本次再次突破会额外推送到“连续突破”频道。

`five_minute_drop_enabled = true` 后，程序会把已突破币种放入急跌监控池；如果启动时状态文件里已经有“今日已突破”的币，也会自动补进监控池。某币最近 `five_minute_drop_watch_days` 天内没有再次突破，就会移出。急跌预警不等收线，按 `five_minute_drop_check_interval_seconds` 秒级轮询当前 5 分钟 K 线，并用 `five_minute_drop_max_workers` 并发行情请求。例如 `five_minute_drop_percent = 5` 表示当前 5m K 线的开盘价到实时价 `<= -5%` 就提醒。同一根 5m K 线只提醒一次。

Telegram 配置推荐放到环境变量：

```powershell
$env:TELEGRAM_BOT_TOKEN = "你的 bot token"
$env:TELEGRAM_CHAT_ID = "你的 chat id"
```

如果要同一个 bot 分两个频道推送突破消息，可以额外设置：

```powershell
$env:TELEGRAM_NEW_BREAKOUT_CHAT_ID = "新突破频道 chat id"
$env:TELEGRAM_EXISTING_BREAKOUT_CHAT_ID = "今日已突破频道 chat id"
$env:TELEGRAM_FIVE_MINUTE_DROP_CHAT_ID = "5分钟急跌频道 chat id"
$env:TELEGRAM_CONTINUOUS_BREAKOUT_CHAT_ID = "连续突破频道 chat id"
```

也可以填到 `config.toml` 的 `[telegram]` 中：`new_breakout_chat_id` 负责“新突破”，`existing_breakout_chat_id` 负责“今日已突破”，`five_minute_drop_chat_id` 负责“5分钟急跌”，`continuous_breakout_chat_id` 负责“连续突破”。未单独配置时会回落到 `chat_id`，但不要提交真实密钥。

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
  },
  "breakoutWatchlist": {
    "BTC-USDT-SWAP": {
      "firstBreakoutTime": "2026-04-11T08:30:00+00:00",
      "lastBreakoutTime": "2026-04-11T08:30:00+00:00",
      "lastDropAlertKlineOpenTime": null
    }
  }
}
```
