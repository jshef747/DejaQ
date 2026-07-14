import logging
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
    external_provider_used INTEGER NOT NULL DEFAULT 0
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


class RequestLogger:
    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(STATS_DB_PATH)
        await self._db.execute(_CREATE_REQUESTS_TABLE)
        await self._db.execute(_CREATE_FEEDBACK_TABLE)
        # Migrate existing tables with additive nullable/default columns.
        try:
            cols = [row[1] for row in await (await self._db.execute("PRAGMA table_info(requests)")).fetchall()]

            # Rename legacy 'org' column to 'workspace' if present (one-time migration).
            if "org" in cols and "workspace" not in cols:
                await self._db.execute("ALTER TABLE requests RENAME COLUMN org TO workspace")
                logger.info("Migrated requests.org → requests.workspace")

            request_columns = {
                "response_id": "TEXT",
                "source": "TEXT NOT NULL DEFAULT 'chat'",
                "interaction_id": "TEXT",
                "parent_interaction_id": "TEXT",
                "served_tier": "TEXT",
                "external_provider_used": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, definition in request_columns.items():
                if name not in cols:
                    await self._db.execute(f"ALTER TABLE requests ADD COLUMN {name} {definition}")

            feedback_cols = [
                row[1] for row in await (await self._db.execute("PRAGMA table_info(feedback_log)")).fetchall()
            ]
            # Rename legacy 'org' column in feedback_log too.
            if "org" in feedback_cols and "workspace" not in feedback_cols:
                await self._db.execute("ALTER TABLE feedback_log RENAME COLUMN org TO workspace")
                logger.info("Migrated feedback_log.org → feedback_log.workspace")

            if "interaction_id" not in feedback_cols:
                await self._db.execute("ALTER TABLE feedback_log ADD COLUMN interaction_id TEXT")
        except Exception:
            logger.warning("Could not migrate stats tables", exc_info=True)
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
                    external_provider_used
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ) -> None:
        if self._db is None:
            return
        ts = datetime.now(timezone.utc).isoformat()
        try:
            await self._db.execute(
                "INSERT INTO feedback_log (ts, response_id, workspace, department, rating, comment, interaction_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, response_id, workspace, department, rating, comment, interaction_id),
            )
            await self._db.commit()
        except Exception:
            logger.exception("Failed to write feedback log row")

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None


request_logger = RequestLogger()
