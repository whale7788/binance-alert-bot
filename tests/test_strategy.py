import pytest

from binance_alert_bot.strategy import calculate_threshold, candle_change_percent, is_breakout, is_single_candle_drop


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


def test_single_candle_drop_uses_open_to_close_percent() -> None:
    assert candle_change_percent(100.0, 95.0) == -5.0
    assert is_single_candle_drop(100.0, 95.0, 5.0) is True
    assert is_single_candle_drop(100.0, 95.01, 5.0) is False


def test_candle_change_requires_positive_open() -> None:
    with pytest.raises(ValueError, match="open_price"):
        candle_change_percent(0, 95.0)
