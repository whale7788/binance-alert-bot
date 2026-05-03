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


def candle_change_percent(open_price: float, close_price: float) -> float:
    """返回单根 K 线从开盘到收盘的涨跌幅。"""
    if open_price <= 0:
        raise ValueError("open_price must be greater than 0")
    return ((close_price - open_price) / open_price) * 100


def is_single_candle_drop(open_price: float, close_price: float, threshold_percent: float) -> bool:
    """判断单根 K 线跌幅是否达到阈值。"""
    return candle_change_percent(open_price, close_price) <= -abs(threshold_percent)
