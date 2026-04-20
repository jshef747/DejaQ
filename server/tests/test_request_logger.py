import asyncio
import sqlite3

import pytest

pytestmark = pytest.mark.no_model


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_stats.db")


@pytest.fixture
def logger(db_path, monkeypatch):
    monkeypatch.setenv("DEJAQ_STATS_DB", db_path)
    import importlib
    import app.config as cfg
    importlib.reload(cfg)
    # Patch the module-level path used by RequestLogger
    import app.services.request_logger as rl_mod
    importlib.reload(rl_mod)
    return rl_mod.RequestLogger(), db_path


class TestRequestLoggerInit:
    def test_creates_table(self, logger):
        rl, db_path = logger

        async def run():
            await rl.init()
            await rl.close()

        asyncio.run(run())

        con = sqlite3.connect(db_path)
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='requests'")
        assert cur.fetchone() is not None
        con.close()

    def test_idempotent_init(self, logger):
        rl, db_path = logger

        async def run():
            await rl.init()
            await rl.init()  # second call should not error
            await rl.close()

        asyncio.run(run())


class TestRequestLoggerLog:
    def test_cache_hit_row(self, logger):
        rl, db_path = logger

        async def run():
            await rl.init()
            await rl.log("acme", "engineering", 120, True, None, None)
            await rl.close()

        asyncio.run(run())

        con = sqlite3.connect(db_path)
        row = con.execute("SELECT org, department, latency_ms, cache_hit, difficulty, model_used FROM requests").fetchone()
        con.close()

        assert row == ("acme", "engineering", 120, 1, None, None)

    def test_easy_miss_row(self, logger):
        rl, db_path = logger

        async def run():
            await rl.init()
            await rl.log("acme", "support", 850, False, "easy", "llama-3.2-1b")
            await rl.close()

        asyncio.run(run())

        con = sqlite3.connect(db_path)
        row = con.execute("SELECT cache_hit, difficulty, model_used FROM requests").fetchone()
        con.close()

        assert row == (0, "easy", "llama-3.2-1b")

    def test_hard_miss_row(self, logger):
        rl, db_path = logger

        async def run():
            await rl.init()
            await rl.log("acme", "support", 2100, False, "hard", "gemini-2.5-flash")
            await rl.close()

        asyncio.run(run())

        con = sqlite3.connect(db_path)
        row = con.execute("SELECT difficulty, model_used FROM requests").fetchone()
        con.close()

        assert row == ("hard", "gemini-2.5-flash")

    def test_multiple_rows(self, logger):
        rl, db_path = logger

        async def run():
            await rl.init()
            await rl.log("acme", "eng", 100, True, None, None)
            await rl.log("acme", "eng", 200, False, "easy", "llama-3.2-1b")
            await rl.log("default", "default", 300, False, "hard", "gemini-2.5-flash")
            await rl.close()

        asyncio.run(run())

        con = sqlite3.connect(db_path)
        count = con.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
        con.close()
        assert count == 3

    def test_default_org_department(self, logger):
        rl, db_path = logger

        async def run():
            await rl.init()
            await rl.log("default", "default", 150, True, None, None)
            await rl.close()

        asyncio.run(run())

        con = sqlite3.connect(db_path)
        row = con.execute("SELECT org, department FROM requests").fetchone()
        con.close()
        assert row == ("default", "default")

    def test_log_before_init_does_not_crash(self, logger):
        rl, db_path = logger

        async def run():
            # No init() call — should silently no-op
            await rl.log("acme", "eng", 100, True, None, None)

        asyncio.run(run())  # must not raise


class TestStatsCLI:
    def _seed(self, db_path, rows):
        con = sqlite3.connect(db_path)
        con.execute("""CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, org TEXT NOT NULL, department TEXT NOT NULL,
            latency_ms INTEGER NOT NULL, cache_hit INTEGER NOT NULL,
            difficulty TEXT, model_used TEXT)""")
        con.executemany(
            "INSERT INTO requests (ts,org,department,latency_ms,cache_hit,difficulty,model_used) VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        con.commit()
        con.close()

    def test_no_db_exits_nonzero(self, tmp_path):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "cli.stats"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "DEJAQ_STATS_DB": str(tmp_path / "nonexistent.db")},
            cwd="/Users/jonathansheffer/Desktop/Coding/DejaQ/server",
        )
        assert result.returncode == 1
        assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()

    def test_empty_db_message(self, tmp_path):
        import subprocess, sys
        db_path = str(tmp_path / "empty.db")
        self._seed(db_path, [])
        result = subprocess.run(
            [sys.executable, "-m", "cli.stats"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "DEJAQ_STATS_DB": db_path},
            cwd="/Users/jonathansheffer/Desktop/Coding/DejaQ/server",
        )
        assert result.returncode == 0
        assert "no requests" in result.stdout.lower()

    def test_renders_rows(self, tmp_path):
        import subprocess, sys
        db_path = str(tmp_path / "stats.db")
        self._seed(db_path, [
            ("2026-04-20T10:00:00Z", "acme", "eng", 120, 1, None, None),
            ("2026-04-20T10:01:00Z", "acme", "eng", 850, 0, "easy", "llama-3.2-1b"),
            ("2026-04-20T10:02:00Z", "acme", "support", 95, 1, None, None),
        ])
        result = subprocess.run(
            [sys.executable, "-m", "cli.stats"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "DEJAQ_STATS_DB": db_path},
            cwd="/Users/jonathansheffer/Desktop/Coding/DejaQ/server",
        )
        assert result.returncode == 0
        out = result.stdout
        assert "acme" in out
        assert "eng" in out
        assert "suppo" in out  # Rich may truncate to "suppo…" in narrow terminals
        assert "TOTAL" in out

    def test_hit_rate_calculation(self, tmp_path):
        import subprocess, sys
        db_path = str(tmp_path / "stats.db")
        # 2 hits, 2 misses → 50%
        self._seed(db_path, [
            ("2026-04-20T10:00:00Z", "acme", "eng", 100, 1, None, None),
            ("2026-04-20T10:01:00Z", "acme", "eng", 100, 1, None, None),
            ("2026-04-20T10:02:00Z", "acme", "eng", 800, 0, "easy", "llama-3.2-1b"),
            ("2026-04-20T10:03:00Z", "acme", "eng", 800, 0, "hard", "gemini-2.5-flash"),
        ])
        result = subprocess.run(
            [sys.executable, "-m", "cli.stats"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "DEJAQ_STATS_DB": db_path},
            cwd="/Users/jonathansheffer/Desktop/Coding/DejaQ/server",
        )
        assert result.returncode == 0
        assert "50.0%" in result.stdout

    def test_tokens_saved_heuristic(self, tmp_path):
        import subprocess, sys
        db_path = str(tmp_path / "stats.db")
        # 3 cache hits → 3 × 150 = 450 tokens saved
        self._seed(db_path, [
            ("2026-04-20T10:00:00Z", "acme", "eng", 100, 1, None, None),
            ("2026-04-20T10:01:00Z", "acme", "eng", 100, 1, None, None),
            ("2026-04-20T10:02:00Z", "acme", "eng", 100, 1, None, None),
        ])
        result = subprocess.run(
            [sys.executable, "-m", "cli.stats"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "DEJAQ_STATS_DB": db_path},
            cwd="/Users/jonathansheffer/Desktop/Coding/DejaQ/server",
        )
        assert result.returncode == 0
        assert "450" in result.stdout
