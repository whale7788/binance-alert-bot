from binance_alert_bot.exchange import OkxClient


def test_list_current_okx_usdt_perpetual_symbols() -> None:
    """在线获取当前 OKX USDT 永续合约列表，并打印出来方便查看。"""
    client = OkxClient()
    try:
        symbols = client.get_usdt_perpetual_symbols()
    finally:
        client.close()

    print(f"\n当前 OKX USDT 永续合约数量: {len(symbols)}")
    print("当前 OKX USDT 永续合约列表:")
    for symbol in symbols:
        print(symbol)

    assert symbols
    assert "BTC-USDT-SWAP" in symbols
