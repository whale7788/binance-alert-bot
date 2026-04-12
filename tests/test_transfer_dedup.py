from binance_alert_bot.transfers.dedup import DeduplicationCache
from binance_alert_bot.transfers.models import TransferEvent


def test_dedup_cache_rejects_recent_duplicate() -> None:
    cache = DeduplicationCache(ttl_seconds=60)

    assert cache.is_duplicate("tx1") is False
    assert cache.is_duplicate("tx1") is True


def test_transfer_event_dedup_key_ignores_tiny_amount_noise() -> None:
    base = dict(
        source="arkham",
        chain="base",
        asset="USDC",
        usd_value=1_000_000.49,
        tx_hash="0xabc",
        from_address="0xfrom",
        to_address="0xto",
        from_label="A",
        to_label="B",
    )

    left = TransferEvent(amount=1234.1111, **base)
    right = TransferEvent(amount=1234.1149, **base)

    assert left.dedup_key == right.dedup_key
