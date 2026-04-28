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
    from app.db.models.org import Organization
    from app.db.session import get_session
    from app.services.credential_service import CredentialService

    service = CredentialService()
    with get_session() as session:
        org = Organization(name="Acme", slug="acme")
        session.add(org)
        session.flush()
        row = service.upsert(session, org.id, "google", "AIzaFoo123Bar")

        assert row.encrypted_key != "AIzaFoo123Bar"
        assert service.get_decrypted_key(session, org.id, "google") == "AIzaFoo123Bar"
        assert service.list_masked(session, org.id)[0]["key_preview"] == "AIza****3Bar"


def test_credential_service_fully_masks_short_keys(credential_key):
    from app.services.credential_service import CredentialService

    assert CredentialService().mask("short123") == "********"


def test_credential_provider_check_constraint_rejects_invalid_provider(isolated_org_db):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.db.models.org import Organization
    from app.db.session import get_session

    with get_session() as session:
        org = Organization(name="Acme", slug="acme")
        session.add(org)
        session.flush()
        org_id = org.id

    with pytest.raises(IntegrityError):
        with get_session() as session:
            session.execute(
                text(
                    "INSERT INTO org_provider_credentials "
                    "(org_id, provider, encrypted_key) VALUES (:org_id, :provider, :encrypted_key)"
                ),
                {"org_id": org_id, "provider": "invalid_provider", "encrypted_key": "ciphertext"},
            )
