"""
Tests for alarm_clock.models.

What we are testing — behaviour, not implementation:
- Alarm rejects invalid field values at construction time.
- Alarm always returns the correct next fire time relative to a given clock.
- Snooze returns now + snooze_minutes.
- Serialization round-trips cleanly.
- __str__ is human-readable.
"""
from __future__ import annotations

from datetime import datetime, time

import pytest

from alarm_clock.models import Alarm


# ── Construction & validation ─────────────────────────────────────────────────


class TestAlarmValidation:
    def test_valid_alarm_does_not_raise(self) -> None:
        alarm = Alarm(hour=14, minute=30, label="Meeting")
        assert alarm.hour == 14
        assert alarm.minute == 30

    def test_hour_zero_is_valid(self) -> None:
        alarm = Alarm(hour=0, minute=0, label="Midnight")
        assert alarm.hour == 0

    def test_hour_23_is_valid(self) -> None:
        alarm = Alarm(hour=23, minute=59, label="Late")
        assert alarm.hour == 23

    def test_hour_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="hour"):
            Alarm(hour=-1, minute=0, label="Bad")

    def test_hour_above_23_raises(self) -> None:
        with pytest.raises(ValueError, match="hour"):
            Alarm(hour=24, minute=0, label="Bad")

    def test_minute_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="minute"):
            Alarm(hour=0, minute=-1, label="Bad")

    def test_minute_above_59_raises(self) -> None:
        with pytest.raises(ValueError, match="minute"):
            Alarm(hour=0, minute=60, label="Bad")

    def test_empty_label_raises(self) -> None:
        with pytest.raises(ValueError, match="label"):
            Alarm(hour=8, minute=0, label="")

    def test_whitespace_label_raises(self) -> None:
        with pytest.raises(ValueError, match="label"):
            Alarm(hour=8, minute=0, label="   ")

    def test_snooze_minutes_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="snooze_minutes"):
            Alarm(hour=8, minute=0, label="x", snooze_minutes=0)

    def test_snooze_minutes_61_raises(self) -> None:
        with pytest.raises(ValueError, match="snooze_minutes"):
            Alarm(hour=8, minute=0, label="x", snooze_minutes=61)

    def test_snooze_minutes_1_is_valid(self) -> None:
        alarm = Alarm(hour=8, minute=0, label="x", snooze_minutes=1)
        assert alarm.snooze_minutes == 1

    def test_snooze_minutes_60_is_valid(self) -> None:
        alarm = Alarm(hour=8, minute=0, label="x", snooze_minutes=60)
        assert alarm.snooze_minutes == 60


# ── wall_time property ────────────────────────────────────────────────────────


class TestWallTime:
    def test_returns_correct_time(self) -> None:
        alarm = Alarm(hour=9, minute=15, label="x")
        assert alarm.wall_time == time(9, 15)

    def test_midnight_returns_time_zero(self) -> None:
        alarm = Alarm(hour=0, minute=0, label="x")
        assert alarm.wall_time == time(0, 0)


# ── display_time ──────────────────────────────────────────────────────────────


class TestDisplayTime:
    # ── 24-hour (default) ─────────────────────────────────────────────────────

    def test_two_digit_hour_and_minute(self) -> None:
        assert Alarm(hour=14, minute=30, label="x").display_time() == "14:30"

    def test_zero_padded_hour(self) -> None:
        assert Alarm(hour=7, minute=5, label="x").display_time() == "07:05"

    def test_midnight_24h(self) -> None:
        assert Alarm(hour=0, minute=0, label="x").display_time() == "00:00"

    # ── 12-hour ───────────────────────────────────────────────────────────────

    def test_12h_pm_afternoon(self) -> None:
        assert Alarm(hour=14, minute=30, label="x").display_time(twelve_hour=True) == "2:30 PM"

    def test_12h_am_morning(self) -> None:
        assert Alarm(hour=9, minute=5, label="x").display_time(twelve_hour=True) == "9:05 AM"

    def test_12h_noon(self) -> None:
        # 12:00 PM, not 0:00 PM
        assert Alarm(hour=12, minute=0, label="x").display_time(twelve_hour=True) == "12:00 PM"

    def test_12h_midnight(self) -> None:
        # 12:00 AM, not 0:00 AM
        assert Alarm(hour=0, minute=0, label="x").display_time(twelve_hour=True) == "12:00 AM"

    def test_12h_one_am(self) -> None:
        assert Alarm(hour=1, minute=0, label="x").display_time(twelve_hour=True) == "1:00 AM"

    def test_12h_eleven_pm(self) -> None:
        assert Alarm(hour=23, minute=59, label="x").display_time(twelve_hour=True) == "11:59 PM"


# ── next_fire ─────────────────────────────────────────────────────────────────


