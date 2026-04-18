import httpx

from binance_alert_bot.exchange import BinanceFuturesClient, OkxClient


def test_get_daily_highs_skips_today_unfinished_candle() -> None:
    """Binance klines 最后一根日 K 视为今天，计算阈值时应跳过它。"""
    client = BinanceFuturesClient()
    payload = [
        ["d1", "0", "101.0", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
        ["d2", "0", "102.0", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
        ["today", "0", "999.0", "0", "0", "0", "0", "0", "0", "0", "0", "0"],
    ]

    client._get_json = lambda path, params: payload  # type: ignore[method-assign]

    highs = client.get_daily_highs("BTCUSDT", limit=2)

    assert highs == [101.0, 102.0]


def test_get_daily_highs_uses_binance_daily_klines() -> None:
    client = BinanceFuturesClient()
    captured: dict[str, dict[str, str]] = {}

    def fake_get_json(path, params):
        captured["call"] = {"path": path, **params}
        return []

    client._get_json = fake_get_json  # type: ignore[method-assign]

    client.get_daily_highs("BTC-USDT-SWAP", limit=10)

    assert captured["call"]["path"] == "/fapi/v1/klines"
    assert captured["call"]["symbol"] == "BTCUSDT"
    assert captured["call"]["interval"] == "1d"
    assert captured["call"]["limit"] == "11"


def test_get_current_prices_uses_bulk_ticker_endpoint_and_filters_symbols() -> None:
    client = BinanceFuturesClient()
    captured: dict[str, dict[str, str]] = {}

    def fake_get_json(path, params):
        captured["call"] = {"path": path, **params}
        return [
            {"symbol": "BTCUSDT", "price": "100000.0"},
            {"symbol": "ETHUSDT", "price": "2000.0"},
        ]

    client._get_json = fake_get_json  # type: ignore[method-assign]

    prices = client.get_current_prices(["BTC-USDT-SWAP"])

    assert captured["call"]["path"] == "/fapi/v1/ticker/price"
    assert prices == {"BTCUSDT": 100000.0}


def test_get_json_retries_on_429_then_succeeds(monkeypatch) -> None:
    client = BinanceFuturesClient(max_retries=3, retry_delay_seconds=0.01)
    calls = {"count": 0}
    sleeps: list[float] = []

    def fake_get(path, params):
        calls["count"] += 1
        request = httpx.Request("GET", f"https://fapi.binance.com{path}", params=params)
        if calls["count"] == 1:
            return httpx.Response(429, request=request, json={"code": -1003, "msg": "Too many requests"})
        return httpx.Response(200, request=request, json={"symbol": "BTCUSDT", "price": "100000.0"})

    monkeypatch.setattr(client.client, "get", fake_get)
    monkeypatch.setattr("binance_alert_bot.exchange.time.sleep", sleeps.append)

    payload = client._get_json("/fapi/v1/ticker/price", params={"symbol": "BTCUSDT"})

    assert calls["count"] == 2
    assert sleeps == [0.01]
    assert payload == {"symbol": "BTCUSDT", "price": "100000.0"}


def test_get_json_does_not_retry_on_non_retryable_status(monkeypatch) -> None:
    client = BinanceFuturesClient(max_retries=3, retry_delay_seconds=0.01)
    calls = {"count": 0}
    sleeps: list[float] = []

    def fake_get(path, params):
        calls["count"] += 1
        request = httpx.Request("GET", f"https://fapi.binance.com{path}", params=params)
        return httpx.Response(400, request=request, json={"code": -1121, "msg": "Invalid symbol."})

    monkeypatch.setattr(client.client, "get", fake_get)
    monkeypatch.setattr("binance_alert_bot.exchange.time.sleep", sleeps.append)

    try:
        client._get_json("/fapi/v1/ticker/price", params={"symbol": "BADSYMBOL"})
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("Expected HTTPStatusError")

    assert calls["count"] == 1
    assert sleeps == []


def test_okx_get_daily_highs_skips_today_unfinished_candle() -> None:
    client = OkxClient()
    payload = {
        "code": "0",
        "data": [
            ["today", "0", "999.0", "0", "0", "0", "0", "0", "0"],
            ["d1", "0", "101.0", "0", "0", "0", "0", "0", "1"],
            ["d2", "0", "102.0", "0", "0", "0", "0", "0", "1"],
        ],
    }

    client._get_json = lambda path, params: payload  # type: ignore[method-assign]

    highs = client.get_daily_highs("BTC-USDT-SWAP", limit=2)

    assert highs == [101.0, 102.0]


def test_okx_get_current_prices_uses_bulk_ticker_endpoint_and_filters_symbols() -> None:
    client = OkxClient()
    captured: dict[str, dict[str, str]] = {}

    def fake_get_json(path, params):
        captured["call"] = {"path": path, **params}
        return {
            "code": "0",
            "data": [
                {"instId": "BTC-USDT-SWAP", "last": "100000.0"},
                {"instId": "ETH-USDT-SWAP", "last": "2000.0"},
            ],
        }

    client._get_json = fake_get_json  # type: ignore[method-assign]

    prices = client.get_current_prices(["BTC-USDT-SWAP"])

    assert captured["call"]["path"] == "/api/v5/market/tickers"
    assert prices == {"BTC-USDT-SWAP": 100000.0}
