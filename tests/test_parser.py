"""
Tests for alarm_clock.parser.

Heavy edge-case coverage because time parsing is the highest surface area for
user-facing errors. Every accepted format and every clear rejection is explicit.

What we are testing — behaviour:
- Each supported format string is accepted and produces the correct time.
- Invalid inputs produce a ValueError with a useful message.
- The error message names the input and gives examples.
- Sub-minute precision is discarded (seconds are stripped).
- Whitespace around the input is tolerated.
"""
from __future__ import annotations

from datetime import time

import pytest

from alarm_clock.parser import parse_time


# ── Happy-path: 24-hour formats ───────────────────────────────────────────────


class TestParse24Hour:
    def test_basic_24h(self) -> None:
        assert parse_time("14:30") == time(14, 30)

    def test_zero_padded_hour(self) -> None:
        assert parse_time("07:05") == time(7, 5)

    def test_midnight(self) -> None:
        assert parse_time("00:00") == time(0, 0)

    def test_end_of_day(self) -> None:
        assert parse_time("23:59") == time(23, 59)

    def test_noon(self) -> None:
        assert parse_time("12:00") == time(12, 0)

    def test_with_seconds_discards_seconds(self) -> None:
        # 14:30:45 → 14:30:00
        result = parse_time("14:30:45")
        assert result == time(14, 30)
        assert result.second == 0


# ── Happy-path: 12-hour formats ───────────────────────────────────────────────


class TestParse12Hour:
    def test_pm_with_space(self) -> None:
        assert parse_time("2:30 PM") == time(14, 30)

    def test_am_with_space(self) -> None:
        assert parse_time("9:00 AM") == time(9, 0)

    def test_pm_no_space(self) -> None:
        assert parse_time("2:30PM") == time(14, 30)

    def test_am_no_space(self) -> None:
        assert parse_time("9:00AM") == time(9, 0)

    def test_lowercase_am(self) -> None:
        assert parse_time("9:00 am") == time(9, 0)

    def test_lowercase_pm(self) -> None:
        assert parse_time("2:30 pm") == time(14, 30)

    def test_mixed_case_pm(self) -> None:
        assert parse_time("2:30 Pm") == time(14, 30)

    def test_noon_12pm(self) -> None:
        assert parse_time("12:00 PM") == time(12, 0)

    def test_midnight_12am(self) -> None:
        assert parse_time("12:00 AM") == time(0, 0)

    def test_hour_only_pm(self) -> None:
        assert parse_time("2 PM") == time(14, 0)

    def test_hour_only_am(self) -> None:
        assert parse_time("9 AM") == time(9, 0)

    def test_hour_only_no_space(self) -> None:
        assert parse_time("2PM") == time(14, 0)


# ── Whitespace tolerance ──────────────────────────────────────────────────────


class TestWhitespaceTolerance:
    def test_leading_whitespace(self) -> None:
        assert parse_time("  14:30") == time(14, 30)

    def test_trailing_whitespace(self) -> None:
        assert parse_time("14:30  ") == time(14, 30)

    def test_surrounding_whitespace(self) -> None:
        assert parse_time("  2:30 PM  ") == time(14, 30)


# ── Rejection: invalid inputs ─────────────────────────────────────────────────


class TestParseInvalidInputs:
    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_time("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_time("   ")

    def test_alphabetic_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_time("noon")

    def test_invalid_hour_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_time("25:00")

    def test_invalid_minute_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_time("14:60")

    def test_negative_hour_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_time("-1:30")

    def test_partial_time_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_time("14:")

    def test_date_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_time("2024-01-15")

    def test_iso_datetime_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_time("2024-01-15T14:30:00")

    def test_just_a_number_raises(self) -> None:
        # "14" alone (without AM/PM or colon) should not be accepted
        with pytest.raises(ValueError):
            parse_time("14")

    def test_error_message_contains_input(self) -> None:
        with pytest.raises(ValueError, match="'badtime'"):
            parse_time("badtime")

    def test_error_message_contains_example_formats(self) -> None:
        with pytest.raises(ValueError, match="14:30"):
            parse_time("notaTime")


# ── Return type ───────────────────────────────────────────────────────────────


class TestReturnType:
    def test_returns_time_object(self) -> None:
        result = parse_time("14:30")
        assert isinstance(result, time)

    def test_microseconds_always_zero(self) -> None:
        result = parse_time("14:30")
        assert result.microsecond == 0

    def test_seconds_always_zero(self) -> None:
        result = parse_time("14:30")
        assert result.second == 0
