"""
Alarm notification layer.

Design decisions
----------------
1. Notifier is a Protocol (structural subtyping), not an ABC.
   Reason: any object with a `notify(alarm)` method satisfies the interface
   without inheriting from anything. Test doubles are trivial to write — a plain
   class with a `notify` method that appends to a list is a valid Notifier.
   No mock.patch required.

2. CompositeNotifier fans out to multiple notifiers independently.
   Reason: if SoundNotifier fails (no audio hardware, running in CI), the
   TerminalNotifier should still work. Each notifier is wrapped in try/except so
   one failure never silences another. The scheduler knows only about Notifier —
   it has no awareness of sound vs. terminal.

3. Sound uses platform system calls, not a third-party audio library.
   Reason: pygame and playsound add ~50 MB of dependencies for what is
   essentially a single beep. System commands (afplay on macOS, aplay/paplay on
   Linux, winsound on Windows) are always available on their respective platforms.
   Failure is silent — sound is best-effort.

4. stdout vs stderr split.
   Reason: the alarm message (what fires) goes to stdout so it can be piped
   (`alarm run | tee alarm.log`). The terminal bell (\a) goes to stderr so it
   does not appear as garbage in piped output. This follows the Unix convention
   that stdout carries data and stderr carries signals.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from datetime import datetime
from typing import Protocol, runtime_checkable

from alarm_clock.models import Alarm

logger = logging.getLogger(__name__)


@runtime_checkable
class Notifier(Protocol):
    """
    Structural protocol for alarm notification.

    Any object implementing ``notify(alarm: Alarm) -> None`` satisfies this
    interface. No inheritance required.
    """

    def notify(self, alarm: Alarm) -> None:
        """Fire the notification for the given alarm."""
        ...


def _format_fired_time(dt: datetime, *, twelve_hour: bool) -> str:
    """
    Format a fired-at datetime for terminal display.

    Uses manual 12h computation rather than strftime's %-I directive,
    which is a GNU extension unavailable on Windows.
    """
    if twelve_hour:
        h = dt.hour % 12 or 12
        period = "AM" if dt.hour < 12 else "PM"
        return f"{h}:{dt.minute:02d}:{dt.second:02d} {period}"
    return dt.strftime("%H:%M:%S")


class TerminalNotifier:
    """
    Writes a formatted alarm banner to stdout and a bell to stderr.

    The visual separator makes the alarm stand out from scheduler status output.

    Args:
        twelve_hour: If True, display times in 12-hour format (e.g. "2:30 PM").
                     Defaults to False (24-hour, e.g. "14:30").
    """

    def __init__(self, twelve_hour: bool = False) -> None:
        self._twelve_hour = twelve_hour

    def notify(self, alarm: Alarm) -> None:
        now = datetime.now()
        now_str = _format_fired_time(now, twelve_hour=self._twelve_hour)
        scheduled = alarm.display_time(twelve_hour=self._twelve_hour)
        border = "=" * 52
        print(f"\n{border}", flush=True)
        print(f"  ⏰  ALARM: {alarm.label}", flush=True)
        print(f"  Scheduled: {scheduled}  |  Fired: {now_str}", flush=True)
        if alarm.recurring:
            print("  Type: recurring (daily)", flush=True)
        if alarm.snooze_minutes:
            print(
                f"  Snooze: {alarm.snooze_minutes} min  (`alarm snooze {alarm.id}`)",
                flush=True,
            )
        print(f"{border}\n", flush=True)
        # Bell to stderr — does not corrupt piped stdout
        print("\a", end="", flush=True, file=sys.stderr)


class SoundNotifier:
    """
    Plays a system audio cue using platform-native commands.

    Failure is always silent — audio is a nice-to-have, never a requirement.
    """

    def notify(self, alarm: Alarm) -> None:
        system = platform.system()
        try:
            if system == "Darwin":
                # afplay is available on all macOS installs
                os.system("afplay /System/Library/Sounds/Glass.aiff 2>/dev/null")
            elif system == "Linux":
                # Try aplay (ALSA) first, fall back to paplay (PulseAudio)
                ret = os.system(
                    "aplay -q /usr/share/sounds/alsa/Front_Center.wav 2>/dev/null"
                )
                if ret != 0:
                    os.system(
                        "paplay /usr/share/sounds/freedesktop/stereo/"
                        "alarm-clock-elapsed.oga 2>/dev/null"
                    )
            elif system == "Windows":
                import winsound  # type: ignore[import]  # noqa: PLC0415

                winsound.Beep(1000, 1000)
        except Exception as exc:
            logger.debug("SoundNotifier failed (non-fatal): %s", exc)


class CompositeNotifier:
    """
    Fans out a notification to multiple Notifier implementations.

    Each notifier is called independently; a failure in one does not
    prevent the others from running.
    """

    def __init__(self, notifiers: list[Notifier]) -> None:
        self._notifiers = notifiers

    def notify(self, alarm: Alarm) -> None:
        for notifier in self._notifiers:
            try:
                notifier.notify(alarm)
            except Exception as exc:
                logger.warning(
                    "Notifier %s raised an unexpected error: %s",
                    type(notifier).__name__,
                    exc,
                )


def default_notifier(twelve_hour: bool = False) -> CompositeNotifier:
    """
    Return the default production notifier (terminal output + system sound).

    Args:
        twelve_hour: Passed through to TerminalNotifier for time display format.
    """
    return CompositeNotifier(
        [TerminalNotifier(twelve_hour=twelve_hour), SoundNotifier()]
    )
