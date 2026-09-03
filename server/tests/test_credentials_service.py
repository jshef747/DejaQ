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


def test_credential_service_upsert_rejects_unsupported_provider(
    isolated_org_db,
    credential_key,
):
    """The provider set moves, so it's validated in Python
    (CredentialService.upsert) rather than frozen into a DB CHECK constraint
    - see workspace_provider_credentials.py for why that constraint was
    dropped (migration e5f6a7b8c9d0)."""
    from app.db.models.workspace import Workspace
    from app.db.session import get_session
    from app.services.credential_service import CredentialService

    service = CredentialService()
    with get_session() as session:
        ws = Workspace(name="Acme", slug="acme")
        session.add(ws)
        session.flush()
        workspace_id = ws.id

        with pytest.raises(ValueError, match="Unsupported provider"):
            service.upsert(session, workspace_id, "invalid_provider", "ciphertext")


def test_credential_service_upsert_accepts_any_single_key_litellm_provider(
    isolated_org_db,
    credential_key,
):
    """Not a hand-kept ten-name list any more - any provider LiteLLM serves
    with a single API-key string is accepted, mistral included."""
    from app.db.models.workspace import Workspace
    from app.db.session import get_session
    from app.services.credential_service import CredentialService

    service = CredentialService()
    with get_session() as session:
        ws = Workspace(name="Acme", slug="acme")
        session.add(ws)
        session.flush()
        row = service.upsert(session, ws.id, "mistral", "mistral-key-123")
        assert row.provider == "mistral"


def test_credential_stored_under_litellm_key_is_found_under_dejaq_key(
    isolated_org_db,
    credential_key,
):
    """A2: the catalog uses LiteLLM keys ('gemini'), but the request path looks
    a credential up under the DejaQ key ('google', from external_provider). A
    key saved as 'gemini' must be normalised to 'google' on upsert so the
    gemini/<id> model that needs it finds it, instead of a spurious 402."""
    from app.db.models.workspace import Workspace
    from app.db.session import get_session
    from app.services.credential_service import CredentialService, get_workspace_provider_key

    service = CredentialService()
    with get_session() as session:
        ws = Workspace(name="Acme", slug="acme")
        session.add(ws)
        session.flush()

        row = service.upsert(session, ws.id, "gemini", "AIzaGeminiKey")
        assert row.provider == "google"  # stored under the DejaQ key
        # Found under the DejaQ key the request path uses (external_provider="google").
        assert get_workspace_provider_key(session, ws.id, "google") == "AIzaGeminiKey"
        # And still reachable via the LiteLLM key thanks to normalisation.
        assert get_workspace_provider_key(session, ws.id, "gemini") == "AIzaGeminiKey"


def test_credential_service_upsert_rejects_structured_credential_provider(
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
        workspace_id = ws.id

        with pytest.raises(ValueError, match="structured credential"):
            service.upsert(session, workspace_id, "azure", "ciphertext")
