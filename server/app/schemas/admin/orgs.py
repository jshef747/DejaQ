from datetime import datetime

from pydantic import BaseModel


class OrgItem(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime


class OrgCreate(BaseModel):
    name: str


class OrgDeleteResponse(BaseModel):
    deleted: bool
    departments_removed: int
