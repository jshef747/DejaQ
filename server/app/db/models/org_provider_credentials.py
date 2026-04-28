from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OrgProviderCredentials(Base):
    __tablename__ = "org_provider_credentials"
    __table_args__ = (
        UniqueConstraint("org_id", "provider", name="uq_org_provider_credentials_org_provider"),
        CheckConstraint(
            "provider IN ('google', 'openai', 'anthropic', 'mistral', 'cohere', 'together', 'groq', 'fireworks')",
            name="ck_org_provider_credentials_provider",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
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

    organization: Mapped["Organization"] = relationship(  # noqa: F821
        "Organization",
        back_populates="provider_credentials",
    )
