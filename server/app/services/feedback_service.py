import asyncio
import json
import logging
from typing import Literal
import sqlite3

from pydantic import BaseModel

import app.config as config
from app.schemas.feedback import EscalatedResponse
from app.schemas.admin.feedback import FeedbackItem, FeedbackListResponse
from app.services.answer_edit import apply_edited_answer
from app.services.escalation import escalate
from app.services.memory_chromaDB import get_memory_service
from app.services.request_logger import ensure_stats_schema, request_logger
from app.services.response_registry import compute_messages_hash, response_registry

logger = logging.getLogger("dejaq.services.feedback")

# Background store (generalize_and_store_task) writes the cache entry AFTER
# the response is already returned to the user, so a feedback submitted right
# after the answer arrives can race it - measured 0.99s-9.9s on this stack.
# Retry the lookup with a short bounded backoff before giving up; a genuinely
# bad response_id just pays this same delay and then correctly 404s.
_FEEDBACK_RETRY_DELAYS_SECONDS = (0.2, 0.5, 1.0)


class FeedbackNotFound(Exception):
    pass


class FeedbackNamespaceMismatch(Exception):
    pass


class FeedbackDeptNotFound(Exception):
    pass


class FeedbackResult(BaseModel):
    status: Literal["ok", "deleted"]
    new_score: float | None = None
    # Edit & Save. Mirrors schemas/feedback.FeedbackResponse - edit both together.
    edit_status: Literal["saved", "created", "not_cached", "message_mismatch"] | None = None
    response_id: str | None = None
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
    workspace: str | None = None,
    department: str | None = None,
    response_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> FeedbackListResponse:
    clauses: list[str] = []
    params: list[object] = []
    if workspace:
        clauses.append("workspace = ?")
        params.append(workspace)
    if department:
        clauses.append("department = ?")
        params.append(department)
    if response_id:
        clauses.append("response_id = ?")
        params.append(response_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""

    with sqlite3.connect(config.STATS_DB_PATH) as con:
        ensure_stats_schema(con)
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


def _namespace_for(workspace: str, department: str) -> str:
    """Best-effort reconstruction of a namespace from workspace + department slug.

    Only a fallback for callers that have no request state to read it from (the
    admin surface). It is a guess, not the authority: `--default` is right for the
    no-department case, where no Department row exists, but a department that is
    genuinely *named* "Default" slugs to "default" and is stored by dept_repo as
    `<workspace>__default`. Callers that can pass the namespace the write path
    used should do so - see `cache_namespace` on submit_feedback().
    """
    if department == "default":
        return f"{workspace}--default"
    return f"{workspace}__{department}"


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


def _checked_namespace(
    *,
    response_id: str,
    workspace: str,
    department: str,
    validate_namespace: bool,
    cache_namespace: str | None,
) -> tuple[str, str]:
    """Split a response_id and prove it belongs to this caller.

    Every path that is about to TOUCH a cache entry goes through here first.
    `response_id` can be client-supplied, and it names the ChromaDB collection
    to open - so an unchecked one reaches another workspace's cache (and
    `get_or_create_collection` would conjure an empty collection for a
    namespace that never existed).
    """
    namespace, doc_id = _split_response_id(response_id)
    expected = cache_namespace or _namespace_for(workspace, department)
    if validate_namespace and namespace != expected:
        raise FeedbackNamespaceMismatch(response_id)
    return namespace, doc_id


async def _apply_cache_feedback(
    *,
    response_id: str,
    rating: Literal["positive", "negative"],
    workspace: str,
    department: str,
    validate_namespace: bool,
    cache_namespace: str | None = None,
) -> FeedbackResult:
    namespace, doc_id = _checked_namespace(
        response_id=response_id,
        workspace=workspace,
        department=department,
        validate_namespace=validate_namespace,
        cache_namespace=cache_namespace,
    )

    memory = get_memory_service(namespace)

    def _apply() -> FeedbackResult:
        if rating == "negative":
            neg_count = memory.get_negative_count(doc_id)
            if neg_count == 0:
                memory.delete_entry(doc_id)
                return FeedbackResult(status="deleted")
            return FeedbackResult(status="ok", new_score=memory.update_score(doc_id, -2.0))
        return FeedbackResult(status="ok", new_score=memory.update_score(doc_id, 1.0))

    attempts = len(_FEEDBACK_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            return _apply()
        except KeyError as exc:
            if attempt == attempts - 1:
                logger.warning(
                    "Feedback for %s still not found in cache after %d retries "
                    "(background store may be unusually slow)",
                    response_id,
                    attempt,
                )
                raise FeedbackNotFound(response_id) from exc
            await asyncio.sleep(_FEEDBACK_RETRY_DELAYS_SECONDS[attempt])
    raise AssertionError("unreachable")


async def submit_feedback(
    *,
    response_id: str | None,
    interaction_id: str | None = None,
    messages: list[dict] | None = None,
    edited_answer: str | None = None,
    rating: Literal["positive", "negative"],
    comment: str | None,
    workspace: str,
    workspace_id: int | None = None,
    department: str,
    validate_namespace: bool,
    cache_namespace: str | None = None,
) -> FeedbackResult:
    """Apply feedback to a cached entry, and escalate when asked to.

    `cache_namespace` is the namespace the WRITE path used for this caller,
    resolved from the departments table by the API-key middleware. Pass it
    whenever it is available: re-deriving it from the workspace and department
    slugs cannot distinguish a department named "Default" from having no
    department at all, and the two live in different collections.
    """
    if response_id is None and interaction_id is None:
        raise ValueError("Either response_id or interaction_id is required")

    interaction = None
    cache_response_id = response_id
    if interaction_id:
        interaction = await response_registry.validate_owner(
            interaction_id,
            workspace_id=workspace_id,
            workspace_slug=workspace,
            department=department,
        )
        if interaction is None:
            raise FeedbackNotFound(interaction_id)
        cache_response_id = cache_response_id or interaction.response_id

    edit_outcome = None
    if edited_answer is not None:
        # FeedbackRequest enforces both of these, but this service is also
        # reachable from the admin surface, whose schema does not - so they are
        # re-checked here rather than trusted, and surface as a 422 either way.
        if rating != "positive":
            raise ValueError("edited_answer requires rating='positive'")
        if interaction is None:
            raise ValueError("edited_answer requires a valid interaction_id")
        # The edit WRITES, so ownership is proved before it runs - not by
        # _apply_cache_feedback further down, which would be checking after the
        # answer had already been replaced. `cache_response_id` may still be the
        # raw client-supplied response_id at this point.
        if cache_response_id:
            _checked_namespace(
                response_id=cache_response_id,
                workspace=workspace,
                department=department,
                validate_namespace=validate_namespace,
                cache_namespace=cache_namespace,
            )
        # Same bound the escalation replay gets. The hash gate makes malformed
        # content moot, but nothing else caps what is serialized to compute it.
        if messages:
            _validate_messages(messages)
        # Runs BEFORE the scoring below for two reasons: the +1.0 must land on
        # the human text rather than on the answer it replaced, and in the
        # create-when-absent case the entry has to exist before update_score
        # can find it.
        edit_outcome = await apply_edited_answer(
            interaction=interaction,
            response_id=cache_response_id,
            edited_answer=edited_answer,
            messages=messages,
        )
        if edit_outcome.response_id:
            # An alias-served id redirects to its root, and a created entry is
            # keyed by a freshly derived query. Score the entry that was
            # actually written, and validate the namespace it actually lives in.
            cache_response_id = edit_outcome.response_id

    # An edit that did not land ("not_cached", "message_mismatch") leaves
    # cache_response_id naming an entry that does not exist, and scoring it
    # would 404 the whole request over a like the user did get to express.
    _edit_landed = edit_outcome is None or edit_outcome.edit_status in ("saved", "created")
    if cache_response_id and _edit_landed:
        try:
            result = await _apply_cache_feedback(
                response_id=cache_response_id,
                rating=rating,
                workspace=workspace,
                department=department,
                validate_namespace=validate_namespace,
                cache_namespace=cache_namespace,
            )
        except FeedbackNotFound:
            # Only reachable when an edit already succeeded and the entry
            # vanished before it could be scored - a concurrent thumbs-down
            # delete. Raising here would answer 404, and the client would tell
            # the user the save failed while their text sits in the cache (or,
            # in the delete case, correctly does not). The write is what the
            # user asked for; the lost +1.0 is not worth a false failure.
            if edit_outcome is None:
                raise
            logger.warning(
                "Edit landed but its entry vanished before scoring: %s", cache_response_id
            )
            result = FeedbackResult(status="ok")
    else:
        result = FeedbackResult(status="ok")

    if edit_outcome is not None:
        result.edit_status = edit_outcome.edit_status
        result.response_id = edit_outcome.response_id

    if interaction_id:
        await request_logger.log_feedback(
            cache_response_id or interaction_id,
            workspace,
            department,
            rating,
            comment,
            interaction_id=interaction_id,
            edited=edited_answer is not None,
        )
    else:
        await request_logger.log_feedback(cache_response_id or "", workspace, department, rating, comment)

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
