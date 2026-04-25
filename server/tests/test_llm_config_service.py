import pytest

from app.db import org_repo
from app.db.session import get_session


def _create_org(name: str = "Acme") -> None:
    with get_session() as session:
        org_repo.create_org(session, name)


def test_llm_config_read_returns_defaults_when_no_row(isolated_org_db):
    from app.config import EXTERNAL_MODEL_NAME, LOCAL_LLM_MODEL_NAME, ROUTING_THRESHOLD
    from app.services.llm_config_service import read_for_org

    _create_org()

    result = read_for_org("acme")

    assert result.external_model == EXTERNAL_MODEL_NAME
    assert result.local_model == LOCAL_LLM_MODEL_NAME
    assert result.routing_threshold == ROUTING_THRESHOLD
    assert result.overrides == {}
    assert result.updated_at is None
    assert result.is_default is True


def test_llm_config_update_preserves_omitted_fields_and_clears_nulls(isolated_org_db):
    from app.config import EXTERNAL_MODEL_NAME
    from app.services.llm_config_service import read_for_org, update_for_org

    _create_org()

    first = update_for_org(
        "acme",
        {"external_model": "gemini-2.5-pro", "local_model": "gemma-4-e4b"},
        {"external_model", "local_model"},
    )
    assert first.external_model == "gemini-2.5-pro"
    assert first.local_model == "gemma-4-e4b"
    assert first.overrides == {
        "external_model": "gemini-2.5-pro",
        "local_model": "gemma-4-e4b",
    }

    second = update_for_org(
        "acme",
        {"external_model": None},
        {"external_model"},
    )

    assert second.external_model == EXTERNAL_MODEL_NAME
    assert second.local_model == "gemma-4-e4b"
    assert second.overrides == {"local_model": "gemma-4-e4b"}

    stored = read_for_org("acme")
    assert stored.external_model == EXTERNAL_MODEL_NAME
    assert stored.local_model == "gemma-4-e4b"
    assert stored.is_default is False


def test_llm_config_empty_update_is_rejected(isolated_org_db):
    from app.services.llm_config_service import InvalidLlmConfigUpdate, update_for_org

    _create_org()

    with pytest.raises(InvalidLlmConfigUpdate):
        update_for_org("acme", {}, set())


def test_llm_config_unknown_org_raises(isolated_org_db):
    from app.services.llm_config_service import OrgNotFound, read_for_org

    with pytest.raises(OrgNotFound):
        read_for_org("missing")
