import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
START_SCRIPT = ROOT_DIR / "start.sh"
# The path as BASH must receive it. On Windows str(START_SCRIPT) is a
# backslash path, and bash consumes each backslash as an escape - the
# invocation then fails with "No such file or directory" on a mangled name
# and every assertion here reads as a start.sh bug rather than a path one.
# Git Bash accepts the forward-slash form of a drive path unchanged.
START_SCRIPT_ARG = START_SCRIPT.as_posix()


def _bash() -> str:
    """The bash these tests must run start.sh under.

    Plain "bash" is wrong on Windows. PATH resolution finds Git's *msys* binary
    (`Git/usr/bin/bash.exe`), which is meant to be run from inside an already
    mounted msys environment - launched cold from subprocess it resolves
    neither `C:/...` nor `/c/...` and reports the script as missing, exit 127.
    `Git/bin/bash.exe` is the wrapper that sets that environment up first, and
    it runs the script correctly.

    The Git root is found by walking up from wherever `git` lives rather than
    assuming a fixed depth: `git` resolves to `Git/mingw64/bin/git.exe` in a
    Git Bash shell and `Git/cmd/git.exe` from cmd, so no single `parents[n]`
    is right in both.

    Falls back to "bash" when no wrapper is found, so a machine with a real
    bash on PATH (WSL, a POSIX box) is unaffected.
    """
    if sys.platform != "win32":
        return "bash"
    roots = []
    git = shutil.which("git")
    if git:
        roots.extend(Path(git).resolve().parents)
    roots.append(Path(r"C:\Program Files\Git"))
    roots.append(Path(r"C:\Program Files (x86)\Git"))
    for root in roots:
        wrapper = root / "bin" / "bash.exe"
        if wrapper.is_file():
            return str(wrapper)
    return "bash"


BASH = _bash()


def _run_start(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = {
        **os.environ,
        "DEJAQ_STACK": "server",
        "DEJAQ_MODE": "in-process",
        **(env or {}),
    }
    return subprocess.run(
        [BASH, START_SCRIPT_ARG, *args],
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


def test_start_script_log_grep_pattern_matches_openai_compat_log_format():
    """start.sh greps the live log for the literal text openai_compat.py's
    'start ...' log line actually emits. Renaming the log format string
    without updating the grep pattern makes the log pane go silent with no
    error - see the log format string in app/routers/openai_compat.py."""
    start_contents = START_SCRIPT.read_text()
    grep_match = re.search(r'grep --line-buffered -E "([^"]+)"', start_contents)
    assert grep_match, "expected a --line-buffered grep pattern in start.sh"
    pattern = grep_match.group(1)

    openai_compat = (ROOT_DIR / "server" / "app" / "routers" / "openai_compat.py").read_text()
    assert re.search(pattern, 'router.openai_compat: start workspace=acme dept=default namespace=x model=y')
    assert '"start workspace=%s' in openai_compat


def test_terminal_log_formatter_adds_separator_without_rewriting_input():
    result = subprocess.run(
        [BASH, START_SCRIPT_ARG, "--format-log-lines"],
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
