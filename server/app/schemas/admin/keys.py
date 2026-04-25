from datetime import datetime

from pydantic import BaseModel


class KeyItem(BaseModel):
    id: int
    token_prefix: str
    created_at: datetime
    revoked_at: datetime | None


class KeyCreated(BaseModel):
    id: int
    org_slug: str
    token: str
    created_at: datetime


class KeyRevokeResponse(BaseModel):
    id: int
    revoked: bool
    already_revoked: bool
    revoked_at: datetime | None
