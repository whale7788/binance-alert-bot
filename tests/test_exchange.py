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


def test_get_daily_highs_uses_utc_daily_candles() -> None:
    """日线阈值要按 UTC+0 计算，而不是 OKX 默认的 UTC+8 日线。"""
    client = OkxClient()
    captured: dict[str, dict[str, str]] = {}

    def fake_get_json(path, params):
        captured["call"] = {"path": path, **params}
        return {"code": "0", "data": []}

    client._get_json = fake_get_json  # type: ignore[method-assign]

    client.get_daily_highs("BTC-USDT-SWAP", limit=10)

    assert captured["call"]["path"] == "/api/v5/market/history-candles"
    assert captured["call"]["bar"] == "1Dutc"
    assert captured["call"]["limit"] == "11"
