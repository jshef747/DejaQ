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


def test_start_script_no_longer_references_removed_validator_env_var():
    """DEJAQ_VALIDATOR_ENABLED was removed from app/config.py and nothing reads
    it; start.sh must not document, prompt for, or export it as if it still
    did something. ("validator rejected" is an unrelated log-grep pattern for
    the actual cache-answer validator and is fine to keep.)"""
    contents = START_SCRIPT.read_text()
    assert "DEJAQ_VALIDATOR_ENABLED" not in contents
    assert "--validator" not in contents
    assert "--no-validator" not in contents


def test_dry_run_rejects_the_removed_validator_flag():
    result = _run_start("--dry-run", "--validator=off")

    assert result.returncode != 0


def test_dry_run_does_not_print_validator_env_var():
    result = _run_start("--dry-run", env={"DEJAQ_START_LOGS": "requests"})

    assert result.returncode == 0
    assert "DEJAQ_VALIDATOR_ENABLED" not in result.stdout


def test_start_script_log_grep_pattern_matches_decision_card_marker():
    """start.sh extracts the live log's decision-card lines by the literal
    marker app/utils/decision_card.py actually emits (CARD_MARKER). Renaming
    the marker without updating start.sh makes the requests log pane go
    silent with no error."""
    start_contents = START_SCRIPT.read_text()
    grep_match = re.search(r"grep --line-buffered -o '([^']+)'", start_contents)
    assert grep_match, "expected a --line-buffered grep -o pattern in start.sh"
    pattern = grep_match.group(1)

    decision_card = (ROOT_DIR / "server" / "app" / "utils" / "decision_card.py").read_text()
    marker_match = re.search(r'CARD_MARKER = "([^"]+)"', decision_card)
    assert marker_match, "expected CARD_MARKER to be defined in decision_card.py"
    assert marker_match.group(1) in pattern


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
