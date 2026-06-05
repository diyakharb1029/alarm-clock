"""
Domain model for the alarm clock.

Design decisions
----------------
1. Alarm stores hour/minute as plain integers rather than a datetime.time object.
   Reason: datetime.time is not JSON-serializable. Storing primitives avoids the
   need for custom JSON encoders/decoders and keeps the storage layer dumb.

2. Validation lives in __post_init__, not in the CLI or storage layer.
   Reason: an Alarm is always valid by construction — you cannot create an Alarm
   with hour=25. This eliminates a class of bugs where an invalid alarm slips
   through and causes a confusing error at fire time rather than at creation time.

3. next_fire() accepts an optional `now` parameter.
   Reason: pure testability. A function that reads datetime.now() internally
   cannot be tested without mocking. Injecting `now` as a parameter makes tests
   deterministic with zero patching required.

4. Short UUID (8 chars) rather than a full UUID.
   Reason: Users type alarm IDs at the CLI (`alarm delete <id>`). A full 36-char
   UUID is hostile to keyboard input. 8 hex characters gives 4 billion unique IDs,
   which is sufficient for a local alarm store.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass
class Alarm:
    """
    Represents a single alarm.

    Attributes:
        id:              Short UUID (8 chars) for user-facing identification.
        hour:            Hour of day in 24-hour format (0–23).
        minute:          Minute of hour (0–59).
        label:           Human-readable name displayed when the alarm fires.
        recurring:       If True, re-enables itself each day after firing.
        snooze_minutes:  How many minutes a snooze operation extends the alarm.
        enabled:         Whether the alarm is active. Disabled alarms are skipped
                         by the scheduler but remain in storage.
        created_at:      ISO-8601 timestamp recording when the alarm was created.
    """

    id: str = field(default_factory=_new_id)
    hour: int = 0
    minute: int = 0
    label: str = "Alarm"
    recurring: bool = False
    snooze_minutes: int = 5
    enabled: bool = True
    created_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not (0 <= self.hour <= 23):
            raise ValueError(f"hour must be 0–23, got {self.hour!r}")
        if not (0 <= self.minute <= 59):
            raise ValueError(f"minute must be 0–59, got {self.minute!r}")
        if not (1 <= self.snooze_minutes <= 60):
            raise ValueError(
                f"snooze_minutes must be 1–60, got {self.snooze_minutes!r}"
            )
        if not self.label.strip():
            raise ValueError("label must not be empty or whitespace-only")

    # ── Time helpers ──────────────────────────────────────────────────────────

    @property
    def wall_time(self) -> time:
        """Return the alarm's time-of-day as a datetime.time object."""
        return time(self.hour, self.minute)

    def display_time(self, twelve_hour: bool = False) -> str:
        """
        Return time formatted for terminal display.

        Args:
            twelve_hour: If True, format as "H:MM AM/PM" (e.g. "2:30 PM").
                         If False (default), format as "HH:MM" (e.g. "14:30").
        """
        if twelve_hour:
            # Avoid strftime's %-I which is Linux-only; compute manually instead.
            h = self.hour % 12 or 12  # 0 → 12 (midnight), 13 → 1, etc.
            period = "AM" if self.hour < 12 else "PM"
            return f"{h}:{self.minute:02d} {period}"
        return f"{self.hour:02d}:{self.minute:02d}"

    def next_fire(self, now: datetime | None = None) -> datetime:
        """
        Return the next datetime at which this alarm should fire.

        If the alarm time today has not yet passed, return today at that time.
        If it has already passed (or is this exact minute), return tomorrow.

        Args:
            now: The reference time. Defaults to datetime.now(). Injected in
                 tests to avoid patching.
        """
        if now is None:
            now = datetime.now()

        candidate = datetime.combine(now.date(), self.wall_time)
        if candidate > now:
            return candidate
        return candidate + timedelta(days=1)

    def snooze(self, now: datetime | None = None) -> datetime:
        """
        Return the datetime that results from applying one snooze period.

        Args:
            now: The reference time. Defaults to datetime.now().
        """
        if now is None:
            now = datetime.now()
        return now + timedelta(minutes=self.snooze_minutes)

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "hour": self.hour,
            "minute": self.minute,
            "label": self.label,
            "recurring": self.recurring,
            "snooze_minutes": self.snooze_minutes,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Alarm":
        """
        Deserialize from a dictionary (e.g., loaded from JSON).

        Unknown keys in `data` are silently ignored. This allows the schema to
        evolve without breaking existing alarm files.
        """
        return cls(
            id=data["id"],
            hour=int(data["hour"]),
            minute=int(data["minute"]),
            label=data.get("label", "Alarm"),
            recurring=bool(data.get("recurring", False)),
            snooze_minutes=int(data.get("snooze_minutes", 5)),
            enabled=bool(data.get("enabled", True)),
            created_at=data.get("created_at", _now_iso()),
        )

    def __str__(self) -> str:
        recur = " (daily)" if self.recurring else ""
        status = "" if self.enabled else " [disabled]"
        return f"[{self.id}] {self.display_time()}{recur} — {self.label}{status}"
