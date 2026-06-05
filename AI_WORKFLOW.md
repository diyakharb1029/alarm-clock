# AI-Assisted Development Workflow

How I used Claude during this project, what it got wrong, and what I had to fix.

---

## Approach

Used Claude Sonnet as a fast first-drafter for every module. Reviewed every output before using it. Most sessions needed at least one meaningful correction — the bugs below are real, not illustrative.

---

## Session 1 — pyproject.toml and project scaffold

**Prompt (paraphrased):** Modern Python project, alarm-clock CLI, hatchling backend, click + pytest + ruff + mypy, dev extras.

**What happened:**
Got setuptools back, not hatchling. Also got a `setup.cfg` I didn't ask for. Classic — AI defaults to what's most common in the training data, not what's current best practice.

**What I changed:**
- Swapped backend to hatchling, deleted setup.cfg
- Added pytest-cov (wasn't included)
- Made ruff lint rules explicit (`select = ["E", "F", "I", ...]`). The generated config had no select list, which means "lint everything" — too noisy on a fresh project.

---

## Session 2 — models.py

**Prompt:** Dataclass for Alarm with fields id/hour/minute/label/recurring/snooze_minutes/enabled/created_at. Validation in `__post_init__`. Methods: `wall_time` property, `next_fire(now)`, `snooze(now)`, `to_dict`, `from_dict`, `__str__`. Type hints everywhere.

**What came back:** Structurally correct but had two actual bugs.

**Bug 1 — untestable `next_fire`:**
Generated version used `datetime.now()` internally with no parameter:
```python
def next_fire(self) -> datetime:
    candidate = datetime.combine(datetime.now().date(), self.wall_time)
```
Any test of this would need to patch `datetime.now`. That's the exact thing I wanted to avoid — the whole point of an injectable clock is that tests don't need to patch global state. Fixed by adding `now: datetime | None = None`.

**Bug 2 — `from_dict` would crash on old alarm files:**
Generated version used `data["label"]` — a hard KeyError if the field is missing. If I ever add a field and someone has an existing alarm file without it, the whole alarm store becomes unreadable. Changed all optional fields to `data.get("field", default)`.

The `__str__` also didn't show disabled/recurring state. Minor but visible in `alarm list`.

---

## Session 3 — parser.py

**Prompt:** `parse_time(value: str) -> datetime.time`. Accept 24h HH:MM, 24h with seconds, 12h with/without space, hour-only 12h. Try format strings in order. Raise `ValueError` with a useful message. No dateutil.

**What came back:** Mostly fine. Two usability issues.

**Issue 1 — bad error message:**
```python
raise ValueError(f"Invalid time format: {value}")
```
This tells the user what's wrong, not how to fix it. Changed to include accepted formats and examples in the message.

**Issue 2 — didn't strip whitespace:**
`parse_time("  14:30  ")` raised ValueError. Added `cleaned = value.strip()` before the format loop. The shell passes quoted args with surrounding whitespace sometimes.

---

## Session 4 — scheduler.py

This was the most productive session and had the most consequential bug.

**Prompt:** Polling scheduler, injectable ClockProtocol, 30s default interval, dedup firings within same minute, disable one-time alarms post-fire, handle KeyboardInterrupt. Separate `should_fire()` function.

**What came back:** Structurally what I wanted. Two real problems.

**Bug 1 — `threading.Event` for deduplication:**
Generated a `threading.Event` to track fired alarms. No threading anywhere in the codebase, no reason to introduce it. Replaced with a plain `set[str]` that resets when the minute changes. Less impressive-looking, more correct.

**Bug 2 — `should_fire()` would break recurring alarms (non-obvious):**
```python
def should_fire(alarm: Alarm, now: datetime) -> bool:
    return alarm.enabled and alarm.next_fire() <= now
```
This looks right. It's wrong. `next_fire()` returns a datetime — a date + time. A recurring alarm that fired yesterday has a `next_fire()` of *today*. But the comparison is `next_fire() <= now`, which checks date too. If `now` is 14:29, `next_fire()` returns today at 14:30, and 14:30 <= 14:29 is False — correct. But what about the edge case where `next_fire()` returns tomorrow, because today's time already passed? Then the alarm *never* fires again until the next day's poll hits exactly the right window.

The real issue: using `next_fire()` ties the firing logic to date arithmetic, when all we actually need is "is the current hour:minute within 60 seconds of the alarm's scheduled hour:minute?" Changed to compare hour and minute independently, with a `FIRE_WINDOW_SECONDS` tolerance.

**Also:** The clock was defined as a plain class, not a Protocol. Changed to Protocol so test doubles don't need to inherit.

---

## Session 5 — test files

**Prompt:** pytest tests for all modules. Behavior tests, not implementation tests. Use the injectable clock for scheduler tests, not mock.patch.

**What came back:** Happy-path coverage was solid. Missing three things I caught in review:

**Gap 1 — no 12:00 AM / 12:00 PM test for parser:**
These are the two most common 12h format errors (noon vs midnight, 12 vs 0). Not in the generated output. Added `test_noon_12pm` and `test_midnight_12am`.

**Gap 2 — scheduler tests used mock.patch anyway:**
Despite the explicit instruction, the generated scheduler tests patched `datetime.now`. That's the pattern I'd specifically asked to avoid. Replaced all of them with `ControlledClock`.

**Gap 3 — no corrupt-file test for storage:**
"Returns [] on parse error" is a documented behavior choice. If it's not tested, it's not guaranteed. Added `test_returns_empty_list_for_corrupt_json`.

---

## Session 6 — 12h/24h time format feature

Added after initial implementation. User preference: display times in either 24-hour (default) or 12-hour format.

**Approach:** Global `--time-format 12h|24h` flag on the CLI group, stored in `ctx.obj`, threaded through to `display_time()` calls and `TerminalNotifier`.

**What AI generated:** Reasonable overall structure. One bug I introduced myself.

**Bug I introduced (caught in test writing):**
For the "fired at" time in `TerminalNotifier.notify()`, I wrote:
```python
now.strftime("%-I:%M:%S %p")
```
`%-I` removes leading zero from the hour. It's a GNU strftime extension — works on Linux and macOS via the C library, does not work on Windows. The `SoundNotifier` in the same file already has explicit Windows handling (`winsound`), so this inconsistency would be obvious to any reviewer.

Caught while writing `test_notifier.py`. Fixed with a small private function that does the same thing portably:
```python
def _format_fired_time(dt: datetime, *, twelve_hour: bool) -> str:
    if twelve_hour:
        h = dt.hour % 12 or 12
        period = "AM" if dt.hour < 12 else "PM"
        return f"{h}:{dt.minute:02d}:{dt.second:02d} {period}"
    return dt.strftime("%H:%M:%S")
```
Same logic already used in `display_time()`. Should have used it from the start.

---

## What I'd do differently

**Write tests before sending the implementation prompt.** The `should_fire()` correctness bug would have been obvious if I'd written the test cases first — I'd have immediately asked "what does next_fire() return if the alarm is recurring and already fired today?" and caught the design flaw before writing the code.

**Be more specific in prompts about what not to do.** "Use an injectable clock" in the scheduler prompt still produced a `mock.patch` in the test output. Should have been "do not use mock.patch anywhere in the scheduler tests — use the ControlledClock pattern."

**Don't assume the first draft handles platform differences.** The `%-I` bug is the second time platform-specific output slipped through (the first was SoundNotifier needing explicit Windows handling). AI defaults to Linux/macOS behavior. Always check cross-platform assumptions manually.
