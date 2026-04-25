import logging
from datetime import datetime, timezone

import aiosqlite

from app.config import STATS_DB_PATH

logger = logging.getLogger("dejaq.request_logger")

_CREATE_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    org         TEXT    NOT NULL,
    department  TEXT    NOT NULL,
    latency_ms  INTEGER NOT NULL,
    cache_hit   INTEGER NOT NULL,
    difficulty  TEXT,
    model_used  TEXT,
    response_id TEXT
)
"""

_CREATE_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS feedback_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    response_id TEXT    NOT NULL,
    org         TEXT    NOT NULL,
    department  TEXT    NOT NULL,
    rating      TEXT    NOT NULL,
    comment     TEXT
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests(ts)",
    "CREATE INDEX IF NOT EXISTS idx_requests_org_department_ts ON requests(org, department, ts)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_ts_id ON feedback_log(ts, id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_org_department ON feedback_log(org, department)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_log_response_id ON feedback_log(response_id)",
)


class RequestLogger:
    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(STATS_DB_PATH)
        await self._db.execute(_CREATE_REQUESTS_TABLE)
        await self._db.execute(_CREATE_FEEDBACK_TABLE)
        for statement in _CREATE_INDEXES:
            await self._db.execute(statement)
        # Migrate existing requests table — add response_id if missing
        try:
            cols = [row[1] for row in await (await self._db.execute("PRAGMA table_info(requests)")).fetchall()]
            if "response_id" not in cols:
                await self._db.execute("ALTER TABLE requests ADD COLUMN response_id TEXT")
        except Exception:
            logger.warning("Could not migrate requests table", exc_info=True)
        await self._db.commit()
        logger.info("RequestLogger initialized at %s", STATS_DB_PATH)

    async def log(
        self,
        org: str,
        department: str,
        latency_ms: int,
        cache_hit: bool,
        difficulty: str | None,
        model_used: str | None,
        response_id: str | None = None,
    ) -> None:
        if self._db is None:
            return
        ts = datetime.now(timezone.utc).isoformat()
        try:
            await self._db.execute(
                "INSERT INTO requests (ts, org, department, latency_ms, cache_hit, difficulty, model_used, response_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, org, department, latency_ms, int(cache_hit), difficulty, model_used, response_id),
            )
            await self._db.commit()
        except Exception:
            logger.exception("Failed to write request log row")

    async def log_feedback(
        self,
        response_id: str,
        org: str,
        department: str,
        rating: str,
        comment: str | None,
    ) -> None:
        if self._db is None:
            return
        ts = datetime.now(timezone.utc).isoformat()
        try:
            await self._db.execute(
                "INSERT INTO feedback_log (ts, response_id, org, department, rating, comment) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ts, response_id, org, department, rating, comment),
            )
            await self._db.commit()
        except Exception:
            logger.exception("Failed to write feedback log row")

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None


request_logger = RequestLogger()
