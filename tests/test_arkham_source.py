from binance_alert_bot.transfers.arkham import ArkhamApiConfig, ArkhamTransferSource


def test_arkham_payload_hash_matches_known_formula() -> None:
    url = "https://api.arkm.com/transfers"
    timestamp = "1710000000"
    client_key = "demo-client-key"

    result = ArkhamTransferSource.compute_payload_hash(url, timestamp, client_key)

    assert len(result) == 64
    assert result == "fe8b5be3b9da43ee05cf31fdedce4121d289aba324e06cdce2fa76b239ff0d37"


def test_arkham_parse_transfer_extracts_labels_and_amounts() -> None:
    source = ArkhamTransferSource(ArkhamApiConfig(client_key="demo"))
    raw = {
        "transactionHash": "0xabc",
        "chain": "ethereum",
        "tokenSymbol": "usdt",
        "unitValue": "1234567",
        "historicalUSD": "1234567",
        "fromAddress": {"address": "0x111111111111", "arkhamEntity": {"name": "Binance"}},
        "toAddress": {"address": "0x222222222222", "arkhamLabel": {"name": "Whale"}},
        "blockNumber": "12345",
        "blockTimestamp": "2026-04-12T10:00:00Z",
    }

    event = source._parse_transfer(raw)
    source.close()

    assert event is not None
    assert event.asset == "USDT"
    assert event.amount == 1234567.0
    assert event.usd_value == 1234567.0
    assert event.from_label == "Binance"
    assert event.to_label == "Whale"
