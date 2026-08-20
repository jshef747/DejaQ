from collections.abc import Mapping, Set

from sqlalchemy.orm import Session

from app.db.models.workspace_llm_config import WorkspaceLlmConfig

_CONFIG_FIELDS = {
    "external_model",
    "external_provider",
    "local_model",
    "generalizer_model",
    "adjuster_model",
    "enricher_model",
    "normalizer_model",
    "validator_model",
    "enricher_system_prompt",
    "normalizer_system_prompt",
    "validator_system_prompt",
    "validator_image_system_prompt",
    "adjuster_system_prompt",
    "generalizer_system_prompt",
    "local_model_system_prompt",
    "routing_threshold",
    "default_max_tokens",
    "rewrite_max_tokens",
    "ollama_num_ctx",
    "local_attachment_max_tokens",
}


def get_for_workspace(session: Session, workspace_id: int) -> WorkspaceLlmConfig | None:
    return session.query(WorkspaceLlmConfig).filter_by(workspace_id=workspace_id).first()


def upsert_for_workspace(
    session: Session,
    workspace_id: int,
    payload: Mapping[str, object],
    fields_set: Set[str],
) -> WorkspaceLlmConfig:
    row = get_for_workspace(session, workspace_id)
    if row is None:
        row = WorkspaceLlmConfig(workspace_id=workspace_id)
        session.add(row)

    for field in fields_set:
        if field in _CONFIG_FIELDS:
            setattr(row, field, payload.get(field))

    session.flush()
    session.refresh(row)
    return row
