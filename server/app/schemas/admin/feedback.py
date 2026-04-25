from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AdminFeedbackRequest(BaseModel):
    org: str
    department: str = "default"
    response_id: str
    rating: Literal["positive", "negative"]
    comment: str | None = None


class FeedbackItem(BaseModel):
    id: int
    ts: datetime | str
    response_id: str
    org: str
    department: str
    rating: Literal["positive", "negative"]
    comment: str | None


class FeedbackListResponse(BaseModel):
    items: list[FeedbackItem]
    total: int
    limit: int = Field(ge=0, le=500)
    offset: int = Field(ge=0)
