from __future__ import annotations

import httpx


WRAPPED_VARIANTS = {
    "WBTC",
    "WETH",
    "WSOL",
    "CBBTC",
    "CBETH",
    "WBNB",
    "WMATIC",
    "WAVAX",
    "WXRP",
}

STABLECOIN_VARIANTS = {
    "USDT",
    "USDC",
    "USDE",
    "FDUSD",
    "DAI",
    "TUSD",
    "USDD",
    "PYUSD",
    "BUSD",
    "FRAX",
    "LUSD",
    "USD0",
    "USD1",
    "SUSDS",
    "USDS",
    "GHO",
    "RLUSD",
    "USDY",
}

STAKED_VARIANTS = {
    "STETH",
    "WSTETH",
    "RETH",
    "WEETH",
    "EETH",
    "METH",
    "SFRXETH",
    "OSETH",
}


class CoinGeckoMarketCapBlacklist:
    """从 CoinGecko 获取市值前 N 名币种，作为自动黑名单。"""

    def __init__(self, api_base: str = "https://api.coingecko.com/api/v3", timeout: float = 15.0) -> None:
        self.client = httpx.Client(base_url=api_base.rstrip("/"), timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def fetch_top_symbols(self, top_n: int) -> set[str]:
        """返回市值前 N 名的 symbol 集合。"""
        if top_n <= 0:
            return set()
        response = self.client.get(
            "/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": str(min(top_n, 250)),
                "page": "1",
                "sparkline": "false",
            },
        )
        response.raise_for_status()
        payload = response.json()
        return {str(item.get("symbol", "")).strip().upper() for item in payload if item.get("symbol")}


def build_ignored_assets(
    manual_ignored_assets: list[str],
    top_market_cap_symbols: set[str],
    include_stablecoin_variants: bool,
    include_wrapped_variants: bool,
    include_staked_variants: bool,
) -> list[str]:
    """合并手动黑名单、主流币黑名单、wrapped/staked 自动过滤。"""
    ignored = {asset.upper() for asset in manual_ignored_assets}
    ignored.update(top_market_cap_symbols)
    if include_stablecoin_variants:
        ignored.update(STABLECOIN_VARIANTS)
    if include_wrapped_variants:
        ignored.update(WRAPPED_VARIANTS)
    if include_staked_variants:
        ignored.update(STAKED_VARIANTS)
    return sorted(ignored)
