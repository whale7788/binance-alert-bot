from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TransferEvent:
    """标准化后的链上转账事件。"""

    source: str
    chain: str
    asset: str
    amount: float
    usd_value: float | None
    tx_hash: str
    from_address: str
    to_address: str
    from_label: str
    to_label: str
    occurred_at: datetime | None = None
    block_number: int | None = None

    @property
    def dedup_key(self) -> str:
        """用于去重和通知聚合的稳定键。"""
        return "|".join(
            [
                self.source.lower(),
                self.chain.lower(),
                self.tx_hash.lower(),
                self.asset.upper(),
                self.from_address.lower(),
                self.to_address.lower(),
                f"{self.amount:.2f}",
                "" if self.usd_value is None else f"{self.usd_value:.0f}",
            ]
        )


@dataclass(frozen=True)
class ThresholdRule:
    """描述某条链或某种资产的大额阈值。"""

    chain: str | None = None
    asset: str | None = None
    min_amount: float | None = None
    min_usd_value: float | None = None

    def matches(self, event: TransferEvent) -> bool:
        """判断某个事件是否命中这条规则。"""
        if self.chain and event.chain.lower() != self.chain.lower():
            return False
        if self.asset and event.asset.upper() != self.asset.upper():
            return False
        if self.min_amount is not None and event.amount < self.min_amount:
            return False
        if self.min_usd_value is not None:
            if event.usd_value is None or event.usd_value < self.min_usd_value:
                return False
        return True
