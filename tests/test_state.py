from datetime import datetime

from binance_alert_bot.state import MonitorState, StateStore


def test_state_round_trip(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    state = MonitorState.empty("2026-04-11")
    state.replace_thresholds(
        today="2026-04-11",
        refreshed_at=datetime.fromisoformat("2026-04-11T00:05:00+00:00"),
        thresholds={"BTCUSDT": 123.45},
    )
    state.mark_notified("BTCUSDT", datetime.fromisoformat("2026-04-11T08:30:00+00:00"))

    store.save(state)
    loaded = store.load(today="2026-04-11")

    assert loaded.date == "2026-04-11"
    assert loaded.symbols["BTCUSDT"].threshold == 123.45
    assert loaded.symbols["BTCUSDT"].notified is True
    assert loaded.symbols["BTCUSDT"].last_notify_time == "2026-04-11T08:30:00+00:00"
    assert loaded.symbols["BTCUSDT"].first_breakout_time == "2026-04-11T08:30:00+00:00"


def test_needs_refresh_for_new_day_and_missing_symbol() -> None:
    state = MonitorState.empty("2026-04-11")
    state.replace_thresholds(
        today="2026-04-11",
        refreshed_at=datetime.fromisoformat("2026-04-11T00:05:00+00:00"),
        thresholds={"BTCUSDT": 123.45},
    )

    assert state.needs_refresh("2026-04-12", ["BTCUSDT"]) is True
    assert state.needs_refresh("2026-04-11", ["BTCUSDT", "ETHUSDT"]) is True
    assert state.needs_refresh("2026-04-11", ["BTCUSDT"]) is False


def test_replace_thresholds_resets_notified_state() -> None:
    state = MonitorState.empty("2026-04-11")
    state.replace_thresholds(
        today="2026-04-11",
        refreshed_at=datetime.fromisoformat("2026-04-11T00:05:00+00:00"),
        thresholds={"BTCUSDT": 123.45},
    )
    state.mark_notified("BTCUSDT", datetime.fromisoformat("2026-04-11T08:30:00+00:00"))

    state.replace_thresholds(
        today="2026-04-12",
        refreshed_at=datetime.fromisoformat("2026-04-12T00:05:00+00:00"),
        thresholds={"BTCUSDT": 130.0},
    )

    assert state.symbols["BTCUSDT"].notified is False
    assert state.symbols["BTCUSDT"].last_notify_time is None
    assert state.symbols["BTCUSDT"].first_breakout_time is None
