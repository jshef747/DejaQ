from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WorkspaceProviderCredentials(Base):
    """No CHECK constraint on `provider`: the set of valid providers is
    `app.services.provider_registry`, validated in Python at write time.
    Dropped by migration e5f6a7b8c9d0 - see that file for the constraint's
    actual (misnamed) name on already-migrated databases.
    """

    __tablename__ = "workspace_provider_credentials"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", name="uq_workspace_provider_credentials_workspace_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(  # noqa: F821
        "Workspace",
        back_populates="provider_credentials",
    )
