from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WorkspaceLlmConfig(Base):
    __tablename__ = "workspace_llm_configs"

    workspace_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    external_model: Mapped[str | None] = mapped_column(String, nullable=True)
    local_model: Mapped[str | None] = mapped_column(String, nullable=True)
    generalizer_model: Mapped[str | None] = mapped_column(String, nullable=True)
    adjuster_model: Mapped[str | None] = mapped_column(String, nullable=True)
    enricher_model: Mapped[str | None] = mapped_column(String, nullable=True)
    normalizer_model: Mapped[str | None] = mapped_column(String, nullable=True)
    validator_model: Mapped[str | None] = mapped_column(String, nullable=True)
    # Prompt overrides - TEXT, not length-limited String: few-shots pushed some
    # shipped defaults to 1-2KB, and a custom prompt may run longer.
    enricher_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalizer_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    validator_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    validator_image_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    adjuster_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    generalizer_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_model_system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    routing_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per-workspace token budget overrides - each mirrors the global default
    # of the same name (lowercased) in app/config.py; NULL falls back to it.
    # See services/llm_config_service.py for the relationship validation
    # between the three (rewrite budget vs answer budget vs context window).
    default_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rewrite_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ollama_num_ctx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship(  # noqa: F821
        "Workspace",
        back_populates="llm_config",
    )
