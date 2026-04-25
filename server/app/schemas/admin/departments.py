from datetime import datetime

from pydantic import BaseModel


class DepartmentItem(BaseModel):
    id: int
    org_slug: str
    name: str
    slug: str
    cache_namespace: str
    created_at: datetime


class DepartmentCreate(BaseModel):
    name: str


class DepartmentDeleteResponse(BaseModel):
    deleted: bool
    cache_namespace: str
