from datetime import datetime

from pydantic import BaseModel


class DeptRead(BaseModel):
    id: int
    workspace_id: int
    name: str
    slug: str
    cache_namespace: str
    created_at: datetime

    model_config = {"from_attributes": True}
