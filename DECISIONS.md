# Architecture Decision Records

This document records every significant engineering decision made during this
project, along with the alternatives considered and the reasoning behind each
choice. The goal is to make implicit decisions explicit — reviewers should
understand not just what was built, but why.

---

## ADR-001: Click over argparse

**Status:** Accepted

**Context:**
Python's standard library includes `argparse`. A third-party alternative,
`click`, adds a dependency but provides additional capabilities.

**Decision:**
Use `click`.

**Reasoning:**
The deciding factor is testability. Click ships with `CliRunner`, which runs
the application in-process with captured output — no subprocess overhead, no
`sys.argv` patching, tests complete in ~1ms each. `argparse` forces test authors
to either patch `sys.argv` (fragile) or invoke via `subprocess` (slow).

The dependency cost is one small, stable, widely-used library. The benefit is
a faster, cleaner test suite and less boilerplate for subcommand wiring.

**Alternatives rejected:**
- `argparse`: testability is inferior. No `CliRunner` equivalent.
- `typer`: builds on Click but adds `pydantic`-style type inference. More magic
  than this project needs; Click is explicit.

---

## ADR-002: Polling over event-driven scheduling

**Status:** Accepted

**Context:**
An alarm clock must fire at a specific time. Two broad approaches exist:
1. Sleep until the next alarm time (`time.sleep(seconds_until_alarm)`).
2. Poll periodically and check whether any alarm is due.

**Decision:**
Poll every 30 seconds.

**Reasoning:**
"Sleep until alarm" sounds efficient but has several failure modes:

- **Multiple alarms:** requires a priority queue, re-sorting on add/remove.
- **System clock drift:** NTP adjustments or laptop sleep cause under/overshoot.
- **Cancellation:** interrupting a long sleep requires threads or signals.

Polling every 30 seconds means ≤30s of worst-case latency — acceptable for
a human-facing alarm. A 30s poll costs ~zero CPU and zero memory. The
implementation is a plain `while True:` loop with no data structures.

**Alternatives rejected:**
- `sched` (stdlib): requires calling `sched.run()` which blocks until an event,
  making it hard to check for newly added alarms without threads.
- `APScheduler`: production-grade scheduler library. Genuine overkill for a
  single-user CLI. Would pull in multiple transitive dependencies.

---

## ADR-003: JSON file storage over SQLite

**Status:** Accepted

**Context:**
Alarms must persist between process restarts. Options include: in-memory only,
JSON file, SQLite, or a proper database.

**Decision:**
JSON file at `~/.alarm_clock/alarms.json`.

**Reasoning:**
- The expected dataset is small (single-user, ≤100 alarms).
- JSON is human-readable and editable — a power user can modify it directly.
- No additional dependencies.
- Follows the `~/.toolname/config` convention used by `aws`, `ssh`, `gh`, etc.

Writes are atomic via `tempfile + os.replace()` to prevent corruption if the
process is killed mid-write. This matches what SQLite's WAL mode provides, at
a fraction of the complexity.

**Alternatives rejected:**
- SQLite: requires schema migrations, a query layer, and adds no meaningful
  benefit for a list of ≤100 items.
- In-memory only: alarms are lost on exit. Useless for a recurring alarm feature.
- `configparser` / TOML: less ecosystem support for loading lists of structured
  records.

---

## ADR-004: Notifier as a Protocol (structural subtyping)

**Status:** Accepted

**Context:**
The scheduler needs to notify users when an alarm fires. Notification could
mean terminal output, sound, OS notifications, or any combination.

**Decision:**
Define `Notifier` as a `typing.Protocol`. Provide `TerminalNotifier`,
`SoundNotifier`, and `CompositeNotifier` as concrete implementations.

**Reasoning:**
A Protocol means any object with a `notify(alarm) -> None` method satisfies
the interface without inheriting from anything. In tests, a recording notifier
is three lines of code:

```python
class RecordingNotifier:
    def __init__(self): self.fired = []
    def notify(self, alarm): self.fired.append(alarm)
```

No `mock.patch`, no `MagicMock`, no import of the production implementation.
`CompositeNotifier` fans out to multiple notifiers independently — sound failure
never silences the terminal output.

**Alternatives rejected:**
- ABC with `@abstractmethod`: forces test doubles to inherit. Adds coupling
  with no behavioural benefit.
- Single function `notify(alarm)`: not composable without conditionals.

---

## ADR-005: Alarm stores hour/minute as integers

**Status:** Accepted

**Context:**
A time-of-day could be stored as a `datetime.time` object or as primitive integers.

**Decision:**
Store `hour: int` and `minute: int`.

**Reasoning:**
`datetime.time` is not JSON-serializable by default. Storing primitives keeps
the serialization layer completely dumb — `json.dumps(alarm.to_dict())` works
with no custom encoder. The `wall_time` property converts to `datetime.time`
on demand for comparison logic.

