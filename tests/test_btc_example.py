from binance_alert_bot.strategy import calculate_threshold


def test_btc_past_10_days_high_uses_the_max_value() -> None:
    """示例：BTC 过去 10 个已完成交易日的最高价应取其中最大值。"""
    btc_daily_highs = [
        86543.9,
        87111.0,
        86999.4,
        87555.5,
        88234.1,
        87990.0,
        88666.6,
        89123.4,
        88888.8,
        89500.0,
    ]

    assert calculate_threshold(btc_daily_highs) == 89500.0


def test_btc_threshold_only_looks_at_the_latest_10_days() -> None:
    """即使更早的数据更高，阈值也只看最近 10 天。"""
    older_high = 99999.0
    latest_10_days = [
        86543.9,
        87111.0,
        86999.4,
        87555.5,
        88234.1,
        87990.0,
        88666.6,
        89123.4,
        88888.8,
        89500.0,
    ]

    assert calculate_threshold(latest_10_days) == 89500.0


def test_btc_threshold_should_exclude_today_unfinished_candle() -> None:
    """即使今天盘中冲高，阈值也不应该把今天未收盘的日 K 算进去。"""
    previous_10_days = [
        86543.9,
        87111.0,
        86999.4,
        87555.5,
        88234.1,
        87990.0,
        88666.6,
        89123.4,
        88888.8,
        89500.0,
    ]
    today_unfinished_high = 91000.0

    assert calculate_threshold(previous_10_days) == 89500.0
    assert today_unfinished_high > calculate_threshold(previous_10_days)
