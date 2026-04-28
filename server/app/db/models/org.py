from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    departments: Mapped[list["Department"]] = relationship(  # noqa: F821
        "Department", back_populates="organization", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["ApiKey"]] = relationship(  # noqa: F821
        "ApiKey", back_populates="organization", cascade="all, delete-orphan"
    )
    llm_config: Mapped["OrgLlmConfig | None"] = relationship(  # noqa: F821
        "OrgLlmConfig",
        back_populates="organization",
        cascade="all, delete-orphan",
        uselist=False,
    )
    provider_credentials: Mapped[list["OrgProviderCredentials"]] = relationship(  # noqa: F821
        "OrgProviderCredentials",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    memberships: Mapped[list["UserOrgMembership"]] = relationship(  # noqa: F821
        "UserOrgMembership", back_populates="organization", cascade="all, delete-orphan"
    )
