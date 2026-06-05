# Requirements

This document defines what the alarm clock does, what it explicitly does not
do, and why those boundaries were drawn. Writing this before implementation
forced explicit choices about scope.

---

## Problem statement

A developer wants to set timed reminders from the terminal without switching
context to a browser or phone. The tool should be composable with other CLI
tools and require no GUI.

---

## Functional requirements

### FR-1: Set a one-time alarm
The user can set an alarm for a specific time today (or the next occurrence of
that time if it has already passed). The alarm fires once, then is disabled.

### FR-2: Set a recurring alarm
The user can set an alarm that repeats at the same time every day. It re-arms
automatically after firing.

### FR-3: Label alarms
Each alarm can have a human-readable label (e.g., "Standup", "Medication").
Labels are displayed when the alarm fires and in the alarm list.

### FR-4: List alarms
The user can view all alarms (enabled and disabled) with their id, time, label,
recurrence, snooze duration, and status.

### FR-5: Delete an alarm
The user can permanently remove an alarm by its id.

### FR-6: Enable / disable an alarm
The user can temporarily disable an alarm without deleting it, and re-enable
it later.

### FR-7: Snooze an alarm
After an alarm fires, the user can snooze it via CLI. Snooze advances the
alarm's time by its configured snooze duration (1–60 minutes, default 5).

### FR-8: Run the scheduler
The user can start a foreground scheduler process that polls for due alarms.
The scheduler exits cleanly on Ctrl+C.

### FR-9: Accept multiple time formats
The CLI accepts times in both 24-hour (`14:30`) and 12-hour (`2:30 PM`)
formats. Invalid formats produce a clear error message with examples.

### FR-10: Persist alarms
Alarms survive process restarts. Storage is in `~/.alarm_clock/alarms.json`.

### FR-11: Notify on alarm fire
When an alarm fires, the user sees a formatted banner on stdout and hears a
system audio cue (best-effort; failure is silent).

### FR-12: User-selectable time display format
The user can choose between 24-hour (e.g. `14:30`) and 12-hour (e.g. `2:30 PM`)
display formats via a global `--time-format` flag. The preference applies to all
time output: `alarm list`, `alarm set` confirmation, `alarm snooze` confirmation,
and the alarm banner when firing. Default is 24-hour.

---

## Non-functional requirements

### NFR-1: Python 3.10+
No backports, no compatibility shims. The `X | Y` union syntax in type hints
requires Python 3.10; `from __future__ import annotations` is used throughout
to keep annotations as strings, ensuring compatibility.

### NFR-2: Single external runtime dependency
Only `click`. The tool should be installable with `pip install .` on a clean
Python environment without pulling in a large dependency tree.

### NFR-3: Tests must not require real time passage
The scheduler's injectable clock makes tests deterministic and fast. No test
should call `time.sleep()`.

### NFR-4: Exit codes are meaningful
- `0`: success
- `1`: user error (invalid input, alarm not found)
- `2`: interrupted (Ctrl+C in a blocking command)

Tools that emit predictable exit codes can be composed with `&&`, `||`, and
`set -e` in shell scripts.

### NFR-5: Atomic file writes
The alarm file is never left in a partially-written state. A process killed
mid-write should not corrupt the alarm store.

---

## Explicitly out of scope

| Feature | Reason excluded |
|---|---|
| Database (SQLite, Postgres) | JSON file sufficient for the scale; no query complexity |
| Web UI | Explicitly excluded by the assignment |
| Background daemon | Requires PID files and OS-specific service management |
| Timezone support beyond system-local | DST edge cases add significant complexity without clear user benefit for a local tool |
| Alarm sounds beyond system defaults | Third-party audio libraries add 50+ MB of dependencies for a beep |
| Push notifications (email, Slack) | Network dependency; out of scope for a local CLI tool |
| Import/export | No use case identified |
| Multiple users | Single-user tool; storage is in ~ |

---

## Assumptions

1. The user runs `alarm run` in a terminal they keep visible. There is no
   daemon or background process model.

2. System local time is used. The user is assumed to be in one timezone.

3. Alarm granularity is one minute. Sub-minute precision is not supported or
   advertised.

4. The user has audio hardware if they want sound notifications. Sound failure
   is silent and does not affect alarm correctness.

5. The alarm file is not shared between multiple machines or users.
