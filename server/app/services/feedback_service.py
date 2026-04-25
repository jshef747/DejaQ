from typing import Literal
import sqlite3

from pydantic import BaseModel

import app.config as config
from app.schemas.admin.feedback import FeedbackItem, FeedbackListResponse
from app.services.memory_chromaDB import get_memory_service
from app.services.request_logger import request_logger


class FeedbackNotFound(Exception):
    pass


class FeedbackNamespaceMismatch(Exception):
    pass


class FeedbackOrgNotFound(Exception):
    pass


class FeedbackDeptNotFound(Exception):
    pass


class FeedbackResult(BaseModel):
    status: Literal["ok", "deleted"]
    new_score: float | None = None


def list_feedback(
    *,
    org: str | None = None,
    department: str | None = None,
    response_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> FeedbackListResponse:
    clauses: list[str] = []
    params: list[object] = []
    if org:
        clauses.append("org = ?")
        params.append(org)
    if department:
        clauses.append("department = ?")
        params.append(department)
    if response_id:
        clauses.append("response_id = ?")
        params.append(response_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    with sqlite3.connect(config.STATS_DB_PATH) as con:
        total = con.execute(f"SELECT COUNT(*) FROM feedback_log {where}", params).fetchone()[0]
        rows = con.execute(
            f"""
            SELECT id, ts, response_id, org, department, rating, comment
            FROM feedback_log
            {where}
            ORDER BY ts DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    return FeedbackListResponse(
        items=[
            FeedbackItem(
                id=row[0],
                ts=row[1],
                response_id=row[2],
                org=row[3],
                department=row[4],
                rating=row[5],
                comment=row[6],
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _namespace_for(org: str, department: str) -> str:
    if department == "default":
        return f"{org}--default"
    return f"{org}__{department}"


def _split_response_id(response_id: str) -> tuple[str, str]:
    if ":" not in response_id:
        raise ValueError("Invalid response_id format; expected <namespace>:<doc_id>")
    return response_id.split(":", 1)


async def submit_feedback(
    *,
    response_id: str,
    rating: Literal["positive", "negative"],
    comment: str | None,
    org: str,
    department: str,
    validate_namespace: bool,
) -> FeedbackResult:
    namespace, doc_id = _split_response_id(response_id)
    if validate_namespace and namespace != _namespace_for(org, department):
        raise FeedbackNamespaceMismatch(response_id)

    memory = get_memory_service(namespace)
    try:
        if rating == "negative":
            neg_count = memory.get_negative_count(doc_id)
            if neg_count == 0:
                memory.delete_entry(doc_id)
                result = FeedbackResult(status="deleted")
            else:
                result = FeedbackResult(status="ok", new_score=memory.update_score(doc_id, -2.0))
        else:
            result = FeedbackResult(status="ok", new_score=memory.update_score(doc_id, 1.0))
    except KeyError as exc:
        raise FeedbackNotFound(response_id) from exc

    await request_logger.log_feedback(response_id, org, department, rating, comment)
    return result
