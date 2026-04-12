from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from .models import TransferEvent


@dataclass(frozen=True)
class ArkhamApiConfig:
    """Arkham REST API 配置。"""

    client_key: str
    api_base: str = "https://api.arkm.com"
    min_usd_value: float = 0.0
    limit: int = 100
    flow: str = "all"


class ArkhamTransferSource:
    """模仿 crypto-transfer 项目封装的 Arkham 数据源。"""

    name = "arkham"

    def __init__(self, config: ArkhamApiConfig, timeout: float = 15.0) -> None:
        self.config = config
        self.client = httpx.Client(base_url=config.api_base.rstrip("/"), timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def fetch_recent_transfers(self) -> list[TransferEvent]:
        """拉取 Arkham 最近一批转账并标准化。"""
        params = {
            "limit": str(self.config.limit),
            "offset": "0",
            "flow": self.config.flow,
        }
        if self.config.min_usd_value > 0:
            params["usdGte"] = str(int(self.config.min_usd_value))

        response = self.client.get("/transfers", params=params, headers=self._build_headers("/transfers"))
        response.raise_for_status()
        payload = response.json()
        return [event for event in (self._parse_transfer(item) for item in payload.get("transfers", [])) if event]

    def _build_headers(self, path: str) -> dict[str, str]:
        timestamp = str(int(datetime.now().timestamp()))
        payload_hash = self.compute_payload_hash(
            f"{self.config.api_base.rstrip('/')}{path}",
            timestamp,
            self.config.client_key,
        )
        return {
            "User-Agent": "Mozilla/5.0",
            "X-Timestamp": timestamp,
            "X-Payload": payload_hash,
        }

    @staticmethod
    def compute_payload_hash(url: str, timestamp: str, client_key: str) -> str:
        """复现 crypto-transfer 里用到的 Arkham 双 SHA256 签名。"""
        pathname = urlparse(url).path
        first = hashlib.sha256(f"{pathname}:{timestamp}:{client_key}".encode()).hexdigest()
        return hashlib.sha256(f"{client_key}:{first}".encode()).hexdigest()

    def _parse_transfer(self, raw: dict[str, Any]) -> TransferEvent | None:
        try:
            tx_hash = raw.get("transactionHash") or raw.get("hash") or ""
            if not tx_hash:
                return None

            from_info = raw.get("fromAddress", {})
            to_info = raw.get("toAddress", {})
            from_address = self._extract_address(from_info)
            to_address = self._extract_address(to_info)
            return TransferEvent(
                source=self.name,
                chain=str(raw.get("chain", "unknown")),
                asset=str(raw.get("tokenSymbol", "UNKNOWN")).upper(),
                amount=float(raw.get("unitValue", 0) or 0),
                usd_value=self._parse_optional_float(raw.get("historicalUSD")),
                tx_hash=tx_hash,
                from_address=from_address,
                to_address=to_address,
                from_label=self._extract_label(from_info),
                to_label=self._extract_label(to_info),
                occurred_at=self._parse_timestamp(raw.get("blockTimestamp")),
                block_number=self._parse_optional_int(raw.get("blockNumber")),
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_address(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("address", ""))
        return "" if value is None else str(value)

    @staticmethod
    def _extract_label(value: Any) -> str:
        if not isinstance(value, dict):
            return ArkhamTransferSource._extract_address(value)

        entity = value.get("arkhamEntity")
        if isinstance(entity, dict) and entity.get("name"):
            return str(entity["name"])

        label = value.get("arkhamLabel")
        if isinstance(label, dict) and label.get("name"):
            return str(label["name"])

        address = str(value.get("address", ""))
        if len(address) < 12:
            return address
        return f"{address[:6]}...{address[-4:]}"

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return None

    @staticmethod
    def _parse_optional_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    @staticmethod
    def _parse_optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)
