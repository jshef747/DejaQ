from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
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
    external_provider: Mapped[str | None] = mapped_column(String, nullable=True)
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
    # Which difficulty classifier this workspace routes on: "legacy" (NVIDIA
    # DeBERTa) or "labse" (LaBSE). NULL falls back to config.py's
    # DEFAULT_CLASSIFIER_CHOICE ("labse" - unchanged behaviour on upgrade).
    # `routing_threshold` above is LaBSE's own threshold; the two classifiers
    # score on different scales (legacy tops out ~0.30, LaBSE crosses ~0.50),
    # so a separate column below holds the legacy classifier's own threshold
    # rather than sharing this one - see llm_config_service.py.
    classifier_choice: Mapped[str | None] = mapped_column(String, nullable=True)
    legacy_routing_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per-workspace token budget overrides - each mirrors the global default
    # of the same name (lowercased) in app/config.py; NULL falls back to it.
    # See services/llm_config_service.py for the relationship validation
    # between the three (rewrite budget vs answer budget vs context window).
    default_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rewrite_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ollama_num_ctx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Ceiling on an attached file's extracted-text size (estimated tokens) for
    # local answering - independent of the three budgets above. Mirrors
    # LOCAL_ATTACHMENT_MAX_TOKENS in app/config.py; NULL falls back to it. See
    # that constant's comment and the size gate in openai_compat.py.
    local_attachment_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Alternative drafts (the semantic tie-breaker) - each mirrors the global
    # default of the same name in app/config.py (CACHE_DRAFTS_*); NULL falls
    # back to it. drafts_max_delta must not exceed drafts_max_distance, and
    # drafts_max_distance is capped at CACHE_TRUST_DISTANCE - both drafts are
    # validated (the served answer like any other hit, the alternate by its own
    # validator call on the tie path), so the trusted zone is the right bound; a
    # window past it would offer a candidate the pipeline does not serve
    # unguarded either. Enforced in services/llm_config_service.py.
    drafts_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    drafts_max_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    drafts_max_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
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
