"""Per-workspace pipeline-config lookups shared by the off-request write paths.

Both feedback escalation and Edit & Save build cache entries outside the normal
chat request, and both need the same two questions answered: "does this
workspace override this pipeline role?" and "what is its answer-token budget?".
These lived in escalation.py first; they are here so answer_edit.py can reuse
them rather than grow a second copy that drifts.
"""

from __future__ import annotations

from app.config import DEFAULT_MAX_TOKENS
from app.services import llm_config_service, pipeline_config_cache


def effective_default_max_tokens(workspace_slug: str) -> int:
    """The workspace's effective answer-generation budget (override or the
    shipped DEFAULT_MAX_TOKENS) - unlike workspace_config_override below,
    this always returns a usable value since there's no "no override, pass
    None and let the callee's own default apply" path for a call-time
    max_tokens argument the way there is for a pooled service's model_name."""
    try:
        return pipeline_config_cache.get_effective_config(workspace_slug).default_max_tokens
    except llm_config_service.WorkspaceNotFound:
        return DEFAULT_MAX_TOKENS


def workspace_config_override(workspace_slug: str, field: str) -> str | None:
    """The workspace's override for `field` (e.g. "local_model",
    "generalizer_model", "enricher_model", "normalizer_model", or any of the
    matching "*_system_prompt" fields), or None when there isn't one -
    including when the workspace can't be resolved at all. None lets callers
    make the exact same no-override get_*_service() call these modules always
    made before per-workspace pipeline config existed.
    """
    try:
        config = pipeline_config_cache.get_effective_config(workspace_slug)
    except llm_config_service.WorkspaceNotFound:
        return None
    if field not in config.overrides:
        return None
    return getattr(config, field)
