"""
Tests for alarm_clock.storage.

What we are testing — behaviour:
- load_all returns [] when the file does not exist (not an error).
- add / remove / update / get work correctly.
- remove returns False when the id does not exist.
- update returns False when the id does not exist.
- The file is written atomically (we verify the final state, not the mechanism).
- A corrupt JSON file causes load_all to return [] and not raise.
- Alarm state survives a full round-trip through the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from alarm_clock.models import Alarm
from alarm_clock.storage import Storage

# ── Fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(path=tmp_path / "alarms.json")


@pytest.fixture
def alarm_a() -> Alarm:
    return Alarm(id="aaaaaaaa", hour=8, minute=0, label="Morning")


@pytest.fixture
def alarm_b() -> Alarm:
    return Alarm(id="bbbbbbbb", hour=22, minute=30, label="Night")


# ── load_all ──────────────────────────────────────────────────────────────────


class TestLoadAll:
    def test_returns_empty_list_when_file_does_not_exist(
        self, storage: Storage
    ) -> None:
        assert storage.load_all() == []

    def test_returns_empty_list_for_corrupt_json(self, storage: Storage) -> None:
        storage.path.write_text("this is not json", encoding="utf-8")
        result = storage.load_all()
        assert result == []

    def test_returns_empty_list_for_empty_json_array(self, storage: Storage) -> None:
        storage.path.write_text("[]", encoding="utf-8")
        assert storage.load_all() == []

    def test_returns_all_stored_alarms(
        self, storage: Storage, alarm_a: Alarm, alarm_b: Alarm
    ) -> None:
        storage.save_all([alarm_a, alarm_b])
        result = storage.load_all()
        ids = {a.id for a in result}
        assert ids == {"aaaaaaaa", "bbbbbbbb"}


# ── add ───────────────────────────────────────────────────────────────────────


class TestAdd:
    def test_add_single_alarm(self, storage: Storage, alarm_a: Alarm) -> None:
        storage.add(alarm_a)
        result = storage.load_all()
        assert len(result) == 1
        assert result[0].id == alarm_a.id

    def test_add_multiple_alarms(
        self, storage: Storage, alarm_a: Alarm, alarm_b: Alarm
    ) -> None:
        storage.add(alarm_a)
        storage.add(alarm_b)
        result = storage.load_all()
        assert len(result) == 2

    def test_add_is_persisted_to_disk(self, storage: Storage, alarm_a: Alarm) -> None:
        storage.add(alarm_a)
        # Create a fresh Storage pointing to the same file to simulate restart
        fresh = Storage(path=storage.path)
        result = fresh.load_all()
        assert len(result) == 1
        assert result[0].id == alarm_a.id


# ── remove ────────────────────────────────────────────────────────────────────


class TestRemove:
    def test_remove_existing_alarm_returns_true(
        self, storage: Storage, alarm_a: Alarm
    ) -> None:
        storage.add(alarm_a)
        assert storage.remove(alarm_a.id) is True

    def test_remove_existing_alarm_deletes_it(
        self, storage: Storage, alarm_a: Alarm
    ) -> None:
        storage.add(alarm_a)
        storage.remove(alarm_a.id)
        assert storage.load_all() == []

    def test_remove_nonexistent_id_returns_false(self, storage: Storage) -> None:
        assert storage.remove("doesnotexist") is False

    def test_remove_only_removes_target(
        self, storage: Storage, alarm_a: Alarm, alarm_b: Alarm
    ) -> None:
        storage.add(alarm_a)
        storage.add(alarm_b)
        storage.remove(alarm_a.id)
        remaining = storage.load_all()
        assert len(remaining) == 1
        assert remaining[0].id == alarm_b.id


# ── get ───────────────────────────────────────────────────────────────────────


class TestGet:
    def test_get_existing_returns_alarm(self, storage: Storage, alarm_a: Alarm) -> None:
        storage.add(alarm_a)
        result = storage.get(alarm_a.id)
        assert result is not None
        assert result.id == alarm_a.id

    def test_get_nonexistent_returns_none(self, storage: Storage) -> None:
        assert storage.get("nope") is None


# ── update ────────────────────────────────────────────────────────────────────


class TestUpdate:
    def test_update_existing_returns_true(
        self, storage: Storage, alarm_a: Alarm
    ) -> None:
        storage.add(alarm_a)
        alarm_a.enabled = False
        assert storage.update(alarm_a) is True

    def test_update_persists_change(self, storage: Storage, alarm_a: Alarm) -> None:
        storage.add(alarm_a)
        alarm_a.enabled = False
        storage.update(alarm_a)
        reloaded = storage.get(alarm_a.id)
        assert reloaded is not None
        assert reloaded.enabled is False

    def test_update_nonexistent_returns_false(
        self, storage: Storage, alarm_a: Alarm
    ) -> None:
        # alarm_a was never added
        assert storage.update(alarm_a) is False

    def test_update_does_not_duplicate(self, storage: Storage, alarm_a: Alarm) -> None:
        storage.add(alarm_a)
        alarm_a.label = "Updated label"
        storage.update(alarm_a)
        all_alarms = storage.load_all()
        assert len(all_alarms) == 1
        assert all_alarms[0].label == "Updated label"


# ── Round-trip fidelity ───────────────────────────────────────────────────────


class TestRoundTrip:
    def test_all_fields_survive_disk_round_trip(self, storage: Storage) -> None:
        original = Alarm(
            id="rttttttt",
            hour=23,
            minute=59,
            label="Round trip",
            recurring=True,
            snooze_minutes=15,
            enabled=False,
        )
        storage.add(original)
        restored = storage.get(original.id)
        assert restored is not None
        assert restored.id == original.id
        assert restored.hour == original.hour
        assert restored.minute == original.minute
        assert restored.label == original.label
        assert restored.recurring == original.recurring
        assert restored.snooze_minutes == original.snooze_minutes
        assert restored.enabled == original.enabled
