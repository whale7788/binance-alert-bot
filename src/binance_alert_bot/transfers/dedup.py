from __future__ import annotations

import time
from collections import OrderedDict


class DeduplicationCache:
    """基于 TTL 的内存去重缓存。"""

    def __init__(self, max_size: int = 10000, ttl_seconds: int = 900) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, float] = OrderedDict()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        while self._cache:
            key, timestamp = next(iter(self._cache.items()))
            if now - timestamp > self._ttl_seconds:
                self._cache.pop(key)
            else:
                break

    def is_duplicate(self, key: str) -> bool:
        """如果 key 已存在且未过期，返回 True；否则记录并返回 False。"""
        self._evict_expired()
        if key in self._cache:
            self._cache.move_to_end(key)
            return True
        self._cache[key] = time.monotonic()
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
        return False
