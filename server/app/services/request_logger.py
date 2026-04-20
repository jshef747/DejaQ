import logging
from datetime import datetime, timezone

import aiosqlite

from app.config import STATS_DB_PATH

logger = logging.getLogger("dejaq.request_logger")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    org         TEXT    NOT NULL,
    department  TEXT    NOT NULL,
    latency_ms  INTEGER NOT NULL,
    cache_hit   INTEGER NOT NULL,
    difficulty  TEXT,
    model_used  TEXT
)
"""


class RequestLogger:
    def __init__(self) -> None:
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(STATS_DB_PATH)
        await self._db.execute(_CREATE_TABLE)
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
    ) -> None:
        if self._db is None:
            return
        ts = datetime.now(timezone.utc).isoformat()
        try:
            await self._db.execute(
                "INSERT INTO requests (ts, org, department, latency_ms, cache_hit, difficulty, model_used) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, org, department, latency_ms, int(cache_hit), difficulty, model_used),
            )
            await self._db.commit()
        except Exception:
            logger.exception("Failed to write request log row")

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None


request_logger = RequestLogger()
