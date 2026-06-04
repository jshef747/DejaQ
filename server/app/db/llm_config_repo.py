from collections.abc import Mapping, Set

from sqlalchemy.orm import Session

from app.db.models.workspace_llm_config import WorkspaceLlmConfig

_CONFIG_FIELDS = {"external_model", "local_model", "routing_threshold"}


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
