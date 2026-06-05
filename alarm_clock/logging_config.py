"""
Logging configuration.

Design decisions
----------------
1. Log to a rotating file in ~/.alarm_clock/alarm.log, not to stderr.
   Reason: stderr is used for the terminal bell (\a). Mixing diagnostic log
   lines with the bell character produces garbled terminal output. File logging
   also persists across sessions, which is invaluable for debugging "why didn't
   my alarm fire?" post-hoc.

2. Default level is WARNING; DEBUG is opt-in via --verbose.
   Reason: a user who just wants alarms does not want to see INFO-level scheduler
   tick logs. DEBUG is available for developers and bug reports. This matches the
   convention of most production CLI tools (git, aws, docker).

3. RotatingFileHandler with a 1 MB cap and 3 backups.
   Reason: a never-rotating log file on a long-running machine would grow
   unboundedly. 1 MB × 4 files ≈ 4 MB maximum disk usage, which is negligible.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_DIR = Path.home() / ".alarm_clock"
_LOG_FILE = _LOG_DIR / "alarm.log"
_MAX_BYTES = 1 * 1024 * 1024  # 1 MB per file
_BACKUP_COUNT = 3  # Keep alarm.log, alarm.log.1, alarm.log.2, alarm.log.3


def configure_logging(verbose: bool = False) -> None:
    """
    Configure the root logger for the alarm clock application.

    Should be called once at application startup (in the Click group callback).
    Subsequent calls are safe but add duplicate handlers — callers should ensure
    they call this only once per process.

    Args:
        verbose: If True, set level to DEBUG. Otherwise WARNING.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if verbose else logging.WARNING

    handler = logging.handlers.RotatingFileHandler(
        filename=_LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
