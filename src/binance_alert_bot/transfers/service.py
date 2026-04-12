from __future__ import annotations

from dataclasses import dataclass

from .dedup import DeduplicationCache
from .models import ThresholdRule, TransferEvent
from .provider import TransferSource


@dataclass(frozen=True)
class MatchedTransfer:
    """命中过规则、准备进入通知链路的转账事件。"""

    event: TransferEvent
    rule: ThresholdRule


class TransferMonitorService:
    """统一编排数据源、规则匹配和去重逻辑。"""

    def __init__(
        self,
        source: TransferSource,
        rules: list[ThresholdRule],
        ignored_assets: list[str] | None = None,
        dedup_cache: DeduplicationCache | None = None,
    ) -> None:
        self.source = source
        self.rules = rules
        self.ignored_assets = {asset.upper() for asset in (ignored_assets or [])}
        self.dedup_cache = dedup_cache or DeduplicationCache()

    def poll(self) -> list[MatchedTransfer]:
        """执行一次轮询，返回所有首次命中的大额转账。"""
        matches: list[MatchedTransfer] = []
        seen_in_poll: set[str] = set()
        for event in self.source.fetch_recent_transfers():
            if event.asset.upper() in self.ignored_assets:
                continue
            if event.dedup_key in seen_in_poll:
                continue
            seen_in_poll.add(event.dedup_key)
            if self.dedup_cache.is_duplicate(event.dedup_key):
                continue
            for rule in self.rules:
                if rule.matches(event):
                    matches.append(MatchedTransfer(event=event, rule=rule))
                    break
        return matches
