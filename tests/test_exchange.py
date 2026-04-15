from binance_alert_bot.exchange import OkxClient


def test_get_threshold_reference_prices_skips_current_unfinished_4h_candle() -> None:
    client = OkxClient()
    payload = {
        "code": "0",
        "data": [
            ["current", "0", "999.0", "0", "199.0", "0", "0", "0", "0"],
            ["c1", "0", "0", "0", "101.0", "0", "0", "0", "1"],
            ["c2", "0", "0", "0", "102.0", "0", "0", "0", "1"],
            ["c3", "0", "0", "0", "103.0", "0", "0", "0", "1"],
        ],
    }

    client._get_json = lambda path, params: payload  # type: ignore[method-assign]

    closes = client.get_threshold_reference_prices("BTC-USDT-SWAP", days=1)

    assert closes == [101.0, 102.0, 103.0]
    assert 199.0 not in closes


def test_get_threshold_reference_prices_uses_4h_close_prices_for_requested_days() -> None:
    client = OkxClient()
    captured: dict[str, dict[str, str]] = {}

    def fake_get_json(path, params):
        captured["call"] = {"path": path, **params}
        return {
            "code": "0",
            "data": [
                ["current", "0", "0", "0", "199.0", "0", "0", "0", "0"],
                ["c1", "0", "0", "0", "101.0", "0", "0", "0", "1"],
                ["c2", "0", "0", "0", "102.0", "0", "0", "0", "1"],
            ],
        }

    client._get_json = fake_get_json  # type: ignore[method-assign]

    closes = client.get_threshold_reference_prices("BTC-USDT-SWAP", days=1)

    assert captured["call"]["path"] == "/api/v5/market/history-candles"
    assert captured["call"]["bar"] == "4H"
    assert captured["call"]["limit"] == "7"
    assert closes == [101.0, 102.0]
