"""
CLI entry point.

Design decisions
----------------
1. Click over argparse.
   Reason: Click's CliRunner makes integration testing trivial — no subprocess
   overhead, no sys.argv patching, output captured in memory. Click also composes
   subcommands cleanly (alarm set, alarm list, alarm run) and generates better
   --help output with less boilerplate. argparse requires manual subparser wiring
   that Click handles with decorators.

2. The CLI group passes a Storage instance via Click's context object (ctx.obj).
   Reason: --data-dir overrides the default storage path. Passing storage through
   ctx.obj means every subcommand gets the correct Storage instance regardless of
   where it was constructed. This is dependency injection without a DI framework.

3. Commands are thin. No business logic in CLI handlers.
   Reason: parsing + delegating is the CLI's job. Alarm creation, validation, and
   storage operations live in models.py and storage.py. This makes the business
   logic testable without the Click machinery and keeps the CLI layer easy to
   replace (e.g., with a TUI or REST API in the future).

4. The `run` command is blocking and foreground-only.
   Reason: a background daemon would require PID file management, systemd/launchd
   integration, or OS-specific APIs — none of which are in scope. The user runs
   `alarm run` in a terminal they keep open. This is the simplest correct model.

5. `set` is the command name but mapped to function `set_alarm`.
   Reason: `set` is a Python built-in. Naming the function `set` would shadow it.
   Click maps the command name to the function name by default, so we pass
   name="set" explicitly.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from alarm_clock.logging_config import configure_logging
from alarm_clock.models import Alarm
from alarm_clock.notifier import default_notifier
from alarm_clock.parser import parse_time
from alarm_clock.scheduler import run_scheduler
from alarm_clock.storage import Storage

logger = logging.getLogger(__name__)


# ── Root command group ────────────────────────────────────────────────────────


@click.group()
@click.version_option(package_name="alarm-clock")
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable debug-level logging to ~/.alarm_clock/alarm.log.",
)
@click.option(
    "--data-dir",
    type=click.Path(path_type=Path),
    default=None,
    metavar="DIR",
    help="Directory for alarm data. Default: ~/.alarm_clock.",
)
@click.option(
    "--time-format",
    type=click.Choice(["12h", "24h"], case_sensitive=False),
    default="24h",
    show_default=True,
    help="Display times in 12-hour (2:30 PM) or 24-hour (14:30) format.",
)
@click.pass_context
def main(ctx: click.Context, verbose: bool, data_dir: Path | None, time_format: str) -> None:
    """
    alarm-clock — A terminal alarm clock.

    \b
    Typical workflow:
      alarm set 07:30 --label "Wake up" --recurring
      alarm list
      alarm run
    """
    configure_logging(verbose=verbose)
    ctx.ensure_object(dict)

    storage_path = (
        (data_dir / "alarms.json")
        if data_dir is not None
        else Path.home() / ".alarm_clock" / "alarms.json"
    )
    ctx.obj["storage"] = Storage(path=storage_path)
    ctx.obj["twelve_hour"] = (time_format == "12h")


# ── set ───────────────────────────────────────────────────────────────────────


@main.command(name="set")
@click.argument("time_str", metavar="TIME")
@click.option(
    "--label", "-l",
    default="Alarm",
    show_default=True,
    help="Human-readable name for this alarm.",
)
@click.option(
    "--recurring", "-r",
    is_flag=True,
    default=False,
    help="Repeat the alarm at the same time every day.",
)
@click.option(
    "--snooze-minutes", "-s",
    default=5,
    show_default=True,
    type=click.IntRange(1, 60),
    help="Snooze duration in minutes (1–60).",
)
@click.pass_context
def set_alarm(
    ctx: click.Context,
    time_str: str,
    label: str,
    recurring: bool,
    snooze_minutes: int,
) -> None:
    """
    Set a new alarm.

    TIME accepts 24-hour (14:30) and 12-hour (2:30 PM / 2:30PM) formats.

    \b
    Examples:
      alarm set 07:30
      alarm set "7:30 AM" --label "Morning run" --recurring
      alarm set 22:00 --label "Sleep" --snooze-minutes 10
    """
    storage: Storage = ctx.obj["storage"]

    try:
        parsed = parse_time(time_str)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    try:
        alarm = Alarm(
            hour=parsed.hour,
            minute=parsed.minute,
            label=label,
            recurring=recurring,
            snooze_minutes=snooze_minutes,
        )
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc

    storage.add(alarm)

    twelve_hour: bool = ctx.obj["twelve_hour"]
    recur_str = " (daily)" if recurring else ""
    click.echo(
        f"✓ Alarm set: [{alarm.id}] {alarm.display_time(twelve_hour)}{recur_str} — {alarm.label}"
    )
    click.echo("  Start the scheduler with: alarm run")


# ── list ──────────────────────────────────────────────────────────────────────


@main.command(name="list")
@click.pass_context
def list_alarms(ctx: click.Context) -> None:
    """List all alarms."""
    storage: Storage = ctx.obj["storage"]
    alarms = storage.load_all()

    if not alarms:
        click.echo("No alarms. Use `alarm set TIME` to create one.")
        return

    twelve_hour: bool = ctx.obj["twelve_hour"]
    # 12h times ("2:30 PM") are 7 chars; 24h ("14:30") are 5. Use 10 for both.
    time_col = 10
    header = f"\n{'ID':<10}{'TIME':<{time_col}}{'RECURRING':<12}{'SNOOZE':<9}{'STATUS':<10}LABEL"
    click.echo(header)
    click.echo("─" * 64)
    for alarm in alarms:
        status = "enabled " if alarm.enabled else "disabled"
        recur = "daily" if alarm.recurring else "once"
        snooze = f"{alarm.snooze_minutes}m"
        click.echo(
            f"{alarm.id:<10}{alarm.display_time(twelve_hour):<{time_col}}{recur:<12}"
            f"{snooze:<9}{status:<10}{alarm.label}"
        )
    click.echo()


# ── delete ────────────────────────────────────────────────────────────────────


@main.command()
@click.argument("alarm_id")
@click.pass_context
def delete(ctx: click.Context, alarm_id: str) -> None:
    """Delete an alarm permanently."""
    storage: Storage = ctx.obj["storage"]
    if not storage.remove(alarm_id):
        raise click.ClickException(
            f"No alarm found with id '{alarm_id}'. "
            f"Use `alarm list` to see available ids."
        )
    click.echo(f"✓ Alarm {alarm_id} deleted.")


# ── enable / disable ──────────────────────────────────────────────────────────


@main.command()
@click.argument("alarm_id")
@click.pass_context
def enable(ctx: click.Context, alarm_id: str) -> None:
    """Enable a previously disabled alarm."""
    storage: Storage = ctx.obj["storage"]
    alarm = storage.get(alarm_id)
    if alarm is None:
        raise click.ClickException(f"No alarm found with id '{alarm_id}'.")
    if alarm.enabled:
        click.echo(f"Alarm {alarm_id} is already enabled.")
        return
    alarm.enabled = True
    storage.update(alarm)
    click.echo(f"✓ Alarm {alarm_id} enabled.")


@main.command()
@click.argument("alarm_id")
@click.pass_context
def disable(ctx: click.Context, alarm_id: str) -> None:
    """Disable an alarm without deleting it."""
    storage: Storage = ctx.obj["storage"]
    alarm = storage.get(alarm_id)
    if alarm is None:
        raise click.ClickException(f"No alarm found with id '{alarm_id}'.")
    if not alarm.enabled:
        click.echo(f"Alarm {alarm_id} is already disabled.")
        return
    alarm.enabled = False
    storage.update(alarm)
    click.echo(f"✓ Alarm {alarm_id} disabled.")


# ── snooze ────────────────────────────────────────────────────────────────────


@main.command()
@click.argument("alarm_id")
@click.pass_context
def snooze(ctx: click.Context, alarm_id: str) -> None:
    """
    Snooze an alarm by its configured snooze duration.

    Updates the alarm's time to (now + snooze_minutes) and re-enables it.
    For recurring alarms, only the next fire is delayed; the daily schedule
    resumes the following day at the original time.
    """
    storage: Storage = ctx.obj["storage"]
    alarm = storage.get(alarm_id)
    if alarm is None:
        raise click.ClickException(f"No alarm found with id '{alarm_id}'.")

    twelve_hour: bool = ctx.obj["twelve_hour"]
    snoozed_until = alarm.snooze()
    alarm.hour = snoozed_until.hour
    alarm.minute = snoozed_until.minute
    alarm.enabled = True
    storage.update(alarm)

    click.echo(
        f"✓ Alarm {alarm_id} snoozed until {alarm.display_time(twelve_hour)} "
        f"(+{alarm.snooze_minutes} min)."
    )


# ── run ───────────────────────────────────────────────────────────────────────


@main.command()
@click.option(
    "--poll-interval",
    default=30,
    show_default=True,
    type=click.IntRange(1, 300),
    help="Seconds between alarm checks.",
)
@click.pass_context
def run(ctx: click.Context, poll_interval: int) -> None:
    """
    Start the alarm scheduler (foreground, blocking).

    Checks for due alarms every POLL_INTERVAL seconds. Press Ctrl+C to stop.
    Run this in a terminal you will keep open.
    """
    storage: Storage = ctx.obj["storage"]
    alarms = storage.load_all()
    enabled = [a for a in alarms if a.enabled]

    if not enabled:
        click.echo(
            "No enabled alarms. Use `alarm set TIME` to add one, then run again.",
            err=False,
        )
        sys.exit(0)

    twelve_hour: bool = ctx.obj["twelve_hour"]
    notifier = default_notifier(twelve_hour=twelve_hour)
    run_scheduler(
        storage=storage,
        notifier=notifier,
        poll_interval=poll_interval,
    )
