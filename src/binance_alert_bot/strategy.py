from __future__ import annotations


def calculate_threshold(highs: list[float]) -> float:
    """取传入这段已完成日 K 最高价中的最大值，作为当天阈值。"""
    if not highs:
        raise ValueError("expected at least 1 daily high, got 0")
    return max(highs)


def is_breakout(current_price: float, threshold: float) -> bool:
    """只有当前价格严格大于阈值，才算突破。"""
    return current_price > threshold


def breakout_delta(current_price: float, threshold: float) -> tuple[float, float]:
    """返回价格超出阈值的绝对值和百分比。"""
    delta = current_price - threshold
    percent = (delta / threshold) * 100 if threshold else 0.0
    return delta, percent
