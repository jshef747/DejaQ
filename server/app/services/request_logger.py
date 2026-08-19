import logging
import sqlite3
from datetime import datetime, timezone

import aiosqlite

from app.config import STATS_DB_PATH

logger = logging.getLogger("dejaq.request_logger")

_CREATE_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    workspace   TEXT    NOT NULL,
    department  TEXT    NOT NULL,
    latency_ms  INTEGER NOT NULL,
    cache_hit   INTEGER NOT NULL,
    difficulty  TEXT,
    model_used  TEXT,
    response_id TEXT,
    source      TEXT    NOT NULL DEFAULT 'chat',
    interaction_id TEXT,
    parent_interaction_id TEXT,
    served_tier TEXT,
    external_provider_used INTEGER NOT NULL DEFAULT 0,
    finish_reason TEXT
)
"""

_CREATE_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS feedback_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    response_id TEXT    NOT NULL,
    workspace   TEXT    NOT NULL,
    department  TEXT    NOT NULL,
    rating      TEXT    NOT NULL,
    comment     TEXT,
    interaction_id TEXT
)
"""

# Additive columns applied to an existing table by ensure_stats_schema below.
# One source of truth: the writer (RequestLogger) and every direct sqlite3
# reader of this DB (stats_service, feedback_service, the `dejaq-admin` CLI
# behind them) run the same list, so a reader can never meet a schema the
# server happens not to have upgraded yet.
_REQUEST_COLUMNS = {
    "response_id": "TEXT",
    "source": "TEXT NOT NULL DEFAULT 'chat'",
    "interaction_id": "TEXT",
    "parent_interaction_id": "TEXT",
    "served_tier": "TEXT",
    "external_provider_used": "INTEGER NOT NULL DEFAULT 0",
    "finish_reason": "TEXT",
}

_FEEDBACK_COLUMNS = {
    "interaction_id": "TEXT",
    # 1 when the positive rating came from Edit & Save rather than a plain
    # thumbs-up, so the two can be told apart in the feedback log.
    "edited": "INTEGER NOT NULL DEFAULT 0",
}

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts)",
    "CREATE INDEX IF NOT EXISTS idx_requests_workspace_department_ts ON requests(workspace, department, ts)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_ts_id ON feedback_log(ts, id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_workspace_department ON feedback_log(workspace, department)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_response_id ON feedback_log(response_id)",
    "CREATE INDEX IF NOT EXISTS idx_requests_interaction_id ON requests(interaction_id)",
    "CREATE INDEX IF NOT EXISTS idx_requests_source ON requests(source)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_interaction_id ON feedback_log(interaction_id)",
)


def _migrate_table(con: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    cols = [row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()]

    # Rename legacy 'org' column to 'workspace' if present (one-time migration).
    if "org" in cols and "workspace" not in cols:
        con.execute(f"ALTER TABLE {table} RENAME COLUMN org TO workspace")
        logger.info("Migrated %s.org → %s.workspace", table, table)

    for name, definition in columns.items():
        if name not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def ensure_stats_schema(con: sqlite3.Connection) -> None:
    """Create the stats tables and add any additive column still missing.

    Idempotent and cheap - one PRAGMA per table, an ALTER only for what is
    absent - so any direct sqlite3 reader of this DB can call it on connect
    rather than depending on the FastAPI lifespan having run first.
    """
    con.execute(_CREATE_REQUESTS_TABLE)
    con.execute(_CREATE_FEEDBACK_TABLE)
    _migrate_table(con, "requests", _REQUEST_COLUMNS)
    _migrate_table(con, "feedback_log", _FEEDBACK_COLUMNS)
    con.commit()


class RequestLogger:
    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        try:
            con = sqlite3.connect(STATS_DB_PATH)
            try:
                ensure_stats_schema(con)
            finally:
                con.close()
        except Exception:
            logger.warning("Could not migrate stats tables", exc_info=True)
        self._db = await aiosqlite.connect(STATS_DB_PATH)
        for statement in _CREATE_INDEXES:
            await self._db.execute(statement)
        await self._db.commit()
        logger.info("RequestLogger initialized at %s", STATS_DB_PATH)

    async def log(
        self,
        workspace: str,
        department: str,
        latency_ms: int,
        cache_hit: bool,
        difficulty: str | None,
        model_used: str | None,
        response_id: str | None = None,
        *,
        source: str = "chat",
        interaction_id: str | None = None,
        parent_interaction_id: str | None = None,
        served_tier: str | None = None,
        external_provider_used: bool = False,
        # None for a cache hit: adjust()'s own truncation guard already falls
        # back to the complete cached answer before anything is served, so a
        # hit is never a cut-off text and has nothing to report here (see
        # ChatPipelineResult.finish_reason in openai_compat.py). "length" on a
        # miss/escalation means the generator's own signal reported
        # truncation - the store guard then correctly skipped caching it, so
        # this is the only place that failure is visible at all.
        finish_reason: str | None = None,
    ) -> None:
        if self._db is None:
            return
        ts = datetime.now(timezone.utc).isoformat()
        try:
            await self._db.execute(
                """
                INSERT INTO requests (
                    ts,
                    workspace,
                    department,
                    latency_ms,
                    cache_hit,
                    difficulty,
                    model_used,
                    response_id,
                    source,
                    interaction_id,
                    parent_interaction_id,
                    served_tier,
                    external_provider_used,
                    finish_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    workspace,
                    department,
                    latency_ms,
                    int(cache_hit),
                    difficulty,
                    model_used,
                    response_id,
                    source,
                    interaction_id,
                    parent_interaction_id,
                    served_tier,
                    int(external_provider_used),
                    finish_reason,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.exception("Failed to write request log row")

    async def log_feedback(
        self,
        response_id: str,
        workspace: str,
        department: str,
        rating: str,
        comment: str | None,
        *,
        interaction_id: str | None = None,
        edited: bool = False,
    ) -> None:
        if self._db is None:
            return
        ts = datetime.now(timezone.utc).isoformat()
        try:
            await self._db.execute(
                "INSERT INTO feedback_log (ts, response_id, workspace, department, rating, comment, interaction_id, edited) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, response_id, workspace, department, rating, comment, interaction_id, int(edited)),
            )
            await self._db.commit()
        except Exception:
            logger.exception("Failed to write feedback log row")

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None


request_logger = RequestLogger()
