from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from binance_alert_bot.exchange import BinanceFuturesClient  # noqa: E402
from binance_alert_bot.strategy import candle_change_percent  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark 5m intrabar drop checks against Binance Futures.")
    parser.add_argument("--symbols", type=int, default=50, help="Number of USDT perpetual symbols to test.")
    parser.add_argument("--workers", type=int, default=20, help="Concurrent request workers.")
    parser.add_argument("--rounds", type=int, default=3, help="Benchmark rounds.")
    parser.add_argument("--interval", default="5m", help="Kline interval.")
    parser.add_argument("--threshold-percent", type=float, default=5.0, help="Drop threshold for alert candidates.")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds.")
    parser.add_argument("--max-retries", type=int, default=3, help="HTTP max retries.")
    parser.add_argument("--retry-delay", type=float, default=0.25, help="Retry delay seconds.")
    parser.add_argument("--pause", type=float, default=2.0, help="Pause seconds between rounds.")
    return parser.parse_args()


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int(len(values) * pct) - 1))
    return sorted(values)[index]


def run_round(
    client: BinanceFuturesClient,
    symbols: list[str],
    workers: int,
    interval: str,
    threshold_percent: float,
) -> dict:
    def fetch(symbol: str) -> tuple[str, float, float]:
        start = time.perf_counter()
        kline = client.get_latest_kline(symbol, interval=interval)
        change_percent = candle_change_percent(kline.open_price, kline.close_price)
        return symbol, time.perf_counter() - start, change_percent

    durations: list[float] = []
    failures: list[tuple[str, str, str]] = []
    alert_candidates: list[tuple[str, float]] = []
    started_at = time.perf_counter()

    with ThreadPoolExecutor(max_workers=min(workers, len(symbols))) as executor:
        futures = {executor.submit(fetch, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                got_symbol, duration, change_percent = future.result()
            except Exception as exc:
                failures.append((symbol, exc.__class__.__name__, str(exc)[:200]))
                continue
            durations.append(duration)
            if change_percent <= -abs(threshold_percent):
                alert_candidates.append((got_symbol, change_percent))

    total_seconds = time.perf_counter() - started_at
    return {
        "total_seconds": total_seconds,
        "durations": durations,
        "failures": failures,
        "alert_candidates": alert_candidates,
    }


def print_round(index: int, result: dict) -> None:
    durations = result["durations"]
    failures = result["failures"]
    alert_candidates = result["alert_candidates"]

    print(f"\nround={index}")
    print(f"total_seconds={result['total_seconds']:.3f}")
    print(f"success_count={len(durations)}")
    print(f"failures_count={len(failures)}")
    if durations:
        print(f"avg_request_seconds={statistics.mean(durations):.3f}")
        print(f"median_request_seconds={statistics.median(durations):.3f}")
        print(f"p95_request_seconds={percentile(durations, 0.95):.3f}")
        print(f"min_request_seconds={min(durations):.3f}")
        print(f"max_request_seconds={max(durations):.3f}")
    for failure in failures[:10]:
        print(f"failure={failure!r}")
    print(f"alert_candidates_count={len(alert_candidates)}")
    for symbol, change_percent in alert_candidates[:10]:
        print(f"alert_candidate={symbol}:{change_percent:.2f}%")


def main() -> int:
    args = parse_args()
    if args.symbols <= 0:
        raise SystemExit("--symbols must be greater than 0")
    if args.workers <= 0:
        raise SystemExit("--workers must be greater than 0")
    if args.rounds <= 0:
        raise SystemExit("--rounds must be greater than 0")

    client = BinanceFuturesClient(
        timeout=args.timeout,
        max_retries=args.max_retries,
        retry_delay_seconds=args.retry_delay,
    )
    try:
        symbols = client.get_usdt_perpetual_symbols()[: args.symbols]
        print(f"symbols_count={len(symbols)}")
        print(f"workers={args.workers}")
        print(f"rounds={args.rounds}")
        print(f"interval={args.interval}")
        print("symbols=" + ",".join(symbols))

        totals: list[float] = []
        for index in range(1, args.rounds + 1):
            result = run_round(
                client=client,
                symbols=symbols,
                workers=args.workers,
                interval=args.interval,
                threshold_percent=args.threshold_percent,
            )
            totals.append(result["total_seconds"])
            print_round(index, result)
            if index < args.rounds and args.pause > 0:
                time.sleep(args.pause)

        print("\nsummary")
        print(f"total_avg_seconds={statistics.mean(totals):.3f}")
        print(f"total_median_seconds={statistics.median(totals):.3f}")
        print(f"total_min_seconds={min(totals):.3f}")
        print(f"total_max_seconds={max(totals):.3f}")
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
