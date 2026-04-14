from datetime import datetime

from pydantic import BaseModel


class OrgCreate(BaseModel):
    name: str


class OrgRead(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime

    model_config = {"from_attributes": True}
