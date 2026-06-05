"""
Integration tests for the CLI via Click's CliRunner.

What we are testing — behaviour:
- `alarm set` creates an alarm and prints its id.
- `alarm set` with an invalid time exits non-zero with a useful message.
- `alarm list` shows alarms when they exist, and a helpful message when empty.
- `alarm delete` removes an alarm; non-existent id exits non-zero.
- `alarm enable` / `alarm disable` toggle enabled state.
- `alarm snooze` updates the alarm time.
- `alarm run` exits cleanly when no enabled alarms exist.
- Global --data-dir flag routes to the correct storage file.

Why CliRunner (not subprocess):
CliRunner runs the Click application in-process with captured stdout/stderr.
No subprocess means no PATH dependency, no install required, and tests run
in ~1ms each rather than ~100ms. The tradeoff: CliRunner does not test the
installed entry point, only the Python function. That is acceptable here.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner, Result

from alarm_clock.cli import main
from alarm_clock.storage import Storage

# ── Helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "alarm_data"
    d.mkdir()
    return d


def invoke(runner: CliRunner, data_dir: Path, *args: str) -> Result:
    """Convenience wrapper that always passes --data-dir."""
    return runner.invoke(main, ["--data-dir", str(data_dir), *args])


# ── alarm set ─────────────────────────────────────────────────────────────────


class TestSetCommand:
    def test_set_creates_alarm(self, runner: CliRunner, data_dir: Path) -> None:
        result = invoke(runner, data_dir, "set", "14:30")
        assert result.exit_code == 0
        assert "14:30" in result.output

    def test_set_shows_alarm_id(self, runner: CliRunner, data_dir: Path) -> None:
        result = invoke(runner, data_dir, "set", "14:30")
        assert result.exit_code == 0
        # Output should contain an 8-char hex id inside brackets
        assert "[" in result.output

    def test_set_with_label(self, runner: CliRunner, data_dir: Path) -> None:
        result = invoke(runner, data_dir, "set", "09:00", "--label", "Standup")
        assert result.exit_code == 0
        assert "Standup" in result.output

    def test_set_with_recurring_flag(self, runner: CliRunner, data_dir: Path) -> None:
        result = invoke(runner, data_dir, "set", "07:30", "--recurring")
        assert result.exit_code == 0
        storage = Storage(path=data_dir / "alarms.json")
        alarms = storage.load_all()
        assert alarms[0].recurring is True

    def test_set_persists_to_storage(self, runner: CliRunner, data_dir: Path) -> None:
        invoke(runner, data_dir, "set", "14:30", "--label", "Persist test")
        storage = Storage(path=data_dir / "alarms.json")
        alarms = storage.load_all()
        assert len(alarms) == 1
        assert alarms[0].label == "Persist test"
        assert alarms[0].hour == 14
        assert alarms[0].minute == 30

    def test_set_invalid_time_exits_nonzero(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = invoke(runner, data_dir, "set", "notaTime")
        assert result.exit_code != 0

    def test_set_invalid_time_shows_helpful_message(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = invoke(runner, data_dir, "set", "99:99")
        assert result.exit_code != 0
        assert "99:99" in result.output or "Error" in result.output

    def test_set_12h_am_format(self, runner: CliRunner, data_dir: Path) -> None:
        result = invoke(runner, data_dir, "set", "9:00 AM")
        assert result.exit_code == 0
        storage = Storage(path=data_dir / "alarms.json")
        assert storage.load_all()[0].hour == 9

    def test_set_12h_pm_format(self, runner: CliRunner, data_dir: Path) -> None:
        result = invoke(runner, data_dir, "set", "2:30 PM")
        assert result.exit_code == 0
        storage = Storage(path=data_dir / "alarms.json")
        assert storage.load_all()[0].hour == 14


# ── alarm list ────────────────────────────────────────────────────────────────


class TestListCommand:
    def test_list_empty_shows_helpful_message(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = invoke(runner, data_dir, "list")
        assert result.exit_code == 0
        assert "No alarms" in result.output

    def test_list_shows_existing_alarms(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        invoke(runner, data_dir, "set", "14:30", "--label", "Shown")
        result = invoke(runner, data_dir, "list")
        assert result.exit_code == 0
        assert "14:30" in result.output
        assert "Shown" in result.output

    def test_list_shows_multiple_alarms(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        invoke(runner, data_dir, "set", "07:00", "--label", "First")
        invoke(runner, data_dir, "set", "22:00", "--label", "Second")
        result = invoke(runner, data_dir, "list")
        assert "First" in result.output
        assert "Second" in result.output


# ── alarm delete ──────────────────────────────────────────────────────────────


class TestDeleteCommand:
    def test_delete_existing_alarm(self, runner: CliRunner, data_dir: Path) -> None:
        invoke(runner, data_dir, "set", "14:30")
        storage = Storage(path=data_dir / "alarms.json")
        alarm_id = storage.load_all()[0].id

        result = invoke(runner, data_dir, "delete", alarm_id)
        assert result.exit_code == 0
        assert storage.load_all() == []

    def test_delete_nonexistent_id_exits_nonzero(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = invoke(runner, data_dir, "delete", "nosuchid")
        assert result.exit_code != 0

    def test_delete_nonexistent_id_shows_error(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = invoke(runner, data_dir, "delete", "nosuchid")
        assert "nosuchid" in result.output or "Error" in result.output


# ── alarm enable / disable ────────────────────────────────────────────────────


class TestEnableDisableCommands:
    def _setup_alarm(self, runner: CliRunner, data_dir: Path) -> str:
        invoke(runner, data_dir, "set", "14:30")
        storage = Storage(path=data_dir / "alarms.json")
        return storage.load_all()[0].id

    def test_disable_alarm(self, runner: CliRunner, data_dir: Path) -> None:
        alarm_id = self._setup_alarm(runner, data_dir)
        result = invoke(runner, data_dir, "disable", alarm_id)
        assert result.exit_code == 0
        storage = Storage(path=data_dir / "alarms.json")
        assert storage.get(alarm_id).enabled is False  # type: ignore[union-attr]

    def test_enable_disabled_alarm(self, runner: CliRunner, data_dir: Path) -> None:
        alarm_id = self._setup_alarm(runner, data_dir)
        invoke(runner, data_dir, "disable", alarm_id)
        result = invoke(runner, data_dir, "enable", alarm_id)
        assert result.exit_code == 0
        storage = Storage(path=data_dir / "alarms.json")
        assert storage.get(alarm_id).enabled is True  # type: ignore[union-attr]

    def test_disable_already_disabled_is_idempotent(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        alarm_id = self._setup_alarm(runner, data_dir)
        invoke(runner, data_dir, "disable", alarm_id)
        result = invoke(runner, data_dir, "disable", alarm_id)
        assert result.exit_code == 0

    def test_enable_nonexistent_id_exits_nonzero(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = invoke(runner, data_dir, "enable", "nosuchid")
        assert result.exit_code != 0


# ── alarm snooze ──────────────────────────────────────────────────────────────


class TestSnoozeCommand:
    def test_snooze_re_enables_alarm(self, runner: CliRunner, data_dir: Path) -> None:
        invoke(runner, data_dir, "set", "08:00", "--snooze-minutes", "5")
        storage = Storage(path=data_dir / "alarms.json")
        alarm_id = storage.load_all()[0].id
        # Disable it first so we can prove snooze re-enables it
        invoke(runner, data_dir, "disable", alarm_id)

        result = invoke(runner, data_dir, "snooze", alarm_id)
        assert result.exit_code == 0

        updated = storage.get(alarm_id)
        assert updated is not None
        assert updated.enabled is True

    def test_snooze_advances_alarm_time(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        # Set alarm well in the past (00:01) so any snooze will produce a later time.
        # Snooze calls datetime.now() internally; we verify the stored time
        # changed from the original rather than asserting an exact value.
        invoke(runner, data_dir, "set", "00:01", "--snooze-minutes", "5")
        storage = Storage(path=data_dir / "alarms.json")
        alarm_id = storage.load_all()[0].id

        invoke(runner, data_dir, "snooze", alarm_id)

        updated = storage.get(alarm_id)
        assert updated is not None
        # Time must have advanced beyond 00:01
        assert (updated.hour, updated.minute) != (0, 1)

    def test_snooze_output_mentions_duration(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        invoke(runner, data_dir, "set", "08:00", "--snooze-minutes", "10")
        storage = Storage(path=data_dir / "alarms.json")
        alarm_id = storage.load_all()[0].id

        result = invoke(runner, data_dir, "snooze", alarm_id)
        assert result.exit_code == 0
        assert "+10 min" in result.output

    def test_snooze_output_respects_12h_format(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        invoke(runner, data_dir, "set", "08:00", "--snooze-minutes", "5")
        storage = Storage(path=data_dir / "alarms.json")
        alarm_id = storage.load_all()[0].id

        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "--time-format", "12h", "snooze", alarm_id],
        )
        assert result.exit_code == 0
        assert "AM" in result.output or "PM" in result.output

    def test_snooze_nonexistent_id_exits_nonzero(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = invoke(runner, data_dir, "snooze", "nosuchid")
        assert result.exit_code != 0


# ── alarm run ─────────────────────────────────────────────────────────────────


class TestRunCommand:
    def test_run_exits_cleanly_when_no_enabled_alarms(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = invoke(runner, data_dir, "run")
        assert result.exit_code == 0
        assert "No enabled alarms" in result.output

    def test_run_starts_scheduler_when_alarms_exist(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        invoke(runner, data_dir, "set", "14:30")

        # Patch run_scheduler so it returns immediately
        with patch("alarm_clock.cli.run_scheduler") as mock_run:
            mock_run.return_value = None
            result = invoke(runner, data_dir, "run")

        assert result.exit_code == 0
        mock_run.assert_called_once()


# ── --time-format ─────────────────────────────────────────────────────────────


class TestTimeFormat:
    def test_list_24h_default(self, runner: CliRunner, data_dir: Path) -> None:
        invoke(runner, data_dir, "set", "14:30", "--label", "Meeting")
        result = invoke(runner, data_dir, "list")
        assert result.exit_code == 0
        assert "14:30" in result.output

    def test_list_12h_format(self, runner: CliRunner, data_dir: Path) -> None:
        invoke(runner, data_dir, "set", "14:30", "--label", "Meeting")
        result = runner.invoke(
            main, ["--data-dir", str(data_dir), "--time-format", "12h", "list"]
        )
        assert result.exit_code == 0
        assert "2:30 PM" in result.output
        # 24h format must not appear in the time column
        assert "14:30" not in result.output

    def test_set_confirmation_respects_12h(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "--time-format", "12h", "set", "14:30"],
        )
        assert result.exit_code == 0
        assert "2:30 PM" in result.output

    def test_set_confirmation_default_24h(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        result = invoke(runner, data_dir, "set", "14:30")
        assert result.exit_code == 0
        assert "14:30" in result.output

    def test_time_format_case_insensitive(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        invoke(runner, data_dir, "set", "14:30")
        result = runner.invoke(
            main, ["--data-dir", str(data_dir), "--time-format", "12H", "list"]
        )
        assert result.exit_code == 0
        assert "PM" in result.output

    def test_run_passes_12h_flag_to_scheduler(
        self, runner: CliRunner, data_dir: Path
    ) -> None:
        invoke(runner, data_dir, "set", "14:30")
        with patch("alarm_clock.cli.default_notifier") as mock_notifier:
            mock_notifier.return_value.notify = lambda a: None
            with patch("alarm_clock.cli.run_scheduler"):
                runner.invoke(
                    main,
                    ["--data-dir", str(data_dir), "--time-format", "12h", "run"],
                )
        mock_notifier.assert_called_once_with(twelve_hour=True)


# ── --help ────────────────────────────────────────────────────────────────────


class TestHelpText:
    def test_root_help_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0

    def test_root_help_mentions_time_format(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--help"])
        assert "time-format" in result.output

    def test_set_help_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["set", "--help"])
        assert result.exit_code == 0
        assert "TIME" in result.output

    def test_list_help_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["list", "--help"])
        assert result.exit_code == 0
