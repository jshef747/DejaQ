from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    departments: Mapped[list["Department"]] = relationship(  # noqa: F821
        "Department", back_populates="workspace", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(  # noqa: F821
        "ApiKey", back_populates="workspace", cascade="all, delete-orphan"
    )
    llm_config: Mapped["WorkspaceLlmConfig | None"] = relationship(  # noqa: F821
        "WorkspaceLlmConfig",
        back_populates="workspace",
        cascade="all, delete-orphan",
        uselist=False,
    )
    provider_credentials: Mapped[list["WorkspaceProviderCredentials"]] = relationship(  # noqa: F821
        "WorkspaceProviderCredentials",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    memberships: Mapped[list["UserWorkspaceMembership"]] = relationship(  # noqa: F821
        "UserWorkspaceMembership", back_populates="workspace", cascade="all, delete-orphan"
    )
