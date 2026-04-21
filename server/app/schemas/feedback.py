from typing import Literal
from pydantic import BaseModel


class FeedbackRequest(BaseModel):
    response_id: str
    rating: Literal["positive", "negative"]
    comment: str | None = None
