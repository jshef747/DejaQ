from datetime import datetime

from pydantic import BaseModel


class WorkspaceItem(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime


class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceUpdate(BaseModel):
    name: str


class WorkspaceDeleteResponse(BaseModel):
    deleted: bool
    departments_removed: int
