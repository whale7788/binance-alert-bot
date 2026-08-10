from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from math import isfinite
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

from .exchange import Kline


CHART_WIDTH = 1280
CHART_HEIGHT = 760
PLOT_LEFT = 90
PLOT_TOP = 105
PLOT_RIGHT = CHART_WIDTH - 70
PLOT_BOTTOM = CHART_HEIGHT - 105

BACKGROUND = "#0f172a"
PLOT_BACKGROUND = "#111827"
GRID = "#334155"
TEXT = "#e2e8f0"
MUTED_TEXT = "#94a3b8"
BULL = "#22c55e"
BEAR = "#ef4444"
THRESHOLD = "#38bdf8"
BREAKOUT = "#facc15"
CURRENT_CANDLE = "#f8fafc"


def render_breakout_chart(
    symbol: str,
    klines: Sequence[Kline],
    threshold: float,
    breakout_price: float,
    breakout_time: datetime,
    requested_candles: int = 80,
) -> bytes:
    """Render a single-symbol OHLC chart and return it as PNG bytes."""
    if not klines:
        raise ValueError(f"No klines available for {symbol}")
    if not isfinite(threshold) or not isfinite(breakout_price):
        raise ValueError(f"Invalid threshold or breakout price for {symbol}")

    candles = sorted(klines, key=lambda kline: kline.open_time)
    ohlc = [_ohlc_values(kline) for kline in candles]
    values = [value for candle in ohlc for value in candle[1:]] + [threshold, breakout_price]
    minimum = min(values)
    maximum = max(values)
    value_range = maximum - minimum
    padding = max(value_range * 0.06, abs(maximum) * 0.001, 1e-8)
    chart_min = minimum - padding
    chart_max = maximum + padding

    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    draw.rounded_rectangle(
        (35, 30, CHART_WIDTH - 35, CHART_HEIGHT - 30),
        radius=16,
        fill=PLOT_BACKGROUND,
        outline="#1e293b",
        width=2,
    )
    draw.text((PLOT_LEFT, 48), f"{symbol}  |  4H Candles", fill=TEXT, font=font)
    time_text = _format_time(breakout_time)
    subtitle = (
        f"{len(candles)}/{requested_candles} candles incl. current  |  "
        f"breakout {time_text}"
    )
    draw.text((PLOT_LEFT, 70), subtitle, fill=MUTED_TEXT, font=font)

    _draw_grid(draw, chart_min, chart_max)

    spacing = (PLOT_RIGHT - PLOT_LEFT) / max(len(ohlc) - 1, 1)
    body_width = max(4, min(16, int(spacing * 0.55)))

    def x_for(index: int) -> int:
        return round(PLOT_LEFT + index * spacing)

    def y_for(price: float) -> int:
        ratio = (chart_max - price) / (chart_max - chart_min)
        return round(PLOT_TOP + ratio * (PLOT_BOTTOM - PLOT_TOP))

    for index, (open_price, high_price, low_price, close_price) in enumerate(ohlc):
        x = x_for(index)
        color = BULL if close_price >= open_price else BEAR
        draw.line((x, y_for(high_price), x, y_for(low_price)), fill=color, width=2)
        body_top = y_for(max(open_price, close_price))
        body_bottom = y_for(min(open_price, close_price))
        if body_bottom - body_top < 3:
            body_bottom = body_top + 3
        draw.rectangle(
            (x - body_width, body_top, x + body_width, body_bottom),
            fill=color,
            outline=color,
        )
        if index == len(ohlc) - 1:
            draw.rectangle(
                (x - body_width - 3, body_top - 3, x + body_width + 3, body_bottom + 3),
                outline=CURRENT_CANDLE,
                width=1,
            )

    threshold_y = y_for(threshold)
    _draw_dashed_line(draw, PLOT_LEFT, threshold_y, PLOT_RIGHT, threshold_y, THRESHOLD)
    draw.text((PLOT_RIGHT - 175, threshold_y - 16), f"threshold {threshold:g}", fill=THRESHOLD, font=font)

    breakout_y = y_for(breakout_price)
    last_x = x_for(len(ohlc) - 1)
    draw.line((last_x, breakout_y, PLOT_RIGHT, breakout_y), fill=BREAKOUT, width=1)
    draw.ellipse((last_x - 6, breakout_y - 6, last_x + 6, breakout_y + 6), fill=BREAKOUT)
    draw.text(
        (PLOT_RIGHT - 175, breakout_y + 4),
        f"breakout {breakout_price:g}",
        fill=BREAKOUT,
        font=font,
    )

    _draw_axis_labels(draw, candles, chart_min, chart_max, x_for, y_for, font)
    draw.text(
        (PLOT_LEFT, CHART_HEIGHT - 65),
        "green=bullish  red=bearish  yellow=current breakout  blue=threshold",
        fill=MUTED_TEXT,
        font=font,
    )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _ohlc_values(kline: Kline) -> tuple[float, float, float, float]:
    open_price = float(kline.open_price)
    close_price = float(kline.close_price)
    high_price = float(kline.high_price) if kline.high_price is not None else max(open_price, close_price)
    low_price = float(kline.low_price) if kline.low_price is not None else min(open_price, close_price)
    values = (open_price, high_price, low_price, close_price)
    if not all(isfinite(value) for value in values) or high_price < low_price:
        raise ValueError(f"Invalid OHLC data for {kline.open_time.isoformat()}")
    return values


def _draw_grid(draw: ImageDraw.ImageDraw, chart_min: float, chart_max: float) -> None:
    for index in range(5):
        ratio = index / 4
        y = round(PLOT_TOP + ratio * (PLOT_BOTTOM - PLOT_TOP))
        draw.line((PLOT_LEFT, y, PLOT_RIGHT, y), fill=GRID, width=1)


def _draw_axis_labels(
    draw: ImageDraw.ImageDraw,
    candles: Sequence[Kline],
    chart_min: float,
    chart_max: float,
    x_for,
    y_for,
    font: ImageFont.ImageFont,
) -> None:
    for index in range(5):
        ratio = index / 4
        price = chart_max - ratio * (chart_max - chart_min)
        y = round(PLOT_TOP + ratio * (PLOT_BOTTOM - PLOT_TOP))
        draw.text((PLOT_RIGHT + 8, y - 6), f"{price:g}", fill=MUTED_TEXT, font=font)

    for index in sorted({0, len(candles) // 2, len(candles) - 1}):
        x = x_for(index)
        label = candles[index].open_time.astimezone(timezone.utc).strftime("%m-%d %H:%M")
        draw.text((x - 28, PLOT_BOTTOM + 12), label, fill=MUTED_TEXT, font=font)


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    start_x: int,
    y: int,
    end_x: int,
    _end_y: int,
    color: str,
) -> None:
    dash = 10
    gap = 7
    x = start_x
    while x < end_x:
        draw.line((x, y, min(x + dash, end_x), y), fill=color, width=1)
        x += dash + gap


def _format_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
