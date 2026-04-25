from collections.abc import Mapping, Set

from sqlalchemy.orm import Session

from app.db.models.org_llm_config import OrgLlmConfig

_CONFIG_FIELDS = {"external_model", "local_model", "routing_threshold"}


def get_for_org(session: Session, org_id: int) -> OrgLlmConfig | None:
    return session.query(OrgLlmConfig).filter_by(org_id=org_id).first()


def upsert_for_org(
    session: Session,
    org_id: int,
    payload: Mapping[str, object],
    fields_set: Set[str],
) -> OrgLlmConfig:
    row = get_for_org(session, org_id)
    if row is None:
        row = OrgLlmConfig(org_id=org_id)
        session.add(row)

    for field in fields_set:
        if field in _CONFIG_FIELDS:
            setattr(row, field, payload.get(field))

    session.flush()
    session.refresh(row)
    return row
