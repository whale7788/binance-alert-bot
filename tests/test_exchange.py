from binance_alert_bot.exchange import OkxClient


def test_get_daily_highs_skips_today_unfinished_candle() -> None:
    """交易所返回的第一根日 K 视为今天，计算阈值时应跳过它。"""
    client = OkxClient()
    payload = {
        "code": "0",
        "data": [
            ["today", "0", "999.0", "0", "0", "0", "0", "0", "0"],
            ["d1", "0", "101.0", "0", "0", "0", "0", "0", "1"],
            ["d2", "0", "102.0", "0", "0", "0", "0", "0", "1"],
            ["d3", "0", "103.0", "0", "0", "0", "0", "0", "1"],
        ],
    }

    client._get_json = lambda path, params: payload  # type: ignore[method-assign]

    highs = client.get_daily_highs("BTC-USDT-SWAP", limit=2)

    assert highs == [101.0, 102.0]
