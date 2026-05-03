from datetime import datetime

from binance_alert_bot.state import BreakoutWatchState, MonitorState, StateStore


def test_state_round_trip(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    state = MonitorState.empty("2026-04-11")
    state.replace_thresholds(
        today="2026-04-11",
        refreshed_at=datetime.fromisoformat("2026-04-11T00:05:00+00:00"),
        thresholds={"BTCUSDT": 123.45},
    )
    state.mark_notified("BTCUSDT", datetime.fromisoformat("2026-04-11T08:30:00+00:00"))
    state.record_breakout_watch("BTCUSDT", datetime.fromisoformat("2026-04-11T08:30:00+00:00"))
    state.mark_drop_alerted("BTCUSDT", datetime.fromisoformat("2026-04-11T09:00:00+00:00"))

    store.save(state)
    loaded = store.load(today="2026-04-11")

    assert loaded.date == "2026-04-11"
    assert loaded.symbols["BTCUSDT"].threshold == 123.45
    assert loaded.symbols["BTCUSDT"].notified is True
    assert loaded.symbols["BTCUSDT"].last_notify_time == "2026-04-11T08:30:00+00:00"
    assert loaded.symbols["BTCUSDT"].first_breakout_time == "2026-04-11T08:30:00+00:00"
    assert loaded.breakout_watchlist["BTCUSDT"].first_breakout_time == "2026-04-11T08:30:00+00:00"
    assert loaded.breakout_watchlist["BTCUSDT"].last_breakout_time == "2026-04-11T08:30:00+00:00"
    assert loaded.breakout_watchlist["BTCUSDT"].last_drop_alert_kline_open_time == "2026-04-11T09:00:00+00:00"


def test_needs_refresh_for_new_day_missing_symbol_and_extra_symbol() -> None:
    state = MonitorState.empty("2026-04-11")
    state.replace_thresholds(
        today="2026-04-11",
        refreshed_at=datetime.fromisoformat("2026-04-11T00:05:00+00:00"),
        thresholds={"BTCUSDT": 123.45},
    )

    assert state.needs_refresh("2026-04-12", ["BTCUSDT"]) is True
    assert state.needs_refresh("2026-04-11", ["BTCUSDT", "ETHUSDT"]) is True
    assert state.needs_refresh("2026-04-11", ["BTCUSDT"]) is False
    assert state.needs_refresh("2026-04-11", ["BTCUSDT", "ETHUSDT"], ignore_missing_symbols=True) is False

    state.replace_thresholds(
        today="2026-04-11",
        refreshed_at=datetime.fromisoformat("2026-04-11T00:05:00+00:00"),
        thresholds={"BTCUSDT": 123.45, "INTCUSDT": 50.0},
    )
    assert state.needs_refresh("2026-04-11", ["BTCUSDT"]) is True


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


def test_replace_thresholds_preserves_notified_state_for_existing_symbols_on_same_day() -> None:
    state = MonitorState.empty("2026-04-11")
    state.replace_thresholds(
        today="2026-04-11",
        refreshed_at=datetime.fromisoformat("2026-04-11T00:05:00+00:00"),
        thresholds={"BTCUSDT": 123.45},
    )
    state.mark_notified("BTCUSDT", datetime.fromisoformat("2026-04-11T08:30:00+00:00"))

    state.replace_thresholds(
        today="2026-04-11",
        refreshed_at=datetime.fromisoformat("2026-04-11T12:00:00+00:00"),
        thresholds={"BTCUSDT": 130.0, "ETHUSDT": 99.0},
    )

    assert state.symbols["BTCUSDT"].threshold == 130.0
    assert state.symbols["BTCUSDT"].notified is True
    assert state.symbols["BTCUSDT"].last_notify_time == "2026-04-11T08:30:00+00:00"
    assert state.symbols["BTCUSDT"].first_breakout_time == "2026-04-11T08:30:00+00:00"
    assert state.symbols["ETHUSDT"].notified is False


def test_record_breakout_watch_updates_last_breakout_time() -> None:
    state = MonitorState.empty("2026-04-11")

    state.record_breakout_watch("btcusdt", datetime.fromisoformat("2026-04-11T08:30:00+00:00"))
    state.record_breakout_watch("BTCUSDT", datetime.fromisoformat("2026-04-12T08:30:00+00:00"))

    assert state.breakout_watchlist["BTCUSDT"].first_breakout_time == "2026-04-11T08:30:00+00:00"
    assert state.breakout_watchlist["BTCUSDT"].last_breakout_time == "2026-04-12T08:30:00+00:00"


def test_prune_breakout_watchlist_removes_symbols_without_recent_breakout() -> None:
    state = MonitorState(
        date="2026-04-18",
        breakout_watchlist={
            "OLDUSDT": BreakoutWatchState(
                first_breakout_time="2026-04-01T00:00:00+00:00",
                last_breakout_time="2026-04-10T00:00:00+00:00",
            ),
            "FRESHUSDT": BreakoutWatchState(
                first_breakout_time="2026-04-12T00:00:00+00:00",
                last_breakout_time="2026-04-12T00:00:00+00:00",
            ),
        },
    )

    removed = state.prune_breakout_watchlist(datetime.fromisoformat("2026-04-18T00:00:00+00:00"), watch_days=7)

    assert removed == 1
    assert set(state.breakout_watchlist) == {"FRESHUSDT"}
