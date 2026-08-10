from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image

from binance_alert_bot.chart import render_breakout_chart
from binance_alert_bot.exchange import Kline


def make_klines(count: int) -> list[Kline]:
    start = datetime(2026, 4, 11, tzinfo=timezone.utc)
    return [
        Kline(
            open_time=start + timedelta(hours=4 * index),
            open_price=100.0 + index,
            close_price=101.0 + index,
            high_price=102.0 + index,
            low_price=99.0 + index,
        )
        for index in range(count)
    ]


def test_render_breakout_chart_returns_valid_png_with_current_candle() -> None:
    image_bytes = render_breakout_chart(
        symbol="BTCUSDT",
        klines=make_klines(40),
        threshold=130.0,
        breakout_price=142.0,
        breakout_time=datetime(2026, 4, 18, 8, 30, tzinfo=timezone.utc),
        requested_candles=40,
    )

    with Image.open(BytesIO(image_bytes)) as image:
        assert image.format == "PNG"
        assert image.size == (1280, 760)


def test_render_breakout_chart_accepts_fewer_than_requested_candles() -> None:
    image_bytes = render_breakout_chart(
        symbol="NEWUSDT",
        klines=make_klines(3),
        threshold=102.0,
        breakout_price=105.0,
        breakout_time=datetime(2026, 4, 11, 8, 30, tzinfo=timezone.utc),
        requested_candles=40,
    )

    with Image.open(BytesIO(image_bytes)) as image:
        assert image.format == "PNG"


def test_render_breakout_chart_rejects_empty_klines() -> None:
    try:
        render_breakout_chart(
            symbol="EMPTYUSDT",
            klines=[],
            threshold=100.0,
            breakout_price=101.0,
            breakout_time=datetime(2026, 4, 11, 8, 30, tzinfo=timezone.utc),
        )
    except ValueError as exc:
        assert "No klines" in str(exc)
    else:
        raise AssertionError("Expected empty K-line input to fail")
