from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import httpx


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Kline:
    """一根 K 线的核心价格；未收线时 close_price 表示最新价格。"""

    open_time: datetime
    open_price: float
    close_price: float


class ExchangeClient(Protocol):
    def close(self) -> None: ...
    def get_usdt_perpetual_symbols(self) -> list[str]: ...
    def validate_symbols(self, requested_symbols: list[str]) -> list[str]: ...
    def get_daily_highs(self, symbol: str, limit: int = 15) -> list[float]: ...
    def get_current_price(self, symbol: str) -> float: ...
    def get_current_prices(self, symbols: Iterable[str]) -> dict[str, float]: ...
    def get_recent_klines(self, symbol: str, interval: str, limit: int = 2) -> list[Kline]: ...
    def get_latest_kline(self, symbol: str, interval: str) -> Kline: ...


class OkxClient:
    """对 OKX 永续合约 HTTP API 的一层轻量封装。"""

    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        base_url: str = "https://www.okx.com",
        timeout: float = 20.0,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

    def close(self) -> None:
        self.client.close()

    def get_usdt_perpetual_symbols(self) -> list[str]:
        payload = self._get_json("/api/v5/public/instruments", params={"instType": "SWAP"})
        symbols = []
        for item in payload.get("data", []):
            if item.get("state") == "live" and item.get("settleCcy") == "USDT":
                symbols.append(str(item["instId"]).upper())
        return sorted(symbols)

    def validate_symbols(self, requested_symbols: list[str]) -> list[str]:
        available = set(self.get_usdt_perpetual_symbols())
        valid = []
        for symbol in requested_symbols:
            inst_id = self._normalize_symbol(symbol)
            if inst_id in available:
                valid.append(inst_id)
            else:
                LOGGER.warning("Symbol %s is not a live OKX USDT perpetual swap; skipping", symbol)
        return valid

    def get_daily_highs(self, symbol: str, limit: int = 15) -> list[float]:
        payload = self._get_json(
            "/api/v5/market/history-candles",
            params={"instId": self._normalize_symbol(symbol), "bar": "1Dutc", "limit": str(limit + 1)},
        )
        candles = payload.get("data", [])
        completed_candles = [candle for candle in candles if self._is_okx_candle_closed(candle)][:limit]
        return [float(candle[2]) for candle in completed_candles]

    def get_current_price(self, symbol: str) -> float:
        prices = self.get_current_prices([symbol])
        normalized = self._normalize_symbol(symbol)
        if normalized not in prices:
            raise ValueError(f"No ticker returned for {normalized}")
        return prices[normalized]

    def get_current_prices(self, symbols: Iterable[str]) -> dict[str, float]:
        normalized_symbols = {self._normalize_symbol(symbol) for symbol in symbols}
        if not normalized_symbols:
            return {}

        payload = self._get_json("/api/v5/market/tickers", params={"instType": "SWAP"})
        prices: dict[str, float] = {}
        for item in payload.get("data", []):
            symbol = str(item.get("instId", "")).upper()
            if symbol in normalized_symbols:
                prices[symbol] = float(item["last"])
        return prices

    def get_recent_klines(self, symbol: str, interval: str, limit: int = 2) -> list[Kline]:
        payload = self._get_json(
            "/api/v5/market/history-candles",
            params={"instId": self._normalize_symbol(symbol), "bar": interval, "limit": str(limit + 1)},
        )
        candles = payload.get("data", [])
        completed_candles = [candle for candle in candles if self._is_okx_candle_closed(candle)][:limit]
        klines = [
            Kline(
                open_time=datetime.fromtimestamp(int(candle[0]) / 1000, tz=timezone.utc),
                open_price=float(candle[1]),
                close_price=float(candle[4]),
            )
            for candle in completed_candles
        ]
        return sorted(klines, key=lambda kline: kline.open_time)

    def get_latest_kline(self, symbol: str, interval: str) -> Kline:
        payload = self._get_json(
            "/api/v5/market/candles",
            params={"instId": self._normalize_symbol(symbol), "bar": interval, "limit": "1"},
        )
        candles = payload.get("data", [])
        if not candles:
            raise ValueError(f"No {interval} kline returned for {symbol}")
        candle = candles[0]
        return Kline(
            open_time=datetime.fromtimestamp(int(candle[0]) / 1000, tz=timezone.utc),
            open_price=float(candle[1]),
            close_price=float(candle[4]),
        )

    def _get_json(self, path: str, params: dict[str, str]) -> dict:
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.get(path, params=params)
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") != "0":
                    raise ValueError(f"OKX API error for {path}: {payload}")
                return payload
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code == 451:
                    LOGGER.error(
                        "OKX request blocked with HTTP 451 for path=%s params=%s; check region or IP restrictions",
                        path,
                        params,
                    )
                if attempt == self.max_retries or status_code not in self.RETRYABLE_STATUS_CODES:
                    raise
                self._sleep_before_retry(path, params, attempt, f"status={status_code}")
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                if attempt == self.max_retries:
                    raise
                self._sleep_before_retry(path, params, attempt, exc.__class__.__name__)

        raise RuntimeError(f"Unreachable retry loop exit for {path}")

    def _sleep_before_retry(self, path: str, params: dict[str, str], attempt: int, reason: str) -> None:
        delay = self.retry_delay_seconds * attempt
        LOGGER.warning(
            "Retrying OKX request path=%s params=%s attempt=%d/%d after %s in %.2fs",
            path,
            params,
            attempt,
            self.max_retries,
            reason,
            delay,
        )
        time.sleep(delay)

    def _normalize_symbol(self, symbol: str) -> str:
        normalized = symbol.strip().upper()
        if normalized.endswith("-SWAP"):
            return normalized
        if "-" in normalized:
            return f"{normalized}-SWAP"
        if normalized.endswith("USDT") and len(normalized) > 4:
            base = normalized[:-4]
            return f"{base}-USDT-SWAP"
        return normalized

    @staticmethod
    def _is_okx_candle_closed(candle: list[str]) -> bool:
        try:
            return str(candle[8]) == "1"
        except (IndexError, TypeError):
            return False


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
        self.client.close()

    def get_usdt_perpetual_symbols(self) -> list[str]:
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
        payload = self._get_json(
            "/fapi/v1/klines",
            params={"symbol": self._normalize_symbol(symbol), "interval": "1d", "limit": str(limit + 1)},
        )
        completed_candles = payload
        if payload and not self._is_binance_kline_closed(payload[-1]):
            completed_candles = payload[:-1]
        if len(completed_candles) > limit:
            completed_candles = completed_candles[-limit:]
        return [float(candle[2]) for candle in completed_candles]

    def get_current_price(self, symbol: str) -> float:
        prices = self.get_current_prices([symbol])
        normalized = self._normalize_symbol(symbol)
        if normalized not in prices:
            raise ValueError(f"No ticker returned for {normalized}")
        return prices[normalized]

    def get_current_prices(self, symbols: Iterable[str]) -> dict[str, float]:
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

    def get_recent_klines(self, symbol: str, interval: str, limit: int = 2) -> list[Kline]:
        payload = self._get_json(
            "/fapi/v1/klines",
            params={"symbol": self._normalize_symbol(symbol), "interval": interval, "limit": str(limit + 1)},
        )
        completed_candles = [candle for candle in payload if self._is_binance_kline_closed(candle)]
        if len(completed_candles) > limit:
            completed_candles = completed_candles[-limit:]
        return [
            Kline(
                open_time=datetime.fromtimestamp(int(candle[0]) / 1000, tz=timezone.utc),
                open_price=float(candle[1]),
                close_price=float(candle[4]),
            )
            for candle in completed_candles
        ]

    def get_latest_kline(self, symbol: str, interval: str) -> Kline:
        payload = self._get_json(
            "/fapi/v1/klines",
            params={"symbol": self._normalize_symbol(symbol), "interval": interval, "limit": "1"},
        )
        if not payload:
            raise ValueError(f"No {interval} kline returned for {symbol}")
        candle = payload[-1]
        return Kline(
            open_time=datetime.fromtimestamp(int(candle[0]) / 1000, tz=timezone.utc),
            open_price=float(candle[1]),
            close_price=float(candle[4]),
        )

    def _get_json(self, path: str, params: dict[str, str]) -> dict | list:
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
                if status_code == 451:
                    LOGGER.error(
                        "Binance request blocked with HTTP 451 for path=%s params=%s; check region or IP restrictions",
                        path,
                        params,
                    )
                if attempt == self.max_retries or status_code not in self.RETRYABLE_STATUS_CODES:
                    raise
                self._sleep_before_retry(path, params, attempt, f"status={status_code}")
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
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
        normalized = symbol.strip().upper()
        if normalized.endswith("-SWAP"):
            normalized = normalized[:-5]
        return normalized.replace("-", "")

    @staticmethod
    def _is_binance_kline_closed(candle: list[str]) -> bool:
        try:
            close_time_ms = int(candle[6])
        except (IndexError, TypeError, ValueError):
            return False
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return close_time_ms < now_ms
