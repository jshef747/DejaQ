import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis
import redis.exceptions
from fastapi import HTTPException

from app.config import (
    REDIS_URL,
    FEEDBACK_SUPPRESSION_TTL,
    FEEDBACK_FLAG_THRESHOLD,
    FEEDBACK_AUTO_DELETE_THRESHOLD,
)
from app.schemas.feedback import FeedbackEvent, FeedbackHistoryResponse, FeedbackResponse
from app.services.memory_chromaDB import MemoryService

logger = logging.getLogger("dejaq.services.feedback")

_feedback_service: Optional["FeedbackService"] = None


def get_feedback_service() -> "FeedbackService":
    global _feedback_service
    if _feedback_service is None:
        _feedback_service = FeedbackService()
    return _feedback_service


class FeedbackService:
    def __init__(self) -> None:
        self._memory = MemoryService()
        try:
            self._redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
            self._redis.ping()
            logger.info("FeedbackService: Redis connection established")
        except redis.exceptions.RedisError as exc:
            logger.warning("FeedbackService: Redis unavailable (%s) — event history disabled", exc)
            self._redis = None

    def _redis_available(self) -> bool:
        return self._redis is not None

    def _set_suppression_flag(self, doc_id: str) -> None:
        if not self._redis_available():
            return
        try:
            self._redis.setex(f"skip:{doc_id}", FEEDBACK_SUPPRESSION_TTL, "1")
            logger.info("Suppression flag set for entry %s (TTL=%ds)", doc_id, FEEDBACK_SUPPRESSION_TTL)
        except redis.exceptions.RedisError as exc:
            logger.warning("Could not set suppression flag for %s: %s", doc_id, exc)

    def _append_event(self, entry_id: str, value: str) -> None:
        if not self._redis_available():
            return
        try:
            event = json.dumps({
                "direction": value,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            self._redis.rpush(f"feedback:{entry_id}", event)
        except redis.exceptions.RedisError as exc:
            logger.warning("Redis unavailable, skipping event history for %s: %s", entry_id, exc)

    def submit_feedback(
        self,
        entry_id: str,
        value: str,
        conversation_id: Optional[str] = None,
    ) -> FeedbackResponse:
        meta = self._memory.get_entry_metadata(entry_id)

        if meta is None:
            # Entry not yet stored (cache miss still in background) or already deleted
            if value == "negative":
                self._set_suppression_flag(entry_id)
                logger.info("Negative feedback on missing entry %s — storage suppressed", entry_id)
                return FeedbackResponse(
                    entry_id=entry_id,
                    feedback_score=0,
                    flagged=False,
                    deleted=False,
                    status="suppressed",
                )
            logger.info("Positive feedback on missing entry %s — no-op", entry_id)
            return FeedbackResponse(
                entry_id=entry_id,
                feedback_score=0,
                flagged=False,
                deleted=False,
                status="not_found",
            )

        current_score = int(meta.get("feedback_score", 0))
        new_score = current_score + (1 if value == "positive" else -1)

        # Auto-delete: once flagged, the entry stops appearing in cache hits so it
        # can't accumulate further negative ratings via normal flow. Delete immediately
        # at the flag threshold instead of waiting for a lower threshold that is
        # unreachable in practice.
        if new_score <= FEEDBACK_FLAG_THRESHOLD:
            self._memory.delete_entry(entry_id)
            self._append_event(entry_id, value)
            logger.info(
                "Entry %s auto-deleted (score=%d <= threshold=%d)",
                entry_id, new_score, FEEDBACK_FLAG_THRESHOLD,
            )
            return FeedbackResponse(
                entry_id=entry_id,
                feedback_score=new_score,
                flagged=True,
                deleted=True,
                status="ok",
            )

        new_flagged = False

        updated_meta = {**meta, "feedback_score": new_score, "flagged": int(new_flagged)}
        self._memory.update_entry_metadata(entry_id, updated_meta)
        self._append_event(entry_id, value)

        logger.info(
            "Feedback recorded for entry %s: %s → score=%d flagged=%s",
            entry_id, value, new_score, new_flagged,
        )
        return FeedbackResponse(
            entry_id=entry_id,
            feedback_score=new_score,
            flagged=new_flagged,
            deleted=False,
            status="ok",
        )

    def get_feedback_history(self, entry_id: str) -> FeedbackHistoryResponse:
        meta = self._memory.get_entry_metadata(entry_id)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"Cache entry '{entry_id}' not found")

        events: list[FeedbackEvent] = []
        if self._redis_available():
            try:
                raw_events = self._redis.lrange(f"feedback:{entry_id}", 0, -1)
                for raw in raw_events:
                    data = json.loads(raw)
                    events.append(FeedbackEvent(
                        direction=data["direction"],
                        timestamp=datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")),
                    ))
            except redis.exceptions.RedisError as exc:
                logger.warning("Redis unavailable, returning empty event history for %s: %s", entry_id, exc)

        return FeedbackHistoryResponse(
            entry_id=entry_id,
            feedback_score=int(meta.get("feedback_score", 0)),
            flagged=bool(meta.get("flagged", 0)),
            events=events,
        )
