# Architecture

## Overview

`alarm-clock` is a single-process, foreground CLI application with no network
access, no background threads, and one external dependency (`click`). Its
architecture is intentionally simple because the problem is simple.

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI (cli.py)                          │
│  click commands: set, list, delete, enable, disable,         │
│                  snooze, run                                 │
└────────┬──────────────────────────────┬─────────────────────┘
         │                              │
         ▼                              ▼
┌────────────────┐            ┌─────────────────────┐
│  Storage       │            │  Scheduler           │
│  (storage.py)  │◄───────────│  (scheduler.py)      │
│                │            │                      │
│  JSON file I/O │            │  polling loop        │
│  atomic writes │            │  should_fire()       │
└───────┬────────┘            └──────────┬───────────┘
        │                               │
        ▼                               ▼
┌────────────────┐            ┌─────────────────────┐
│  Alarm         │            │  Notifier            │
│  (models.py)   │            │  (notifier.py)       │
│                │            │                      │
│  dataclass     │            │  Protocol            │
│  validation    │            │  CompositeNotifier   │
│  serialization │            │  Terminal + Sound    │
└────────────────┘            └─────────────────────┘
```

## Module responsibilities

### `cli.py`
The entry point and command dispatcher. Each command is thin: it parses
arguments, validates with domain objects, and delegates to Storage or Scheduler.
No business logic lives here.

The Click group callback constructs two shared objects stored in `ctx.obj`:
- `storage`: a `Storage` instance pointed at the correct path (respects `--data-dir`)
- `twelve_hour`: a `bool` derived from `--time-format` (respects user preference)

Every subcommand reads both from `ctx.obj`. This is the only place either is
constructed — subcommands never create `Storage` or read `--time-format` directly.

### `models.py`
The `Alarm` dataclass is the core domain object. It owns:
- Field validation (via `__post_init__`)
- Time calculations (`next_fire`, `snooze`)
- Serialization (`to_dict`, `from_dict`)

`models.py` has no imports from other `alarm_clock` modules. It is a leaf node
in the dependency graph.

### `parser.py`
A single pure function, `parse_time(value: str) -> datetime.time`. No state.
No side effects. Accepts multiple time formats; raises `ValueError` on failure.

### `storage.py`
Manages reading and writing the JSON alarm file. Atomic writes via
`tempfile.NamedTemporaryFile + os.replace()`. All methods are safe to call
before the file exists.

### `scheduler.py`
The runtime loop. Reads all alarms from storage every `poll_interval` seconds,
checks each against `should_fire()`, calls the notifier, and updates storage
after firing. The clock is an injectable dependency for testability.

### `notifier.py`
Defines the `Notifier` Protocol and three implementations:
- `TerminalNotifier(twelve_hour=)`: writes a formatted banner to stdout, bell to stderr. Accepts a `twelve_hour` flag to control time display format.
- `SoundNotifier`: plays a system audio cue via platform-native commands. Failure is always silent.
- `CompositeNotifier`: fans out to a list of notifiers independently — one failing never silences the rest.

Time formatting in `TerminalNotifier` uses a private `_format_fired_time()` helper
rather than strftime's `%-I` directive, which is a GNU extension unavailable on Windows.

### `logging_config.py`
Configures a rotating file handler at `~/.alarm_clock/alarm.log`. Default
level is WARNING; `--verbose` enables DEBUG.

## Data flow: setting an alarm

```
User: alarm --time-format 12h set "2:30 PM" --label "Meeting"
  │
  ├── ctx.obj["twelve_hour"] = True   (from --time-format)
  │
  ├── parser.parse_time("2:30 PM")  →  time(14, 30)
  │
  ├── Alarm(hour=14, minute=30, label="Meeting")
  │     └── __post_init__() validates fields
  │
  ├── Storage.add(alarm)
  │     └── load_all() → append → save_all() (atomic write)
  │
  └── click.echo(alarm.display_time(twelve_hour=True))  →  "2:30 PM"
```

## Data flow: scheduler firing an alarm

```
alarm run --time-format 12h
  │
  ├── ctx.obj["twelve_hour"] = True
  ├── notifier = default_notifier(twelve_hour=True)
  │     └── CompositeNotifier([TerminalNotifier(twelve_hour=True), SoundNotifier()])
  │
  └── run_scheduler(storage, notifier, poll_interval=30)
        │
        └── Clock tick (every 30s)
              │
              ├── Storage.load_all()  →  list[Alarm]
              │
              ├── for each Alarm:
              │     should_fire(alarm, now)?
              │       ├── No  → skip
              │       └── Yes → Notifier.notify(alarm)
              │                   ├── TerminalNotifier: banner (12h) + bell
              │                   └── SoundNotifier: afplay / aplay / winsound
              │
              └── _on_fired(alarm, storage)
                    ├── recurring → no change (fires again tomorrow)
                    └── one-time  → alarm.enabled = False; Storage.update(alarm)
```

## Dependency graph

```
cli.py
  ├── models.py        (leaf)
  ├── parser.py        (leaf)
  ├── storage.py
  │     └── models.py
  ├── scheduler.py
  │     ├── models.py
  │     ├── storage.py
  │     └── notifier.py
  │           └── models.py
  ├── notifier.py
  └── logging_config.py  (leaf)
```

No circular dependencies. `models.py` is imported by four modules and has no
internal imports — it is deliberately kept as a leaf to avoid cycles.

## Testability design

Every module with non-trivial logic was designed for testability first:

| Module | Testability mechanism |
|---|---|
| `models.py` | `next_fire(now=)` and `snooze(now=)` accept injectable `now` |
| `parser.py` | Pure function; no state |
| `storage.py` | `Storage(path=)` accepts any `Path`; tests use `tmp_path` |
| `scheduler.py` | `ClockProtocol` injected via `clock=`; `should_fire()` is pure |
| `notifier.py` | `Notifier` is a Protocol; `RecordingNotifier` needs no inheritance |
| `cli.py` | `CliRunner` runs in-process; `--data-dir` + `--time-format` route to tmp storage and controlled format |

No test requires `mock.patch`, `freezegun`, or patching of `datetime.now`. This
is a deliberate constraint — tests that patch time are fragile because they
depend on the exact import path of `datetime` inside the production code.