**Alternatives rejected:**
- `datetime.time` field: requires a custom JSON encoder/decoder (more code,
  more surface area for bugs).
- ISO-8601 string: requires parsing on every load, adds a failure mode.

---

## ADR-006: Short UUID (8 chars) for alarm IDs

**Status:** Accepted

**Context:**
Alarms need IDs so users can reference them at the CLI (`alarm delete <id>`).

**Decision:**
Use the first 8 characters of a UUID4: `str(uuid.uuid4())[:8]`.

**Reasoning:**
A full UUID (e.g., `f47ac10b-58cc-4372-a567-0e02b2c3d479`) is hostile to
keyboard input. An 8-character hex ID (`f47ac10b`) is short enough to type
or copy from terminal output. The collision probability for a local alarm
store that will never exceed a few hundred records is negligible.

**Alternatives rejected:**
- Sequential integers: simple but requires tracking a counter across restarts.
- Full UUID: correct but unusable as a CLI argument.
- Human-readable names: collision-prone and requires user input at creation time.

---

## ADR-007: stdout for alarm messages, stderr for bells

**Status:** Accepted

**Context:**
The scheduler produces two types of output: the alarm banner (what fired) and
the terminal bell character (`\a`).

**Decision:**
Alarm banner → stdout. Terminal bell → stderr.

**Reasoning:**
Unix convention: stdout carries data, stderr carries signals. Separating them
allows `alarm run | tee alarm.log` to capture the alarm message without
logging the bell character as garbage. A user who wants to suppress sound
can redirect stderr: `alarm run 2>/dev/null`.

**Alternatives rejected:**
- Both to stdout: breaks piping. The bell character appears as `^G` in log files.
- Both to stderr: alarm messages are not diagnostics. They should be capturable.

---

## ADR-008: Disabled (not deleted) after one-time alarm fires

**Status:** Accepted

**Context:**
After a one-time alarm fires, it could be deleted from storage or marked disabled.

**Decision:**
Mark as `enabled = False`, keep in storage.

**Reasoning:**
Deleting would silently remove the alarm from `alarm list`, confusing users who
check the list after the fact ("did my 14:30 alarm fire?"). Keeping it disabled
provides an audit trail and allows re-enabling without re-entering the time and
label. Users who want to clean up can run `alarm delete <id>`.

**Alternatives rejected:**
- Delete after firing: no history. Confusing UX.
- Keep enabled: alarm fires every 30s until the minute changes. Clearly wrong.

---

## ADR-009: Time format as a global CLI flag, not per-alarm or persisted config

**Status:** Accepted

**Context:**
Users have preferences for 12-hour vs 24-hour time display. Several implementation
models were considered when adding this feature post-initial release.

**Decision:**
Global `--time-format 12h|24h` flag on the CLI group. Defaults to `24h`.

**Reasoning:**
The key question is: where does the preference belong? Options:

- **Per-alarm** (`alarm set 14:30 --format 12h`): wrong model. The display
  format is a user preference, not a property of the alarm itself. Storing it
  per-alarm means different alarms display differently in the same `alarm list`
  output, which would be confusing.

- **Persisted config file** (`~/.alarm_clock/config.json`): correct model, but
  introduces a new storage concern — a separate config file, or mixing
  configuration with alarm records. Either way: more code, more failure modes,
  and a migration path to manage. The benefit is one less flag to type.

- **Auto-detect from locale** (`locale.getpreferredencoding()` / LC_TIME): too
  fragile. Python's locale module is notoriously platform-dependent. macOS,
  Linux, and Windows all handle locale differently. A tool that behaves
  differently on different machines without user intent is surprising.

- **Global CLI flag** (chosen): simplest correct model. The preference travels
  with the invocation, not the alarm. Users who always want 12h add an alias:
  `alias alarm='alarm --time-format 12h'`. No new state, no migration path.

**Alternatives rejected:**
- Per-alarm storage: display format is session preference, not alarm data.
- Persisted config: disproportionate complexity for a display preference.
- Locale detection: too fragile to be reliable across platforms.

---

## What I would do with more time

1. **Daemon mode** (`alarm run --background`): write a PID file, redirect
   output to the log file, and detach from the terminal. The hard part is
   platform-specific (launchd on macOS, systemd on Linux, Task Scheduler on
   Windows). Deliberately out of scope for this submission.

2. **OS native notifications**: use `plyer` or platform APIs to show a desktop
   notification bubble in addition to the terminal banner. Low-complexity win
   for usability.

3. **`alarm next` command**: show the next alarm that will fire and in how many
   minutes. Quick to implement, high utility.

4. **Timezone support**: store alarms in UTC with a user-configured local
   timezone. DST transitions make this non-trivial; skipped to keep scope clean.

5. **Property-based tests for the parser**: use `hypothesis` to fuzz
   `parse_time()` and confirm it never raises anything other than `ValueError`.
