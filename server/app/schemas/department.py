from datetime import datetime

from pydantic import BaseModel


class DeptCreate(BaseModel):
    org_slug: str
    name: str


class DeptRead(BaseModel):
    id: int
    org_id: int
    name: str
    slug: str
    cache_namespace: str
    created_at: datetime

    model_config = {"from_attributes": True}
