"""
Shared pytest fixtures.

Design note: fixtures are kept minimal — only the things that are genuinely
shared across test modules. Each test module defines its own local helpers
for anything specific to its domain.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from alarm_clock.storage import Storage


@pytest.fixture
def tmp_storage(tmp_path: Path) -> Storage:
    """
    A Storage instance backed by a temporary directory.

    pytest's `tmp_path` fixture provides a unique temp directory per test,
    so there is no state bleed between tests even when they write to disk.
    """
    return Storage(path=tmp_path / "alarms.json")
