from __future__ import annotations

import logging

import httpx


LOGGER = logging.getLogger(__name__)


class OkxClient:
    """OKX 永续合约 HTTP API 轻量封装。"""

    FOUR_HOURS_PER_DAY = 6

    def __init__(self, base_url: str = "https://www.okx.com", timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        """关闭复用的 HTTP 客户端。"""
        self.client.close()

    def get_usdt_perpetual_symbols(self) -> list[str]:
        """返回当前可交易的 USDT 本位永续合约列表。"""
        payload = self._get_json("/api/v5/public/instruments", params={"instType": "SWAP"})
        symbols = []
        for item in payload.get("data", []):
            if item.get("state") == "live" and item.get("settleCcy") == "USDT":
                symbols.append(str(item["instId"]).upper())
        return sorted(symbols)

    def validate_symbols(self, requested_symbols: list[str]) -> list[str]:
        """把用户传入的币种规范成 OKX 合约 ID，并过滤掉无效合约。"""
        available = set(self.get_usdt_perpetual_symbols())
        valid = []
        for symbol in requested_symbols:
            inst_id = self._normalize_symbol(symbol)
            if inst_id in available:
                valid.append(inst_id)
            else:
                LOGGER.warning("Symbol %s is not a live OKX USDT perpetual swap; skipping", symbol)
        return valid

    def get_threshold_reference_prices(self, symbol: str, days: int = 10) -> list[float]:
        """返回过去 N 天内已完成 4 小时 K 线的收盘价序列，不包含当前未完成 K 线。"""
        bars = max(days, 1) * self.FOUR_HOURS_PER_DAY
        payload = self._get_json(
            "/api/v5/market/history-candles",
            params={"instId": self._normalize_symbol(symbol), "bar": "4H", "limit": str(bars + 1)},
        )
        candles = payload.get("data", [])
        completed_candles = candles[1 : bars + 1]
        return [float(candle[4]) for candle in completed_candles]

    def get_current_price(self, symbol: str) -> float:
        """获取某个币种的最新成交价。"""
        payload = self._get_json("/api/v5/market/ticker", params={"instId": self._normalize_symbol(symbol)})
        tickers = payload.get("data", [])
        if not tickers:
            raise ValueError(f"No ticker returned for {symbol}")
        return float(tickers[0]["last"])

    def _get_json(self, path: str, params: dict[str, str]) -> dict:
        """请求 OKX 接口，并在业务码异常时抛错。"""
        response = self.client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "0":
            raise ValueError(f"OKX API error for {path}: {payload}")
        return payload

    def _normalize_symbol(self, symbol: str) -> str:
        """把 BTCUSDT / BTC-USDT / BTC-USDT-SWAP 统一成 OKX 合约 ID。"""
        normalized = symbol.strip().upper()
        if normalized.endswith("-SWAP"):
            return normalized
        if "-" in normalized:
            return f"{normalized}-SWAP"
        if normalized.endswith("USDT") and len(normalized) > 4:
            base = normalized[:-4]
            return f"{base}-USDT-SWAP"
        return normalized
