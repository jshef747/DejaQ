from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

@dataclass(frozen=True)
class WorkspaceRef:
    id: int
    name: str
    slug: str
    created_at: datetime


@dataclass(frozen=True)
class ManagementAuthContext:
    actor_type: Literal["user", "system"]
    # Populated for user actors only
    local_user_id: int | None = None
    supabase_user_id: str | None = None
    email: str | None = None
    accessible_workspaces: list[WorkspaceRef] = field(default_factory=list)

    @property
    def is_system(self) -> bool:
        return self.actor_type == "system"

    def has_workspace_access(self, workspace_id: int) -> bool:
        if self.is_system:
            return True
        return any(w.id == workspace_id for w in self.accessible_workspaces)

    def has_workspace_access_by_slug(self, slug: str) -> bool:
        if self.is_system:
            return True
        return any(w.slug == slug for w in self.accessible_workspaces)

    @classmethod
    def system(cls) -> "ManagementAuthContext":
        return cls(actor_type="system")

    @classmethod
    def local_dev(cls) -> "ManagementAuthContext":
        """Dev-admin context used when AUTH_MODE == 'local' (no Supabase).

        Full access like ``system()`` but carries a friendly email so /whoami
        reads sensibly. Local development only — never expose remotely.
        """
        return cls(actor_type="system", email="dev@localhost")
