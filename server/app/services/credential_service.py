from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

import app.config as config
from app.db import credential_repo
from app.db.models.org_provider_credentials import OrgProviderCredentials

SUPPORTED_PROVIDERS = {
    "google",
    "openai",
    "anthropic",
    "mistral",
    "cohere",
    "together",
    "groq",
    "fireworks",
}


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
        org_id: int,
        provider: str,
        raw_key: str,
    ) -> OrgProviderCredentials:
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'.")
        stripped = raw_key.strip()
        if not stripped:
            raise ValueError("API key must not be empty.")
        encrypted = self.encrypt(stripped)
        return credential_repo.upsert_credential(session, org_id, provider, encrypted)

    def get_decrypted_key(self, session: Session, org_id: int, provider: str) -> str | None:
        row = credential_repo.get_credential(session, org_id, provider.lower())
        if row is None:
            return None
        return self.decrypt(row.encrypted_key)

    def list_masked(self, session: Session, org_id: int) -> list[dict]:
        rows = credential_repo.list_credentials(session, org_id)
        return [self._to_masked_dict(row) for row in rows]

    def delete(self, session: Session, org_id: int, provider: str) -> bool:
        provider = provider.lower()
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported provider '{provider}'.")
        return credential_repo.delete_credential(session, org_id, provider)

    def to_masked_response(self, row: OrgProviderCredentials) -> dict:
        return self._to_masked_dict(row)

    def _to_masked_dict(self, row: OrgProviderCredentials) -> dict:
        key = self.decrypt(row.encrypted_key)
        return {
            "provider": row.provider,
            "key_preview": self.mask(key),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
