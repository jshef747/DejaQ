import json
from typing import Literal
import sqlite3

from pydantic import BaseModel

import app.config as config
from app.schemas.feedback import EscalatedResponse
from app.schemas.admin.feedback import FeedbackItem, FeedbackListResponse
from app.services.escalation import escalate
from app.services.memory_chromaDB import get_memory_service
from app.services.request_logger import request_logger
from app.services.response_registry import compute_messages_hash, response_registry


class FeedbackNotFound(Exception):
    pass


class FeedbackNamespaceMismatch(Exception):
    pass


class FeedbackDeptNotFound(Exception):
    pass


class FeedbackResult(BaseModel):
    status: Literal["ok", "deleted"]
    new_score: float | None = None
    escalated_response: EscalatedResponse | None = None
    escalation_status: (
        Literal[
            "answered",
            "not_requested",
            "no_further_escalation",
            "no_credential",
            "provider_error",
            "timeout",
            "message_mismatch",
            "already_escalated",
        ]
        | None
    ) = None


def list_feedback(
    *,
    org: str | None = None,
    department: str | None = None,
    response_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    accessible_workspace_slugs: set[str] | None = None,
) -> FeedbackListResponse:
    clauses: list[str] = []
    params: list[object] = []
    if org:
        clauses.append("workspace = ?")
        params.append(org)
    if department:
        clauses.append("department = ?")
        params.append(department)
    if response_id:
        clauses.append("response_id = ?")
        params.append(response_id)
    if accessible_workspace_slugs is not None and not org:
        if accessible_workspace_slugs:
            placeholders = ",".join("?" * len(accessible_workspace_slugs))
            clauses.append(f"workspace IN ({placeholders})")
            params.extend(sorted(accessible_workspace_slugs))
        else:
            clauses.append("1=0")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    with sqlite3.connect(config.STATS_DB_PATH) as con:
        total = con.execute(f"SELECT COUNT(*) FROM feedback_log {where}", params).fetchone()[0]
        rows = con.execute(
            f"""
            SELECT id, ts, response_id, workspace, department, rating, comment
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
                workspace=row[3],
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


def _validate_messages(messages: list[dict]) -> None:
    if not messages:
        raise ValueError("messages must not be empty")
    if len(messages) > 100:
        raise ValueError("messages exceeds maximum count")
    try:
        serialized = json.dumps(messages)
    except TypeError as exc:
        raise ValueError("messages must be JSON serializable") from exc
    if len(serialized.encode("utf-8")) > 256_000:
        raise ValueError("messages exceeds maximum size")

    has_user = False
    allowed_roles = {"system", "user", "assistant", "tool"}
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("messages entries must be objects")
        role = message.get("role")
        content = message.get("content")
        if role not in allowed_roles:
            raise ValueError(f"Unsupported message role: {role}")
        if not isinstance(content, str):
            raise ValueError("messages content must be a string")
        if role == "user" and content.strip():
            has_user = True
    if not has_user:
        raise ValueError("messages must include a non-empty user message")


def _apply_cache_feedback(
    *,
    response_id: str,
    rating: Literal["positive", "negative"],
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
                return FeedbackResult(status="deleted")
            return FeedbackResult(status="ok", new_score=memory.update_score(doc_id, -2.0))
        return FeedbackResult(status="ok", new_score=memory.update_score(doc_id, 1.0))
    except KeyError as exc:
        raise FeedbackNotFound(response_id) from exc


async def submit_feedback(
    *,
    response_id: str | None,
    interaction_id: str | None = None,
    messages: list[dict] | None = None,
    rating: Literal["positive", "negative"],
    comment: str | None,
    org: str,
    workspace_id: int | None = None,
    department: str,
    validate_namespace: bool,
) -> FeedbackResult:
    if response_id is None and interaction_id is None:
        raise ValueError("Either response_id or interaction_id is required")

    interaction = None
    cache_response_id = response_id
    if interaction_id:
        interaction = await response_registry.validate_owner(
            interaction_id,
            workspace_id=workspace_id,
            workspace_slug=org,
            department=department,
        )
        if interaction is None:
            raise FeedbackNotFound(interaction_id)
        cache_response_id = cache_response_id or interaction.response_id

    if cache_response_id:
        result = _apply_cache_feedback(
            response_id=cache_response_id,
            rating=rating,
            org=org,
            department=department,
            validate_namespace=validate_namespace,
        )
    else:
        result = FeedbackResult(status="ok")

    if interaction_id:
        await request_logger.log_feedback(
            cache_response_id or interaction_id,
            org,
            department,
            rating,
            comment,
            interaction_id=interaction_id,
        )
    else:
        await request_logger.log_feedback(cache_response_id or "", org, department, rating, comment)

    if not interaction_id or rating != "negative":
        return result

    if not messages:
        result.escalation_status = "not_requested"
        return result

    _validate_messages(messages)
    if interaction is None:
        raise FeedbackNotFound(interaction_id)
    if compute_messages_hash(messages) != interaction.message_hash:
        result.escalation_status = "message_mismatch"
        return result

    acquired = await response_registry.acquire_escalation(interaction_id)
    if not acquired:
        result.escalation_status = "already_escalated"
        return result

    escalation_result = await escalate(interaction=interaction, messages=messages)
    result.escalated_response = escalation_result.escalated_response
    result.escalation_status = escalation_result.escalation_status
    return result
