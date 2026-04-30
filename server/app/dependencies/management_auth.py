from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

@dataclass(frozen=True)
class OrgRef:
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
    accessible_orgs: list[OrgRef] = field(default_factory=list)

    @property
    def is_system(self) -> bool:
        return self.actor_type == "system"

    def has_org_access(self, org_id: int) -> bool:
        if self.is_system:
            return True
        return any(o.id == org_id for o in self.accessible_orgs)

    def has_org_access_by_slug(self, slug: str) -> bool:
        if self.is_system:
            return True
        return any(o.slug == slug for o in self.accessible_orgs)

    @classmethod
    def system(cls) -> "ManagementAuthContext":
        return cls(actor_type="system")
