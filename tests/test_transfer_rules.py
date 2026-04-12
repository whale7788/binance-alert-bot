from binance_alert_bot.transfers.models import ThresholdRule, TransferEvent


def make_event(**kwargs) -> TransferEvent:
    payload = {
        "source": "arkham",
        "chain": "ethereum",
        "asset": "USDT",
        "amount": 1_500_000.0,
        "usd_value": 1_500_000.0,
        "tx_hash": "0xabc",
        "from_address": "0xfrom",
        "to_address": "0xto",
        "from_label": "A",
        "to_label": "B",
    }
    payload.update(kwargs)
    return TransferEvent(**payload)


def test_threshold_rule_matches_amount_and_chain() -> None:
    rule = ThresholdRule(chain="ethereum", asset="USDT", min_amount=1_000_000)

    assert rule.matches(make_event()) is True
    assert rule.matches(make_event(chain="tron")) is False


def test_threshold_rule_matches_usd_threshold() -> None:
    rule = ThresholdRule(chain="ethereum", asset="USDT", min_usd_value=1_000_000)

    assert rule.matches(make_event()) is True
    assert rule.matches(make_event(usd_value=999_999.0)) is False
