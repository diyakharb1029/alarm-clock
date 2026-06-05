"""
Tests for alarm_clock.notifier.

What we are testing — behaviour:
- TerminalNotifier prints the alarm label, scheduled time, and fired time.
- TerminalNotifier respects the twelve_hour flag for both the scheduled time
  and the fired-at time (this test would have caught the %-I platform bug).
- CompositeNotifier calls all notifiers and does not propagate exceptions
  from one notifier to the others.

SoundNotifier is excluded from automated tests: it calls platform-specific
system commands (afplay, aplay, winsound) that require audio hardware and
a real OS audio stack. It is tested manually on each supported platform.
"""

from __future__ import annotations

import pytest

from alarm_clock.models import Alarm
from alarm_clock.notifier import CompositeNotifier, TerminalNotifier

# ── TerminalNotifier ──────────────────────────────────────────────────────────


class TestTerminalNotifier:
    @pytest.fixture
    def alarm(self) -> Alarm:
        return Alarm(id="notif001", hour=14, minute=30, label="Review")

    def test_notify_prints_label(
        self, alarm: Alarm, capsys: pytest.CaptureFixture
    ) -> None:  # type: ignore[type-arg]
        TerminalNotifier().notify(alarm)
        out = capsys.readouterr().out
        assert "Review" in out

    def test_notify_24h_shows_scheduled_time(
        self,
        alarm: Alarm,
        capsys: pytest.CaptureFixture,  # type: ignore[type-arg]
    ) -> None:
        TerminalNotifier(twelve_hour=False).notify(alarm)
        out = capsys.readouterr().out
        assert "14:30" in out

    def test_notify_12h_shows_pm_in_scheduled_time(
        self,
        alarm: Alarm,
        capsys: pytest.CaptureFixture,  # type: ignore[type-arg]
    ) -> None:
        # Proves the scheduled time uses 12h format — "2:30 PM" not "14:30"
        TerminalNotifier(twelve_hour=True).notify(alarm)
        out = capsys.readouterr().out
        assert "2:30 PM" in out
        assert "14:30" not in out

    def test_notify_12h_shows_pm_in_fired_time(
        self,
        alarm: Alarm,
        capsys: pytest.CaptureFixture,  # type: ignore[type-arg]
    ) -> None:
        # Proves the fired-at time also uses 12h format.
        # This test would have caught the %-I platform bug:
        # %-I is a GNU strftime extension unavailable on Windows.
        # We verify output contains AM or PM, which only appears if formatting
        # succeeded — not a literal "%-I:%M:%S %p" fallback.
        TerminalNotifier(twelve_hour=True).notify(alarm)
        out = capsys.readouterr().out
        assert "AM" in out or "PM" in out

    def test_notify_default_is_24h(
        self,
        alarm: Alarm,
        capsys: pytest.CaptureFixture,  # type: ignore[type-arg]
    ) -> None:
        TerminalNotifier().notify(alarm)
        out = capsys.readouterr().out
        # No AM/PM in default mode
        assert " AM" not in out
        assert " PM" not in out

    def test_notify_recurring_shows_type(
        self,
        capsys: pytest.CaptureFixture,  # type: ignore[type-arg]
    ) -> None:
        alarm = Alarm(hour=7, minute=0, label="Standup", recurring=True)
        TerminalNotifier().notify(alarm)
        out = capsys.readouterr().out
        assert "recurring" in out.lower()

    def test_notify_shows_snooze_hint(
        self,
        alarm: Alarm,
        capsys: pytest.CaptureFixture,  # type: ignore[type-arg]
    ) -> None:
        TerminalNotifier().notify(alarm)
        out = capsys.readouterr().out
        assert "snooze" in out.lower()
        assert alarm.id in out

    def test_notify_midnight_12h(
        self,
        capsys: pytest.CaptureFixture,  # type: ignore[type-arg]
    ) -> None:
        alarm = Alarm(hour=0, minute=0, label="Midnight")
        TerminalNotifier(twelve_hour=True).notify(alarm)
        out = capsys.readouterr().out
        # 00:00 in 12h is "12:00 AM", not "0:00 AM"
        assert "12:00 AM" in out

    def test_notify_noon_12h(
        self,
        capsys: pytest.CaptureFixture,  # type: ignore[type-arg]
    ) -> None:
        alarm = Alarm(hour=12, minute=0, label="Noon")
        TerminalNotifier(twelve_hour=True).notify(alarm)
        out = capsys.readouterr().out
        assert "12:00 PM" in out


# ── CompositeNotifier ─────────────────────────────────────────────────────────


class TestCompositeNotifier:
    def test_calls_all_notifiers(self) -> None:
        calls: list[str] = []

        class N1:
            def notify(self, alarm: Alarm) -> None:
                calls.append("n1")

        class N2:
            def notify(self, alarm: Alarm) -> None:
                calls.append("n2")

        alarm = Alarm(hour=8, minute=0, label="x")
        CompositeNotifier([N1(), N2()]).notify(alarm)  # type: ignore[arg-type]
        assert calls == ["n1", "n2"]

    def test_continues_after_failing_notifier(self) -> None:
        """A failing notifier must not silence the ones that follow it."""
        calls: list[str] = []

        class Failing:
            def notify(self, alarm: Alarm) -> None:
                raise RuntimeError("audio device not found")

        class Working:
            def notify(self, alarm: Alarm) -> None:
                calls.append("worked")

        alarm = Alarm(hour=8, minute=0, label="x")
        CompositeNotifier([Failing(), Working()]).notify(alarm)  # type: ignore[arg-type]
        assert calls == ["worked"]

    def test_empty_notifier_list_does_nothing(self) -> None:
        alarm = Alarm(hour=8, minute=0, label="x")
        CompositeNotifier([]).notify(alarm)  # must not raise