class TestNextFire:
    def test_alarm_in_the_future_today(self) -> None:
        # Alarm at 14:00; current time is 13:00 — should fire today
        alarm = Alarm(hour=14, minute=0, label="x")
        now = datetime(2024, 1, 15, 13, 0, 0)
        result = alarm.next_fire(now=now)
        assert result == datetime(2024, 1, 15, 14, 0)

    def test_alarm_already_passed_today_returns_tomorrow(self) -> None:
        # Alarm at 08:00; current time is 09:00 — should fire tomorrow
        alarm = Alarm(hour=8, minute=0, label="x")
        now = datetime(2024, 1, 15, 9, 0, 0)
        result = alarm.next_fire(now=now)
        assert result == datetime(2024, 1, 16, 8, 0)

    def test_alarm_at_exact_current_minute_returns_tomorrow(self) -> None:
        # Alarm at 14:30; current time is also 14:30 — "now" means it just fired
        alarm = Alarm(hour=14, minute=30, label="x")
        now = datetime(2024, 1, 15, 14, 30, 0)
        result = alarm.next_fire(now=now)
        assert result == datetime(2024, 1, 16, 14, 30)

    def test_alarm_one_second_in_the_future(self) -> None:
        alarm = Alarm(hour=14, minute=30, label="x")
        now = datetime(2024, 1, 15, 14, 29, 59)
        result = alarm.next_fire(now=now)
        assert result == datetime(2024, 1, 15, 14, 30)


# ── snooze ────────────────────────────────────────────────────────────────────


class TestSnooze:
    def test_snooze_adds_snooze_minutes(self) -> None:
        alarm = Alarm(hour=8, minute=0, label="x", snooze_minutes=5)
        now = datetime(2024, 1, 15, 8, 0, 0)
        result = alarm.snooze(now=now)
        assert result == datetime(2024, 1, 15, 8, 5, 0)

    def test_snooze_crosses_hour_boundary(self) -> None:
        alarm = Alarm(hour=8, minute=55, label="x", snooze_minutes=10)
        now = datetime(2024, 1, 15, 8, 55, 0)
        result = alarm.snooze(now=now)
        assert result == datetime(2024, 1, 15, 9, 5, 0)

    def test_snooze_crosses_midnight(self) -> None:
        alarm = Alarm(hour=23, minute=57, label="x", snooze_minutes=5)
        now = datetime(2024, 1, 15, 23, 57, 0)
        result = alarm.snooze(now=now)
        assert result == datetime(2024, 1, 16, 0, 2, 0)


# ── Serialization ─────────────────────────────────────────────────────────────


class TestSerialization:
    def test_to_dict_contains_all_fields(self) -> None:
        alarm = Alarm(hour=9, minute=30, label="Standup", recurring=True)
        d = alarm.to_dict()
        assert d["hour"] == 9
        assert d["minute"] == 30
        assert d["label"] == "Standup"
        assert d["recurring"] is True
        assert "id" in d
        assert "created_at" in d

    def test_round_trip_preserves_all_fields(self) -> None:
        original = Alarm(
            id="abc12345",
            hour=22,
            minute=0,
            label="Bedtime",
            recurring=False,
            snooze_minutes=15,
            enabled=False,
        )
        restored = Alarm.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.hour == original.hour
        assert restored.minute == original.minute
        assert restored.label == original.label
        assert restored.recurring == original.recurring
        assert restored.snooze_minutes == original.snooze_minutes
        assert restored.enabled == original.enabled

    def test_from_dict_uses_defaults_for_missing_optional_keys(self) -> None:
        # Simulate an alarm file that predates the snooze_minutes field
        minimal = {"id": "aabbccdd", "hour": 8, "minute": 0}
        alarm = Alarm.from_dict(minimal)
        assert alarm.label == "Alarm"
        assert alarm.snooze_minutes == 5
        assert alarm.enabled is True

    def test_from_dict_with_string_integers(self) -> None:
        # Protect against JSON files edited by hand with "8" instead of 8
        d = {"id": "aabbccdd", "hour": "8", "minute": "0"}
        alarm = Alarm.from_dict(d)
        assert alarm.hour == 8
        assert alarm.minute == 0


# ── __str__ ───────────────────────────────────────────────────────────────────


class TestStr:
    def test_str_contains_id_time_label(self) -> None:
        alarm = Alarm(id="abc12345", hour=7, minute=30, label="Wake up")
        s = str(alarm)
        assert "abc12345" in s
        assert "07:30" in s
        assert "Wake up" in s

    def test_str_shows_disabled_when_disabled(self) -> None:
        alarm = Alarm(hour=7, minute=0, label="x", enabled=False)
        assert "disabled" in str(alarm)

    def test_str_shows_daily_when_recurring(self) -> None:
        alarm = Alarm(hour=7, minute=0, label="x", recurring=True)
        assert "daily" in str(alarm)
