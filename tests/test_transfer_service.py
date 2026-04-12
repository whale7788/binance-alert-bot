from binance_alert_bot.transfers.models import ThresholdRule, TransferEvent
from binance_alert_bot.transfers.service import TransferMonitorService


class FakeTransferSource:
    name = "fake"

    def __init__(self, events):
        self._events = events

    def fetch_recent_transfers(self):
        return self._events


def make_event(asset: str, usd_value: float) -> TransferEvent:
    return TransferEvent(
        source="arkham",
        chain="base",
        asset=asset,
        amount=usd_value,
        usd_value=usd_value,
        tx_hash=f"0x{asset.lower()}",
        from_address="0xfrom",
        to_address="0xto",
        from_label="A",
        to_label="B",
    )


def test_transfer_monitor_service_ignores_blacklisted_assets() -> None:
    service = TransferMonitorService(
        source=FakeTransferSource([make_event("BTC", 2_000_000), make_event("USDC", 2_000_000)]),
        rules=[ThresholdRule(min_usd_value=1_000_000)],
        ignored_assets=["BTC", "ETH", "SOL"],
    )

    matches = service.poll()

    assert [match.event.asset for match in matches] == ["USDC"]
