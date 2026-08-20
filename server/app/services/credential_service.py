from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

import app.config as config
from app.db import credential_repo
from app.db.models.workspace_provider_credentials import WorkspaceProviderCredentials
from app.services.model_catalog import STRUCTURED_CREDENTIAL_PROVIDERS

SUPPORTED_PROVIDERS = {
    "google",
    "openai",
    "anthropic",
    "xai",
    "deepseek",
    "mistral",
    "cohere",
    "together",
    "groq",
    "fireworks",
}


class CredentialEncryptionKeyMissing(RuntimeError):
    """The server has no usable DEJAQ_CREDENTIAL_ENCRYPTION_KEY.

    Deliberately not a ValueError, and deliberately not the same condition as
    "this workspace has no credential for the provider". The second is an
    ordinary 402 the operator fixes in the dashboard; this one is a server
    misconfiguration no API caller can do anything about.
    """


class CredentialService:
    def __init__(self) -> None:
        raw_key = config.CREDENTIAL_ENCRYPTION_KEY.strip()
        try:
            self._fernet = Fernet(raw_key.encode("utf-8"))
        except (TypeError, ValueError):
            raise ValueError("DEJAQ_CREDENTIAL_ENCRYPTION_KEY missing or malformed") from None

    def encrypt(self, key: str) -> str:
        return self._fernet.encrypt(key.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            raise ValueError("Credential ciphertext could not be decrypted") from None

    def mask(self, key: str) -> str:
        if len(key) < 12:
            return "********"
        return f"{key[:4]}****{key[-4:]}"

    def upsert(
        self,
        session: Session,
        workspace_id: int,
        provider: str,
        raw_key: str,
    ) -> WorkspaceProviderCredentials:
        provider = provider.lower()
        if provider in STRUCTURED_CREDENTIAL_PROVIDERS:
            raise ValueError(
                f"Provider '{provider}' needs a structured credential (more than one "
                "field) that workspace_provider_credentials cannot store yet "
                "(app/services/model_catalog.py:STRUCTURED_CREDENTIAL_PROVIDERS)."
            )
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'.")
        stripped = raw_key.strip()
        if not stripped:
            raise ValueError("API key must not be empty.")
        encrypted = self.encrypt(stripped)
        return credential_repo.upsert_credential(session, workspace_id, provider, encrypted)

    def get_decrypted_key(self, session: Session, workspace_id: int, provider: str) -> str | None:
        row = credential_repo.get_credential(session, workspace_id, provider.lower())
        if row is None:
            return None
        return self.decrypt(row.encrypted_key)

    def list_masked(self, session: Session, workspace_id: int) -> list[dict]:
        rows = credential_repo.list_credentials(session, workspace_id)
        return [self._to_masked_dict(row) for row in rows]

    def delete(self, session: Session, workspace_id: int, provider: str) -> bool:
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'.")
        return credential_repo.delete_credential(session, workspace_id, provider)

    def to_masked_response(self, row: WorkspaceProviderCredentials) -> dict:
        return self._to_masked_dict(row)

    def _to_masked_dict(self, row: WorkspaceProviderCredentials) -> dict:
        key = self.decrypt(row.encrypted_key)
        return {
            "provider": row.provider,
            "key_preview": self.mask(key),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }


ENCRYPTION_KEY_MISSING_DETAIL = (
    "The server has no usable DEJAQ_CREDENTIAL_ENCRYPTION_KEY, so stored provider "
    "credentials cannot be decrypted. An operator must set it in server/.env "
    "(see .env.example) and restart the server."
)

ENCRYPTION_KEY_MISMATCH_DETAIL = (
    "A stored provider credential could not be decrypted with the server's "
    "DEJAQ_CREDENTIAL_ENCRYPTION_KEY. An operator must restore the original key or "
    "re-enter the credential."
)


def get_workspace_provider_key(session: Session, workspace_id: int, provider: str) -> str | None:
    """Decrypt a workspace's key for `provider`, or None when it has none.

    The row is read BEFORE the Fernet is built, and that order is the point.
    Constructing CredentialService first meant a server with no encryption key
    raised on the way to a lookup that would have found nothing anyway - so a
    workspace with no credential (an ordinary 402) reported itself as an internal
    error. Since a key cannot be stored without the encryption key either, a fresh
    checkout has no rows, which made every external-routed request - every image
    and every file, which always route external - a 500 out of the box.

    A row that exists but cannot be decrypted is a genuine server-side problem and
    still raises; the caller reports it as one.
    """
    row = credential_repo.get_credential(session, workspace_id, provider.lower())
    if row is None:
        return None
    try:
        service = CredentialService()
    except ValueError as exc:
        raise CredentialEncryptionKeyMissing(ENCRYPTION_KEY_MISSING_DETAIL) from exc
    return service.decrypt(row.encrypted_key)
