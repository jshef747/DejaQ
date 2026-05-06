import os
import re
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
START_SCRIPT = ROOT_DIR / "start.sh"


def _run_start(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = {
        **os.environ,
        "DEJAQ_STACK": "server",
        "DEJAQ_MODE": "in-process",
        **(env or {}),
    }
    return subprocess.run(
        ["bash", str(START_SCRIPT), *args],
        cwd=ROOT_DIR,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_dry_run_uses_timestamped_logs_directory_for_request_logs():
    result = _run_start("--dry-run", env={"DEJAQ_START_LOGS": "requests"})

    assert result.returncode == 0
    assert "Log mode: requests" in result.stdout
    assert re.search(r"Logs:\s+.*/logs/\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}/", result.stdout)


def test_dry_run_accepts_full_service_log_mode():
    result = _run_start("--dry-run", env={"DEJAQ_START_LOGS": "all"})

    assert result.returncode == 0
    assert "Log mode: all" in result.stdout


def test_invalid_log_mode_fails_before_starting_services():
    result = _run_start("--dry-run", env={"DEJAQ_START_LOGS": "redis"})

    assert result.returncode == 1
    assert "Invalid log mode" in result.stderr


def test_terminal_log_formatter_adds_separator_without_rewriting_input():
    result = subprocess.run(
        ["bash", str(START_SCRIPT), "--format-log-lines"],
        cwd=ROOT_DIR,
        input="first log\nsecond log\n",
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.count("────────────────────────────────────────────────────────────────────────") == 2
    assert "first log" in result.stdout
    assert "second log" in result.stdout
