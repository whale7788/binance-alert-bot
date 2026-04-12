from binance_alert_bot.transfers.blacklist import build_ignored_assets


def test_build_ignored_assets_merges_all_sources() -> None:
    ignored = build_ignored_assets(
        manual_ignored_assets=["BTC", "ETH"],
        top_market_cap_symbols={"SOL", "DOGE"},
        include_stablecoin_variants=True,
        include_wrapped_variants=True,
        include_staked_variants=True,
    )

    assert "BTC" in ignored
    assert "DOGE" in ignored
    assert "USDT" in ignored
    assert "WETH" in ignored
    assert "STETH" in ignored
