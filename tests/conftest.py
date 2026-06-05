"""
Shared pytest fixtures.

Design note: fixtures are kept minimal — only the things that are genuinely
shared across test modules. Each test module defines its own local helpers
for anything specific to its domain.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alarm_clock.models import Alarm
from alarm_clock.storage import Storage


@pytest.fixture
def tmp_storage(tmp_path: Path) -> Storage:
    """
    A Storage instance backed by a temporary directory.

    pytest's `tmp_path` fixture provides a unique temp directory per test,
    so there is no state bleed between tests even when they write to disk.
    """
    return Storage(path=tmp_path / "alarms.json")


@pytest.fixture
def sample_alarm() -> Alarm:
    """A valid Alarm for use as a baseline in tests."""
    return Alarm(
        id="test0001",
        hour=14,
        minute=30,
        label="Test Alarm",
        recurring=False,
        snooze_minutes=5,
        enabled=True,
    )


@pytest.fixture
def recurring_alarm() -> Alarm:
    """A recurring Alarm for use in scheduler / storage tests."""
    return Alarm(
        id="test0002",
        hour=7,
        minute=0,
        label="Daily standup",
        recurring=True,
        snooze_minutes=10,
        enabled=True,
    )
