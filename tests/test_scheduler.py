"""
Tests for alarm_clock.scheduler.

What we are testing — behaviour:
- should_fire() returns True only when the alarm is enabled and within the window.
- should_fire() returns False for disabled alarms, wrong hour, wrong minute.
- run_scheduler fires the notifier exactly once per alarm per minute.
- After firing, a one-time alarm is disabled in storage.
- After firing, a recurring alarm remains enabled.
- KeyboardInterrupt stops the loop cleanly (no exception propagates).

Testing strategy for run_scheduler
------------------------------------
run_scheduler has an infinite loop. We test it by injecting a fake clock that
raises StopIteration after N ticks — the test catches StopIteration and inspects
the side effects. No threading, no patching, no freezegun required.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from pathlib import Path

import pytest

from alarm_clock.models import Alarm
from alarm_clock.scheduler import (
    FIRE_WINDOW_SECONDS,
    _on_fired,
    run_scheduler,
    should_fire,
)
from alarm_clock.storage import Storage

# ── Helpers ───────────────────────────────────────────────────────────────────


class RecordingNotifier:
    """Notifier that records which alarms it was called with."""

    def __init__(self) -> None:
        self.fired: list[Alarm] = []

    def notify(self, alarm: Alarm) -> None:
        self.fired.append(alarm)


class ControlledClock:
    """
    Injectable clock that steps through a predefined sequence of datetimes.

    After exhausting the sequence it raises StopIteration on the next
    call to now(), which terminates the scheduler loop in tests.
    sleep() is a no-op.
    """

    def __init__(self, times: list[datetime]) -> None:
        self._iter: Generator[datetime, None, None] = iter(times)

    def now(self) -> datetime:
        try:
            return next(self._iter)
        except StopIteration:
            # Propagate as KeyboardInterrupt so the scheduler exits cleanly
            raise KeyboardInterrupt from None

    def sleep(self, seconds: int) -> None:
        pass  # No-op in tests


# ── should_fire ───────────────────────────────────────────────────────────────


class TestShouldFire:
    @pytest.fixture
    def alarm(self) -> Alarm:
        return Alarm(hour=14, minute=30, label="Test")

    def test_fires_at_exact_alarm_time(self, alarm: Alarm) -> None:
        now = datetime(2024, 1, 15, 14, 30, 0)
        assert should_fire(alarm, now) is True

    def test_fires_within_window(self, alarm: Alarm) -> None:
        # 30 seconds after alarm time — still within FIRE_WINDOW_SECONDS
        now = datetime(2024, 1, 15, 14, 30, 30)
        assert should_fire(alarm, now) is True

    def test_does_not_fire_after_window(self, alarm: Alarm) -> None:
        # 14:31:00 is exactly FIRE_WINDOW_SECONDS (60s) past 14:30:00 — outside window
        now = datetime(2024, 1, 15, 14, 31, 0)
        assert should_fire(alarm, now) is False

    def test_does_not_fire_before_alarm_time(self, alarm: Alarm) -> None:
        now = datetime(2024, 1, 15, 14, 29, 59)
        assert should_fire(alarm, now) is False

    def test_does_not_fire_wrong_hour(self, alarm: Alarm) -> None:
        now = datetime(2024, 1, 15, 15, 30, 0)
        assert should_fire(alarm, now) is False

    def test_does_not_fire_when_disabled(self, alarm: Alarm) -> None:
        alarm.enabled = False
        now = datetime(2024, 1, 15, 14, 30, 0)
        assert should_fire(alarm, now) is False

    def test_fires_at_midnight(self) -> None:
        alarm = Alarm(hour=0, minute=0, label="Midnight")
        now = datetime(2024, 1, 15, 0, 0, 0)
        assert should_fire(alarm, now) is True

    def test_does_not_fire_one_minute_early(self, alarm: Alarm) -> None:
        now = datetime(2024, 1, 15, 14, 29, 0)
        assert should_fire(alarm, now) is False


# ── _on_fired ─────────────────────────────────────────────────────────────────


class TestOnFired:
    def test_one_time_alarm_is_disabled_after_firing(self, tmp_path: Path) -> None:
        storage = Storage(path=tmp_path / "alarms.json")
        alarm = Alarm(id="onetime1", hour=8, minute=0, label="x", recurring=False)
        storage.add(alarm)

        _on_fired(alarm, storage)

        reloaded = storage.get("onetime1")
        assert reloaded is not None
        assert reloaded.enabled is False

    def test_recurring_alarm_stays_enabled_after_firing(self, tmp_path: Path) -> None:
        storage = Storage(path=tmp_path / "alarms.json")
        alarm = Alarm(id="recur001", hour=8, minute=0, label="x", recurring=True)
        storage.add(alarm)

        _on_fired(alarm, storage)

        reloaded = storage.get("recur001")
        assert reloaded is not None
        assert reloaded.enabled is True


# ── run_scheduler ─────────────────────────────────────────────────────────────


class TestRunScheduler:
    def test_fires_alarm_when_due(self, tmp_path: Path) -> None:
        storage = Storage(path=tmp_path / "alarms.json")
        alarm = Alarm(id="fire0001", hour=9, minute=0, label="x")
        storage.add(alarm)

        notifier = RecordingNotifier()
        clock = ControlledClock([datetime(2024, 1, 15, 9, 0, 0)])

        run_scheduler(storage=storage, notifier=notifier, clock=clock)

        assert len(notifier.fired) == 1
        assert notifier.fired[0].id == "fire0001"

    def test_does_not_fire_disabled_alarm(self, tmp_path: Path) -> None:
        storage = Storage(path=tmp_path / "alarms.json")
        alarm = Alarm(id="skip0001", hour=9, minute=0, label="x", enabled=False)
        storage.add(alarm)

        notifier = RecordingNotifier()
        clock = ControlledClock([datetime(2024, 1, 15, 9, 0, 0)])

        run_scheduler(storage=storage, notifier=notifier, clock=clock)

        assert notifier.fired == []

    def test_does_not_fire_same_alarm_twice_in_one_minute(self, tmp_path: Path) -> None:
        storage = Storage(path=tmp_path / "alarms.json")
        alarm = Alarm(id="dedup001", hour=9, minute=0, label="x")
        storage.add(alarm)

        notifier = RecordingNotifier()
        # Two ticks in the same minute
        clock = ControlledClock(
            [
                datetime(2024, 1, 15, 9, 0, 0),
                datetime(2024, 1, 15, 9, 0, 30),
            ]
        )

        run_scheduler(storage=storage, notifier=notifier, clock=clock)

        assert len(notifier.fired) == 1

    def test_fires_alarm_on_second_tick_of_same_minute(self, tmp_path: Path) -> None:
        """Alarm missed on first tick (just before window) fires on second tick."""
        storage = Storage(path=tmp_path / "alarms.json")
        alarm = Alarm(id="tick0001", hour=9, minute=0, label="x")
        storage.add(alarm)

        notifier = RecordingNotifier()
        clock = ControlledClock(
            [
                datetime(2024, 1, 15, 8, 59, 45),  # too early
                datetime(2024, 1, 15, 9, 0, 5),  # in window
            ]
        )

        run_scheduler(storage=storage, notifier=notifier, clock=clock)

        assert len(notifier.fired) == 1

    def test_disables_one_time_alarm_after_firing(self, tmp_path: Path) -> None:
        storage = Storage(path=tmp_path / "alarms.json")
        alarm = Alarm(id="ot000001", hour=9, minute=0, label="x", recurring=False)
        storage.add(alarm)

        notifier = RecordingNotifier()
        clock = ControlledClock([datetime(2024, 1, 15, 9, 0, 0)])

        run_scheduler(storage=storage, notifier=notifier, clock=clock)

        reloaded = storage.get("ot000001")
        assert reloaded is not None
        assert reloaded.enabled is False

    def test_recurring_alarm_stays_enabled_after_firing(self, tmp_path: Path) -> None:
        storage = Storage(path=tmp_path / "alarms.json")
        alarm = Alarm(id="rec00001", hour=9, minute=0, label="x", recurring=True)
        storage.add(alarm)

        notifier = RecordingNotifier()
        clock = ControlledClock([datetime(2024, 1, 15, 9, 0, 0)])

        run_scheduler(storage=storage, notifier=notifier, clock=clock)

        reloaded = storage.get("rec00001")
        assert reloaded is not None
        assert reloaded.enabled is True

    def test_exits_cleanly_with_no_alarms(self, tmp_path: Path) -> None:
        storage = Storage(path=tmp_path / "alarms.json")
        notifier = RecordingNotifier()
        clock = ControlledClock([datetime(2024, 1, 15, 9, 0, 0)])

        # Should not raise
        run_scheduler(storage=storage, notifier=notifier, clock=clock)

        assert notifier.fired == []

    def test_poll_interval_equal_to_fire_window_raises(self, tmp_path: Path) -> None:
        """
        poll_interval == FIRE_WINDOW_SECONDS means alarms firing between polls
        fall outside the window on the next poll and are silently skipped.
        run_scheduler must reject this at startup, not silently misbehave.
        """
        storage = Storage(path=tmp_path / "alarms.json")
        notifier = RecordingNotifier()
        with pytest.raises(ValueError, match="poll_interval"):
            run_scheduler(
                storage=storage,
                notifier=notifier,
                poll_interval=FIRE_WINDOW_SECONDS,
            )

    def test_poll_interval_above_fire_window_raises(self, tmp_path: Path) -> None:
        storage = Storage(path=tmp_path / "alarms.json")
        notifier = RecordingNotifier()
        with pytest.raises(ValueError, match="poll_interval"):
            run_scheduler(
                storage=storage,
                notifier=notifier,
                poll_interval=FIRE_WINDOW_SECONDS + 30,
            )
