import pytest

from binance_alert_bot.strategy import calculate_threshold, is_breakout


def test_calculate_threshold_uses_max_high_from_input_values() -> None:
    highs = [1.0, 99.0, 3.0, 4.0]

    assert calculate_threshold(highs) == 99.0


def test_calculate_threshold_requires_non_empty_values() -> None:
    with pytest.raises(ValueError, match="expected at least 1"):
        calculate_threshold([])


def test_is_breakout_requires_strictly_greater_price() -> None:
    assert is_breakout(101.0, 100.0) is True
    assert is_breakout(100.0, 100.0) is False
    assert is_breakout(99.99, 100.0) is False
