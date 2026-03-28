import logging

from fastapi import APIRouter

from app.schemas.feedback import FeedbackRequest, FeedbackHistoryResponse, FeedbackResponse
from app.services.feedback_service import get_feedback_service

logger = logging.getLogger("dejaq.router.feedback")

router = APIRouter()

feedback_svc = get_feedback_service()


@router.post("/cache/entries/{entry_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(entry_id: str, request: FeedbackRequest):
    logger.info("POST /cache/entries/%s/feedback value=%s", entry_id, request.value)
    return feedback_svc.submit_feedback(entry_id, request.value, request.conversation_id)


@router.get("/cache/entries/{entry_id}/feedback", response_model=FeedbackHistoryResponse)
async def get_feedback_history(entry_id: str):
    logger.info("GET /cache/entries/%s/feedback", entry_id)
    return feedback_svc.get_feedback_history(entry_id)