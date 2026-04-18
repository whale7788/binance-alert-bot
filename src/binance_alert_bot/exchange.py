from __future__ import annotations

import logging
import time
from collections.abc import Iterable

import httpx


LOGGER = logging.getLogger(__name__)


class BinanceFuturesClient:
    """对 Binance U 本位永续合约 HTTP API 的轻量封装。"""

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        base_url: str = "https://fapi.binance.com",
        timeout: float = 20.0,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    def close(self) -> None:
        """关闭复用的 HTTP 客户端。"""
        self.client.close()

    def get_usdt_perpetual_symbols(self) -> list[str]:
        """返回当前可交易的 USDT 本位永续合约列表。"""
        payload = self._get_json("/fapi/v1/exchangeInfo", params={})
        symbols = []
        for item in payload.get("symbols", []):
            if (
                item.get("status") == "TRADING"
                and item.get("contractType") == "PERPETUAL"
                and item.get("quoteAsset") == "USDT"
            ):
                symbols.append(str(item["symbol"]).upper())
        return sorted(symbols)

    def validate_symbols(self, requested_symbols: list[str]) -> list[str]:
        """把用户传入的币种规范成 Binance 合约代码，并过滤掉无效合约。"""
        available = set(self.get_usdt_perpetual_symbols())
        valid = []
        for symbol in requested_symbols:
            inst_id = self._normalize_symbol(symbol)
            if inst_id in available:
                valid.append(inst_id)
            else:
                LOGGER.warning("Symbol %s is not a live Binance USDT perpetual future; skipping", symbol)
        return valid

    def get_daily_highs(self, symbol: str, limit: int = 15) -> list[float]:
        """获取最近已完成日 K 的最高价序列，不包含今天这根未收盘日线。"""
        payload = self._get_json(
            "/fapi/v1/klines",
            params={"symbol": self._normalize_symbol(symbol), "interval": "1d", "limit": str(limit + 1)},
        )
        completed_candles = payload[:-1]
        if len(completed_candles) > limit:
            completed_candles = completed_candles[-limit:]
        return [float(candle[2]) for candle in completed_candles]

    def get_current_price(self, symbol: str) -> float:
        """获取某个币种的最新成交价。"""
        prices = self.get_current_prices([symbol])
        normalized = self._normalize_symbol(symbol)
        if normalized not in prices:
            raise ValueError(f"No ticker returned for {normalized}")
        return prices[normalized]

    def get_current_prices(self, symbols: Iterable[str]) -> dict[str, float]:
        """批量获取多个币种的最新成交价。"""
        normalized_symbols = {self._normalize_symbol(symbol) for symbol in symbols}
        if not normalized_symbols:
            return {}

        payload = self._get_json("/fapi/v1/ticker/price", params={})
        prices: dict[str, float] = {}
        for item in payload:
            symbol = str(item.get("symbol", "")).upper()
            if symbol in normalized_symbols:
                prices[symbol] = float(item["price"])
        return prices

    def _get_json(self, path: str, params: dict[str, str]) -> dict | list:
        """请求 Binance 接口，并在业务错误时抛错。"""
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.get(path, params=params)
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("code") not in (None, 200):
                    raise ValueError(f"Binance API error for {path}: {payload}")
                return payload
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if attempt == self.max_retries or status_code not in self.RETRYABLE_STATUS_CODES:
                    raise
                self._sleep_before_retry(path, params, attempt, f"status={status_code}")
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                if attempt == self.max_retries:
                    raise
                self._sleep_before_retry(path, params, attempt, exc.__class__.__name__)

        raise RuntimeError(f"Unreachable retry loop exit for {path}")

    def _sleep_before_retry(self, path: str, params: dict[str, str], attempt: int, reason: str) -> None:
        delay = self.retry_delay_seconds * attempt
        LOGGER.warning(
            "Retrying Binance request path=%s params=%s attempt=%d/%d after %s in %.2fs",
            path,
            params,
            attempt,
            self.max_retries,
            reason,
            delay,
        )
        time.sleep(delay)

    def _normalize_symbol(self, symbol: str) -> str:
        """把 BTC-USDT-SWAP / BTC-USDT / BTCUSDT 统一成 Binance 合约代码。"""
        normalized = symbol.strip().upper()
        if normalized.endswith("-SWAP"):
            normalized = normalized[:-5]
        return normalized.replace("-", "")


OkxClient = BinanceFuturesClient
