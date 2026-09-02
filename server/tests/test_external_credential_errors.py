"""Which HTTP status a hard query gets when credentials cannot be used.

Three different conditions used to collapse into one 500 carrying an internal
exception string, because CredentialService was constructed before the row was
looked up:

  * the workspace has no credential for the provider - 402, and this is the
    fresh-checkout case, since without an encryption key none can be stored;
  * the server has no DEJAQ_CREDENTIAL_ENCRYPTION_KEY but a credential row
    exists - 500, named as an operator action;
  * the row cannot be decrypted with the key the server has - 500, likewise.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import openai_compat
from app.services import credential_service
from tests.test_openai_compat_smoke import (
    _AUTH,
    HardClassifier,
    StubAdjuster,
    StubEnricher,
    StubMemory,
    StubNormalizer,
)

pytestmark = pytest.mark.no_model


@pytest.fixture(autouse=True)
def _no_encryption_key(monkeypatch):
    """A fresh checkout: .env.example ships the key commented out."""
    import app.config as config

    monkeypatch.setattr(config, "CREDENTIAL_ENCRYPTION_KEY", "", raising=False)


@pytest.fixture(autouse=True)
def _stub_api_key(monkeypatch):
    from app.middleware.api_key import _KEY_CACHE

    monkeypatch.setattr(
        _KEY_CACHE, "resolve", lambda token: ("demo", 1) if token == "test-key" else None
    )
    monkeypatch.setattr(_KEY_CACHE, "namespace", lambda *a, **kw: "test-namespace")


def _patch_pipeline(monkeypatch):
    async def _noop_log(*a, **k):
        return None

    monkeypatch.setattr(openai_compat, "EXTERNAL_MODEL_NAME", "gemini-2.5-flash")
    monkeypatch.setattr(
        openai_compat, "_services_for_model_profile",
        lambda profile, llm_config=None: openai_compat.ModelServices(
            normalizer=StubNormalizer(), llm_router=None,
            adjuster=StubAdjuster(), enricher=StubEnricher(), validator=None,
        ),
    )
    monkeypatch.setattr(openai_compat, "_classifier", HardClassifier())
    monkeypatch.setattr(openai_compat, "get_memory_service", lambda namespace: StubMemory())
    monkeypatch.setattr(openai_compat.request_logger, "log", _noop_log)
    monkeypatch.setattr(openai_compat, "USE_CELERY", False)


def _stub_credential_row(monkeypatch, row):
    monkeypatch.setattr(
        credential_service.credential_repo,
        "get_credential",
        lambda session, workspace_id, provider: row,
    )


def _ask_hard_question():
    return TestClient(app, headers=_AUTH).post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Prove that there are infinitely many prime numbers."}],
            "stream": False,
        },
    )


def test_no_credential_and_no_encryption_key_is_402_not_500(monkeypatch):
    """The out-of-the-box case. Nothing is stored, so nothing needs decrypting;
    building the Fernet first turned "you have no key configured" into an
    internal error - and since attachments always route external, that was every
    image and file request on a fresh install."""
    _patch_pipeline(monkeypatch)
    _stub_credential_row(monkeypatch, None)

    resp = _ask_hard_question()

    assert resp.status_code == 402
    assert "API key configured" in resp.json()["detail"]


def test_missing_encryption_key_with_a_stored_credential_names_the_operator_fix(monkeypatch):
    """A real server misconfiguration: rows exist but the key that wrote them is
    gone. Still a 500 - but it says what an operator must do, and does not hand
    the caller an exception string."""
    _patch_pipeline(monkeypatch)
    _stub_credential_row(monkeypatch, type("_Row", (), {"encrypted_key": "gAAAAA-ciphertext"})())

    resp = _ask_hard_question()

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "DEJAQ_CREDENTIAL_ENCRYPTION_KEY" in detail
    assert "operator" in detail
    assert "missing or malformed" not in detail, "internal exception text must not leak"


def test_undecryptable_credential_is_reported_as_a_key_mismatch(monkeypatch):
    """A valid key that is not the key the credential was written with."""
    from cryptography.fernet import Fernet

    import app.config as config

    monkeypatch.setattr(
        config, "CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode(), raising=False
    )
    _patch_pipeline(monkeypatch)
    _stub_credential_row(
        monkeypatch,
        type("_Row", (), {"encrypted_key": Fernet(Fernet.generate_key()).encrypt(b"k").decode()})(),
    )

    resp = _ask_hard_question()

    assert resp.status_code == 500
    assert resp.json()["detail"] == credential_service.ENCRYPTION_KEY_MISMATCH_DETAIL


def test_get_workspace_provider_key_reads_the_row_before_building_the_fernet(monkeypatch):
    """The unit-level statement of the same thing: no credential is None, never
    a raise, whatever the server's encryption key is doing."""
    _stub_credential_row(monkeypatch, None)

    assert credential_service.get_workspace_provider_key(None, 1, "google") is None


def test_get_workspace_provider_key_raises_a_typed_error_for_a_missing_key(monkeypatch):
    _stub_credential_row(monkeypatch, type("_Row", (), {"encrypted_key": "gAAAAA"})())

    with pytest.raises(credential_service.CredentialEncryptionKeyMissing):
        credential_service.get_workspace_provider_key(None, 1, "google")
