from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import aiosqlite

from app.config import STATS_DB_PATH

logger = logging.getLogger("dejaq.response_registry")

ServedTier = Literal["cache", "local", "external"]

_CREATE_RESPONSE_INTERACTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS response_interactions (
    interaction_id       TEXT PRIMARY KEY,
    created_at           TEXT    NOT NULL,
    workspace_id         INTEGER,
    workspace_slug       TEXT    NOT NULL,
    department           TEXT    NOT NULL,
    cache_namespace      TEXT    NOT NULL,
    served_tier          TEXT    NOT NULL,
    response_id          TEXT,
    message_hash         TEXT    NOT NULL,
    escalation_attempted INTEGER NOT NULL DEFAULT 0,
    escalation_attempted_at TEXT
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_response_interactions_workspace_dept ON response_interactions(workspace_id, workspace_slug, department)",
    "CREATE INDEX IF NOT EXISTS idx_response_interactions_response_id ON response_interactions(response_id)",
    "CREATE INDEX IF NOT EXISTS idx_response_interactions_created_at ON response_interactions(created_at)",
)


@dataclass(frozen=True)
class ResponseInteraction:
    interaction_id: str
    workspace_id: int | None
    workspace_slug: str
    department: str
    cache_namespace: str
    served_tier: ServedTier
    response_id: str | None
    message_hash: str
    created_at: str
    escalation_attempted: bool
    escalation_attempted_at: str | None


def _message_to_dict(message: object) -> dict[str, object]:
    if hasattr(message, "model_dump"):
        dumped = message.model_dump()
    elif isinstance(message, dict):
        dumped = dict(message)
    else:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        dumped = {"role": role, "content": content}
    return {
        "role": dumped.get("role"),
        "content": dumped.get("content"),
    }


def compute_messages_hash(messages: list[object]) -> str:
    canonical = [_message_to_dict(message) for message in messages]
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_interaction_id() -> str:
    return "int_" + uuid.uuid4().hex


class ResponseRegistry:
    def __init__(self, db_path: str = STATS_DB_PATH) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        if self._db is not None:
            return
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute(_CREATE_RESPONSE_INTERACTIONS_TABLE)
        # Migrate legacy org_id/org_slug columns to workspace_id/workspace_slug.
        try:
            cursor = await self._db.execute("PRAGMA table_info(response_interactions)")
            cols = [row[1] for row in await cursor.fetchall()]
            if "org_id" in cols and "workspace_id" not in cols:
                await self._db.execute(
                    "ALTER TABLE response_interactions RENAME COLUMN org_id TO workspace_id"
                )
                logger.info("Migrated response_interactions.org_id → workspace_id")
            if "org_slug" in cols and "workspace_slug" not in cols:
                await self._db.execute(
                    "ALTER TABLE response_interactions RENAME COLUMN org_slug TO workspace_slug"
                )
                logger.info("Migrated response_interactions.org_slug → workspace_slug")
        except Exception:
            logger.warning("Could not migrate response_interactions columns", exc_info=True)
        for statement in _CREATE_INDEXES:
            await self._db.execute(statement)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def register(
        self,
        *,
        workspace_id: int | None,
        workspace_slug: str,
        department: str,
        cache_namespace: str,
        served_tier: ServedTier,
        response_id: str | None,
        messages: list[object],
        interaction_id: str | None = None,
    ) -> ResponseInteraction:
        if self._db is None:
            raise RuntimeError("ResponseRegistry is not initialized")
        if served_tier not in {"cache", "local", "external"}:
            raise ValueError(f"Invalid served_tier: {served_tier}")

        record_id = interaction_id or new_interaction_id()
        created_at = datetime.now(timezone.utc).isoformat()
        message_hash = compute_messages_hash(messages)
        await self._db.execute(
            """
            INSERT INTO response_interactions (
                interaction_id,
                created_at,
                workspace_id,
                workspace_slug,
                department,
                cache_namespace,
                served_tier,
                response_id,
                message_hash,
                escalation_attempted,
                escalation_attempted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
            """,
            (
                record_id,
                created_at,
                workspace_id,
                workspace_slug,
                department,
                cache_namespace,
                served_tier,
                response_id,
                message_hash,
            ),
        )
        await self._db.commit()
        return ResponseInteraction(
            interaction_id=record_id,
            workspace_id=workspace_id,
            workspace_slug=workspace_slug,
            department=department,
            cache_namespace=cache_namespace,
            served_tier=served_tier,
            response_id=response_id,
            message_hash=message_hash,
            created_at=created_at,
            escalation_attempted=False,
            escalation_attempted_at=None,
        )

    async def get(self, interaction_id: str) -> ResponseInteraction | None:
        if self._db is None:
            raise RuntimeError("ResponseRegistry is not initialized")
        cursor = await self._db.execute(
            """
            SELECT
                interaction_id,
                workspace_id,
                workspace_slug,
                department,
                cache_namespace,
                served_tier,
                response_id,
                message_hash,
                created_at,
                escalation_attempted,
                escalation_attempted_at
            FROM response_interactions
            WHERE interaction_id = ?
            """,
            (interaction_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return ResponseInteraction(
            interaction_id=row[0],
            workspace_id=row[1],
            workspace_slug=row[2],
            department=row[3],
            cache_namespace=row[4],
            served_tier=row[5],
            response_id=row[6],
            message_hash=row[7],
            created_at=row[8],
            escalation_attempted=bool(row[9]),
            escalation_attempted_at=row[10],
        )

    async def validate_owner(
        self,
        interaction_id: str,
        *,
        workspace_id: int | None,
        workspace_slug: str,
        department: str,
    ) -> ResponseInteraction | None:
        interaction = await self.get(interaction_id)
        if interaction is None:
            return None
        if workspace_id is not None and interaction.workspace_id != workspace_id:
            return None
        if interaction.workspace_slug != workspace_slug:
            return None
        if interaction.department != department:
            return None
        return interaction

    async def acquire_escalation(self, interaction_id: str) -> bool:
        if self._db is None:
            raise RuntimeError("ResponseRegistry is not initialized")
        attempted_at = datetime.now(timezone.utc).isoformat()
        cursor = await self._db.execute(
            """
            UPDATE response_interactions
            SET escalation_attempted = 1,
                escalation_attempted_at = ?
            WHERE interaction_id = ?
              AND escalation_attempted = 0
            """,
            (attempted_at, interaction_id),
        )
        await self._db.commit()
        return cursor.rowcount == 1


response_registry = ResponseRegistry()
