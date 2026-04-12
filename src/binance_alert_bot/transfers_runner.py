from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .config import AppConfig, load_config
from .main import setup_logging
from .notify import TelegramNotifier
from .transfers.arkham import ArkhamApiConfig, ArkhamTransferSource
from .transfers.blacklist import CoinGeckoMarketCapBlacklist, build_ignored_assets
from .transfers.models import ThresholdRule
from .transfers.service import TransferMonitorService


def build_parser() -> argparse.ArgumentParser:
    """定义链上大额转账运行器的命令行参数。"""
    parser = argparse.ArgumentParser(description="Monitor large on-chain transfers.")
    parser.add_argument("--config", required=True, help="Path to config.toml")
    return parser


def build_transfer_service(config: AppConfig) -> TransferMonitorService:
    """根据应用配置构建 transfer monitor。"""
    if not config.transfers.enabled:
        raise ValueError("transfers.enabled is false; transfer monitor is disabled")

    arkham_config = config.transfers.arkham
    source = ArkhamTransferSource(
        ArkhamApiConfig(
            client_key=arkham_config.client_key,
            api_base=arkham_config.api_base,
            min_usd_value=arkham_config.min_usd_value,
            limit=arkham_config.limit,
            flow=arkham_config.flow,
        )
    )
    rules = [
        ThresholdRule(
            chain=rule.chain,
            asset=rule.asset,
            min_amount=rule.min_amount,
            min_usd_value=rule.min_usd_value,
        )
        for rule in config.transfers.rules
    ]
    top_market_cap_symbols: set[str] = set()
    market_cap_blacklist = CoinGeckoMarketCapBlacklist()
    try:
        top_market_cap_symbols = market_cap_blacklist.fetch_top_symbols(config.transfers.auto_blacklist_top_n)
    finally:
        market_cap_blacklist.close()

    ignored_assets = build_ignored_assets(
        manual_ignored_assets=config.transfers.ignored_assets,
        top_market_cap_symbols=top_market_cap_symbols,
        include_stablecoin_variants=config.transfers.auto_blacklist_stablecoin_variants,
        include_wrapped_variants=config.transfers.auto_blacklist_wrapped_variants,
        include_staked_variants=config.transfers.auto_blacklist_staked_variants,
    )
    return TransferMonitorService(source=source, rules=rules, ignored_assets=ignored_assets)


def main(argv: list[str] | None = None) -> int:
    """命令行入口：启动独立的链上大额转账监控。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        monitor = build_transfer_service(config)
    except (OSError, ValidationError, ValueError) as exc:
        print(f"Failed to load config: {exc}", file=sys.stderr)
        return 2

    setup_logging(Path(str(config.log_file).replace(".log", "-transfers.log")), config.log_level)
    notifier = TelegramNotifier(config.telegram)
    source = monitor.source
    interval = config.transfers.poll_interval_seconds
    logging.getLogger(__name__).info(
        "Starting transfer monitor: source=%s poll_interval_seconds=%d rules=%d",
        config.transfers.source,
        interval,
        len(config.transfers.rules),
    )

    try:
        while True:
            matches = monitor.poll()
            if matches:
                logging.getLogger(__name__).info("Matched %d large transfers", len(matches))
                notifier.send_transfer_summary(matches, observed_at=datetime.now(config.zoneinfo))
            time.sleep(interval)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Received KeyboardInterrupt; shutting down transfer monitor")
    except Exception:
        logging.getLogger(__name__).exception("Transfer monitor crashed")
        return 1
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
