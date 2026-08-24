import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def credential_key(monkeypatch):
    import app.config as config

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("DEJAQ_CREDENTIAL_ENCRYPTION_KEY", key)
    monkeypatch.setattr(config, "CREDENTIAL_ENCRYPTION_KEY", key, raising=False)
    return key


def test_credential_service_lazy_validation(monkeypatch):
    import app.config as config
    from app.services.credential_service import CredentialService

    monkeypatch.setattr(config, "CREDENTIAL_ENCRYPTION_KEY", "", raising=False)

    with pytest.raises(ValueError, match="missing or malformed"):
        CredentialService()


def test_credential_service_encrypts_masks_and_round_trips(
    isolated_org_db,
    credential_key,
):
    from app.db.models.workspace import Workspace
    from app.db.session import get_session
    from app.services.credential_service import CredentialService

    service = CredentialService()
    with get_session() as session:
        ws = Workspace(name="Acme", slug="acme")
        session.add(ws)
        session.flush()
        row = service.upsert(session, ws.id, "google", "AIzaFoo123Bar")

        assert row.encrypted_key != "AIzaFoo123Bar"
        assert service.get_decrypted_key(session, ws.id, "google") == "AIzaFoo123Bar"
        assert service.list_masked(session, ws.id)[0]["key_preview"] == "AIza****3Bar"


def test_credential_service_fully_masks_short_keys(credential_key):
    from app.services.credential_service import CredentialService

    assert CredentialService().mask("short123") == "********"


def test_credential_provider_is_validated_in_python_not_by_the_database(credential_key, isolated_org_db):
    """There is deliberately no CHECK constraint on `provider`.

    Migration e5f6a7b8c9d0 dropped it: the supported-provider set is owned by
    `credential_service.SUPPORTED_PROVIDERS`, and duplicating it in the schema
    cost a full SQLite table rebuild for every provider added. This replaces a
    test that asserted the dropped constraint still fired - it pinned behaviour
    the codebase had intentionally removed, so it failed everywhere. The
    invariant is real, it just lives one layer up.
    """
    from app.db.models.workspace import Workspace
    from app.db.session import get_session
    from app.services.credential_service import CredentialService

    with get_session() as session:
        ws = Workspace(name="Acme", slug="acme")
        session.add(ws)
        session.flush()
        workspace_id = ws.id

    with get_session() as session:
        with pytest.raises(ValueError, match="Unsupported provider"):
            CredentialService().upsert(session, workspace_id, "invalid_provider", "sk-whatever")


def test_credential_unique_constraint_rejects_a_duplicate_provider(isolated_org_db):
    """One credential per (workspace, provider), enforced by the database.

    Worth its own test because this constraint was silently ABSENT for a while:
    d1e2f3a4b5c6 dropped and recreated it inside a batch rebuild that did not
    survive, and e5f6a7b8c9d0 restored it while rebuilding the table anyway.
    Nothing else would notice it going missing again - a duplicate row just
    means two encrypted keys where every reader expects one.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.db.models.workspace import Workspace
    from app.db.session import get_session

    with get_session() as session:
        ws = Workspace(name="Acme", slug="acme")
        session.add(ws)
        session.flush()
        workspace_id = ws.id

    insert = text(
        "INSERT INTO workspace_provider_credentials "
        "(workspace_id, provider, encrypted_key) VALUES (:workspace_id, :provider, :encrypted_key)"
    )
    row = {"workspace_id": workspace_id, "provider": "google", "encrypted_key": "ciphertext"}

    with get_session() as session:
        session.execute(insert, row)

    with pytest.raises(IntegrityError):
        with get_session() as session:
            session.execute(insert, {**row, "encrypted_key": "second-ciphertext"})
