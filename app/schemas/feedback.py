from pydantic import BaseModel
from datetime import datetime
from typing import Literal, Optional


class FeedbackRequest(BaseModel):
    value: Literal["positive", "negative"]
    conversation_id: Optional[str] = None


class FeedbackResponse(BaseModel):
    entry_id: str
    feedback_score: int
    flagged: bool
    deleted: bool
    status: str  # "ok" | "suppressed" | "not_found"


class FeedbackEvent(BaseModel):
    direction: str
    timestamp: datetime


class FeedbackHistoryResponse(BaseModel):
    entry_id: str
    feedback_score: int
    flagged: bool
    events: list[FeedbackEvent]