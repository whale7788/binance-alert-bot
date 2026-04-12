from __future__ import annotations

from typing import Protocol

from .models import TransferEvent


class TransferSource(Protocol):
    """统一的数据源接口，方便后续扩展 Arkham、Etherscan、Tronscan 等实现。"""

    name: str

    def fetch_recent_transfers(self) -> list[TransferEvent]:
        """获取最近一批转账事件。"""
        ...
