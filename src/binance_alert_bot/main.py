from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from .config import load_config
from .exchange import BinanceFuturesClient
from .notify import TelegramNotifier
from .scheduler import BreakoutMonitor
from .state import StateStore


def setup_logging(log_file: Path, log_level: str) -> None:
    """把日志同时输出到控制台和文件，并共用同一套格式。"""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, log_level)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)


def build_parser() -> argparse.ArgumentParser:
    """定义启动程序时使用的命令行参数。"""
    parser = argparse.ArgumentParser(description="Monitor Binance USDT perpetual futures breakouts.")
    parser.add_argument("--config", required=True, help="Path to config.toml")
    return parser


def main(argv: list[str] | None = None) -> int:
    """命令行入口：加载配置、组装依赖并启动监控。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"Failed to load config: {exc}", file=sys.stderr)
        return 2

    setup_logging(config.log_file, config.log_level)
    logging.getLogger(__name__).info("Starting alert bot with Binance futures market data")
    logging.getLogger(__name__).info(
        "Config loaded: monitor_all=%s symbols=%s timezone=%s state_path=%s",
        config.monitor_all,
        config.symbols,
        config.timezone,
        config.state_path,
    )

    monitor = BreakoutMonitor(
        config=config,
        exchange=BinanceFuturesClient(),
        notifier=TelegramNotifier(config.telegram),
        state_store=StateStore(config.state_path),
    )
    try:
        monitor.run_forever()
    except Exception:
        logging.getLogger(__name__).exception("Monitor crashed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
