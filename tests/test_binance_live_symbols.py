from binance_alert_bot.exchange import BinanceFuturesClient


def test_list_current_binance_usdt_perpetual_symbols() -> None:
    """在线获取当前 Binance U 本位永续合约列表，并打印出来方便查看。"""
    client = BinanceFuturesClient()
    try:
        symbols = client.get_usdt_perpetual_symbols()
    finally:
        client.close()

    print(f"\n当前 Binance USDT 永续合约数量: {len(symbols)}")
    print("当前 Binance USDT 永续合约列表:")
    for symbol in symbols:
        print(symbol)

    assert symbols
    assert "BTCUSDT" in symbols
