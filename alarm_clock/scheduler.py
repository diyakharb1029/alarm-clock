"""
Alarm scheduler — the heart of the application.

Design decisions
----------------
1. Poll every N seconds instead of sleeping until the next alarm.
   Reason: "sleep until alarm time" sounds efficient but is a footgun:
   - With multiple alarms, you need a priority queue and re-sorting on changes.
   - If the system clock adjusts (NTP, DST, laptop sleep), you under/overshoot.
   - Cancellation requires interrupting a long sleep, which needs threads or signals.
   Polling every 30s has at most 30s of latency — acceptable for a human alarm —
   and requires no data structures beyond a plain list.

2. Storage is re-read on every tick, not cached.
   Reason: the CLI (`alarm set`, `alarm delete`) modifies storage externally to
   the running scheduler. If the scheduler cached alarms at startup, it would
   never see new alarms. Re-reading every 30s adds negligible I/O and makes the
   system composable without IPC or file-watching.

3. A FIRE_WINDOW_SECONDS tolerance window prevents missed alarms.
   Reason: if the scheduler polls at :00 and :30, an alarm set for :00 will be
   seen on the :00 poll. But if poll drift causes the scheduler to check at :01,
   a window of [alarm_time, alarm_time+60s) ensures the alarm still fires.

4. de-duplication via fired_this_window set.
   Reason: the fire window is 60 seconds; the poll interval is 30 seconds. Without
   tracking which alarms fired, the same alarm would fire twice in the same minute
   (once at the :00 poll and once at the :30 poll). The set is reset when the
   minute changes.

5. ClockProtocol is an injectable dependency, not a global import.
   Reason: datetime.now() cannot be patched cleanly without monkeypatching the
   entire module. An injectable clock lets tests control time precisely without
   patching, mock.patch, or freezegun.

6. After firing, one-time alarms are disabled (not deleted).
   Reason: deleting would silently remove the alarm from `alarm list`, which could
   confuse users who want to re-enable it. Disabling preserves the record while
   making it clear the alarm has been consumed.
"""
from __future__ import annotations

import logging
import time as time_module
from datetime import datetime
from typing import Protocol

from alarm_clock.models import Alarm
from alarm_clock.notifier import Notifier
from alarm_clock.storage import Storage

logger = logging.getLogger(__name__)

# How often the scheduler checks for alarms to fire (seconds).
DEFAULT_POLL_INTERVAL: int = 30

# An alarm is considered "due" if it falls within this window of the current time.
# Must be > poll_interval to guarantee every alarm is caught.
FIRE_WINDOW_SECONDS: int = 60


class ClockProtocol(Protocol):
    """
    Injectable clock for testability.

    The real implementation wraps datetime.now() and time.sleep().
    Test implementations control time deterministically.
    """

    def now(self) -> datetime:
        """Return the current datetime."""
        ...

    def sleep(self, seconds: int) -> None:
        """Block for the given number of seconds."""
        ...


class SystemClock:
    """Production clock backed by the system's datetime and time.sleep."""

    def now(self) -> datetime:
        return datetime.now()

    def sleep(self, seconds: int) -> None:
        time_module.sleep(seconds)


def should_fire(alarm: Alarm, now: datetime) -> bool:
    """
    Return True if *alarm* should fire at time *now*.

    An alarm fires when:
    - It is enabled.
    - It is in the same hour as now.
    - Its minute falls within [now_minute_seconds, now_minute_seconds + FIRE_WINDOW_SECONDS).

    Args:
        alarm: The alarm to check.
        now:   The reference time (typically the current time).

    This function is pure (no I/O, no side effects) and is therefore easy to
    test exhaustively.
    """
    if not alarm.enabled:
        return False

    alarm_time = alarm.wall_time

    if alarm_time.hour != now.hour:
        return False

    # Compare within the minute using seconds for precision
    alarm_seconds = alarm_time.minute * 60
    now_seconds = now.minute * 60 + now.second
    delta = now_seconds - alarm_seconds

    # Fire if we are within the window *after* the alarm time (not before)
    return 0 <= delta < FIRE_WINDOW_SECONDS


def run_scheduler(
    storage: Storage,
    notifier: Notifier,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    clock: ClockProtocol | None = None,
) -> None:
    """
    Start the alarm scheduler loop.

    Polls storage every *poll_interval* seconds. For each enabled alarm whose
    time falls within the current fire window, calls notifier.notify() and
    updates alarm state. Handles KeyboardInterrupt gracefully.

    Args:
        storage:       Persistence layer to read/write alarm state.
        notifier:      Called when an alarm is due to fire.
        poll_interval: Seconds between polls.
        clock:         Injectable clock. Defaults to the real system clock.

    Raises:
        Nothing. KeyboardInterrupt is caught and results in a clean exit message.
    """
    if clock is None:
        clock = SystemClock()

    logger.info("Scheduler started. Poll interval: %ds.", poll_interval)
    print(
        f"Alarm scheduler running (polling every {poll_interval}s). "
        f"Press Ctrl+C to stop.",
        flush=True,
    )

    # Track alarms fired within the current minute to avoid double-firing.
    fired_ids_this_minute: set[str] = set()
    last_minute: int = -1

    try:
        while True:
            now = clock.now()
            current_minute = now.hour * 60 + now.minute

            # Reset the dedup set at the start of each new minute.
            if current_minute != last_minute:
                fired_ids_this_minute.clear()
                last_minute = current_minute

            alarms = storage.load_all()
            for alarm in alarms:
                if alarm.id in fired_ids_this_minute:
                    continue
                if should_fire(alarm, now):
                    logger.info(
                        "Firing alarm %s '%s' at %s", alarm.id, alarm.label, now
                    )
                    notifier.notify(alarm)
                    fired_ids_this_minute.add(alarm.id)
                    _on_fired(alarm, storage)

            clock.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\nScheduler stopped.", flush=True)
        logger.info("Scheduler stopped by KeyboardInterrupt.")


def _on_fired(alarm: Alarm, storage: Storage) -> None:
    """
    Update alarm state immediately after it fires.

    - Recurring alarms: remain enabled; they fire again at the same time tomorrow.
    - One-time alarms: disabled so they are not re-triggered on the next poll.
    """
    if alarm.recurring:
        logger.debug("Recurring alarm %s will fire again tomorrow.", alarm.id)
        # No state change needed — alarm stays enabled.
    else:
        alarm.enabled = False
        storage.update(alarm)
        logger.debug(
            "Disabled one-time alarm %s after firing.", alarm.id
        )
