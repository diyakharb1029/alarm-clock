"""
JSON persistence layer.

Design decisions
----------------
1. Data lives in ~/.alarm_clock/alarms.json.
   Reason: follows the ~/.toolname convention used by ssh, aws, git, and others.
   No sudo required. Data persists across installs without needing a database
   server. The directory is created automatically on first use.

2. The file is read and written in full on every operation.
   Reason: a local alarm store will rarely exceed tens of records. Full read/write
   is O(n) in file size — entirely negligible. Partial updates would require file
   locking or a journal, adding complexity with no measurable benefit at this scale.

3. Writes are atomic: temp file + os.replace().
   Reason: if the process is killed mid-write (power loss, SIGKILL), a partially
   written JSON file would leave the alarm store corrupt and unrecoverable.
   os.replace() is atomic on POSIX (rename(2) is atomic). The temp file is
   written to the same directory as the target so the rename is guaranteed to be
   on the same filesystem (no cross-device rename).

4. Read errors return [] rather than raising.
   Reason: a corrupted or missing alarm file should not crash the CLI. The user
   gets a usable (if empty) alarm list. The error is logged for diagnostics.
   An explicit error message is printed only if the file exists but is unreadable,
   so the user knows something is wrong.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from alarm_clock.models import Alarm

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".alarm_clock"
_DEFAULT_FILE = _DEFAULT_DIR / "alarms.json"


class Storage:
    """
    Manages reading and writing alarms to a JSON file.

    All public methods are safe to call even if the backing file does not yet
    exist — it will be created on the first write.
    """

    def __init__(self, path: Path = _DEFAULT_FILE) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """The absolute path to the JSON file."""
        return self._path

    # ── Read ──────────────────────────────────────────────────────────────────

    def load_all(self) -> list[Alarm]:
        """
        Load all alarms from disk.

        Returns an empty list if the file does not exist or cannot be parsed.
        Logs a warning (not an exception) on parse errors.
        """
        if not self._path.exists():
            return []

        try:
            raw = self._path.read_text(encoding="utf-8")
            data: list[dict[str, Any]] = json.loads(raw)
            alarms = [Alarm.from_dict(d) for d in data]
            logger.debug("Loaded %d alarm(s) from %s", len(alarms), self._path)
            return alarms
        except json.JSONDecodeError as exc:
            logger.warning(
                "Alarm file %s is not valid JSON: %s. Returning empty list.",
                self._path,
                exc,
            )
            return []
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to deserialize alarm from %s: %s. Returning empty list.",
                self._path,
                exc,
            )
            return []

    def get(self, alarm_id: str) -> Alarm | None:
        """Return the alarm with the given id, or None if not found."""
        for alarm in self.load_all():
            if alarm.id == alarm_id:
                return alarm
        return None

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_all(self, alarms: list[Alarm]) -> None:
        """
        Atomically write the full alarm list to disk.

        Raises:
            OSError: If the file cannot be written (e.g., permissions error).
        """
        payload = json.dumps(
            [a.to_dict() for a in alarms],
            indent=2,
            ensure_ascii=False,
        )
        # Write to a temp file in the same directory, then atomically rename.
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                delete=False,
                suffix=".tmp",
            ) as tmp:
                tmp.write(payload)
                tmp_path = Path(tmp.name)

            os.replace(tmp_path, self._path)
            logger.debug("Saved %d alarm(s) to %s", len(alarms), self._path)
        except OSError:
            # Clean up temp file if rename failed
            with contextlib.suppress(Exception):
                tmp_path.unlink(missing_ok=True)
            raise

    def add(self, alarm: Alarm) -> None:
        """Append a new alarm to the store."""
        alarms = self.load_all()
        alarms.append(alarm)
        self.save_all(alarms)
        logger.info("Added alarm %s (%s)", alarm.id, alarm.label)

    def remove(self, alarm_id: str) -> bool:
        """
        Remove the alarm with the given id.

        Returns:
            True if the alarm was found and removed; False if not found.
        """
        alarms = self.load_all()
        filtered = [a for a in alarms if a.id != alarm_id]
        if len(filtered) == len(alarms):
            return False
        self.save_all(filtered)
        logger.info("Removed alarm %s", alarm_id)
        return True

    def update(self, alarm: Alarm) -> bool:
        """
        Replace an existing alarm (matched by id) with the provided instance.

        Returns:
            True if found and updated; False if no alarm with that id exists.
        """
        alarms = self.load_all()
        for i, a in enumerate(alarms):
            if a.id == alarm.id:
                alarms[i] = alarm
                self.save_all(alarms)
                logger.info("Updated alarm %s", alarm.id)
                return True
        return False
