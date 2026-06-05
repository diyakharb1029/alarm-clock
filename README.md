# alarm-clock

A terminal alarm clock. Set, manage, and run alarms from the command line.

```
$ alarm set "7:30 AM" --label "Standup" --recurring
✓ Alarm set: [a3f2b1c4] 07:30 (daily) — Standup
  Start the scheduler with: alarm run

$ alarm list
ID        TIME      RECURRING   SNOOZE   STATUS    LABEL
────────────────────────────────────────────────────────────────
a3f2b1c4  07:30     daily       5m       enabled   Standup

$ alarm run
Alarm scheduler running (polling every 30s). 
Next: [a3f2b1c4] 07:30 — Standup (in ~3h 12m)
Press Ctrl+C to stop.

====================================================
  ⏰  ALARM: Standup
  Scheduled: 07:30  |  Fired: 07:30:02
  Type: recurring (daily)
  Snooze: 5 min  (`alarm snooze a3f2b1c4`)
====================================================
```

---

## Design decisions

This project optimises for correctness, testability, and explicitness over
feature count. Every significant decision is documented in
[`DECISIONS.md`](DECISIONS.md) with alternatives considered and reasons for
rejection. A summary:

- **Click over argparse** — Click's `CliRunner` makes CLI integration tests
  run in-process at ~1ms each, with no `sys.argv` patching required.
- **Polling over event-driven** — A 30-second poll loop has ≤30s worst-case
  latency (acceptable for a human alarm) and requires no priority queue,
  threading, or cancellation logic.
- **JSON file over SQLite** — The expected dataset is small. JSON is human-readable
  and editable. Writes are atomic via `tempfile + os.replace()`.
- **Notifier as a Protocol** — Any object with `notify(alarm)` satisfies the
  interface. Test doubles are three lines; no `mock.patch` required.
- **Disabled after firing, not deleted** — Preserves history and allows
  re-enabling without re-entering time and label.

## Scope and non-goals

This tool does one thing: fire a terminal notification at a specified time.

**Deliberately excluded:**

| Feature | Why excluded |
|---|---|
| Background daemon | Requires PID files and OS-specific service management |
| Database | JSON is sufficient; no query complexity |
| Timezone support | DST edge cases without clear local-use benefit |
| Web UI | Explicitly out of scope per assignment |
| Push/email/Slack notifications | Network dependency; out of scope |

---

## Quick start

```bash
# 1. Create a virtual environment and install
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Set an alarm
alarm set "7:30 AM" --label "Standup" --recurring

# 3. List alarms to confirm
alarm list

# 4. Start the scheduler in this terminal (keep it open)
alarm run
```

Prefer 12-hour display? Add `--time-format 12h` before any subcommand:
```bash
alias alarm='alarm --time-format 12h'   # put in ~/.zshrc or ~/.bashrc
```

---

## Usage

### Global flags

These apply before any subcommand:

| Flag | Default | Description |
|---|---|---|
| `--time-format 12h\|24h` | `24h` | Display format for all times |
| `--data-dir DIR` | `~/.alarm_clock` | Override storage location |
| `--verbose` | off | Debug logging to `~/.alarm_clock/alarm.log` |

### `alarm set TIME [OPTIONS]`

Set a new alarm. `TIME` accepts 24-hour and 12-hour formats:

```bash
alarm set 14:30
alarm set 07:00 --label "Wake up"
alarm set "2:30 PM" --label "Meeting" --recurring
alarm set 22:00 --snooze-minutes 10
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--label, -l` | `Alarm` | Human-readable name |
| `--recurring, -r` | off | Repeat daily |
| `--snooze-minutes, -s` | `5` | Snooze duration (1–60 min) |

### `alarm list`

Show all alarms with id, time, recurrence, snooze, status, and label.

### `alarm delete ALARM_ID`

Permanently remove an alarm. Use the id shown by `alarm list`.

### `alarm enable ALARM_ID` / `alarm disable ALARM_ID`

Toggle alarm without deleting it. Disabled alarms are skipped by the scheduler.

### `alarm snooze ALARM_ID`

Advance the alarm's time by its snooze duration. Run after the alarm fires to
delay the next occurrence.

### `alarm run [--poll-interval N]`

Start the foreground scheduler. Checks every N seconds (1–59, default 30).
Displays the next scheduled alarm on startup. Press Ctrl+C to stop.

---

## Architecture

Modules are separated by responsibility. None depend on each other circularly:

```
cli.py          ← thin commands, no business logic
models.py       ← Alarm dataclass, validation, serialization
parser.py       ← parse_time() pure function
storage.py      ← JSON read/write, atomic writes
scheduler.py    ← polling loop, should_fire(), injectable clock
notifier.py     ← Notifier protocol, Terminal + Sound + Composite
logging_config  ← rotating file handler at ~/.alarm_clock/alarm.log
```

Full details in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Testing

```bash
make test        # run all tests with coverage
make test-fast   # run without coverage (faster feedback)
make check       # lint + types + tests
```

The test suite has six modules:

- **`test_models.py`** — validation, `next_fire`, `snooze`, serialization, `__str__`
- **`test_parser.py`** — all accepted formats, all rejection cases, whitespace handling, error message quality
- **`test_storage.py`** — CRUD, round-trip fidelity, corrupt file handling
- **`test_scheduler.py`** — `should_fire` edge cases, deduplication, one-time vs. recurring post-fire behaviour
- **`test_notifier.py`** — `TerminalNotifier` output (24h and 12h), `CompositeNotifier` fault isolation
- **`test_cli.py`** — full command integration via Click's `CliRunner`, including `--time-format` coverage

**No test patches `datetime.now()`.** The scheduler uses an injectable
`ClockProtocol`; the domain model accepts `now=` parameters. Tests control time
by injection, not patching.

**What is not tested:**
- `SoundNotifier`: platform audio calls cannot be tested in CI without hardware.
  The sound layer is explicitly marked `# pragma: no cover`.
- Long-running scheduler behaviour (e.g., "fires correctly over 24 hours"):
  covered by the `should_fire` unit tests and the `run_scheduler` integration
  tests with a controlled clock.

---

## AI workflow

AI (Claude) was used to scaffold initial versions of each module. Every generated
artefact was reviewed before use. Notable catches from the review step:

- `next_fire()` initially used `datetime.now()` internally — untestable without
  patching. Fixed by adding `now: datetime | None = None`.
- `should_fire()` initially compared full `datetime` objects (date + time),
  which would have caused recurring alarms to fire only on their creation date.
  Fixed to compare hour and minute independently.
- Test files used `mock.patch` for the scheduler clock instead of the injectable
  `ControlledClock` pattern.

Full log of prompts, outputs, and changes: [`AI_WORKFLOW.md`](AI_WORKFLOW.md).

---

## What I'd do with more time

1. **`alarm next` command** — show the next alarm that will fire and in how many
   minutes. High utility, low complexity.
2. **Background daemon mode** (`alarm run --background`) — requires a PID file
   and platform-specific detachment (`os.fork()` or `start /B`).
3. **OS native notifications** — `plyer` or platform APIs to show a desktop
   notification bubble in addition to the terminal banner.
4. **Property-based tests for the parser** — `hypothesis` to fuzz `parse_time()`
   and verify it never raises anything other than `ValueError`.
5. **Timezone support** — store alarms in UTC with a user-configured local
   timezone. Non-trivial due to DST.
