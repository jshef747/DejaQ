export type WorkspaceItem = {
  id: number;
  name: string;
  slug: string;
  created_at: string;
};

export type DepartmentItem = {
  id: number;
  workspace_slug: string;
  name: string;
  slug: string;
  cache_namespace: string;
  created_at: string;
};

export type StatsMetrics = {
  requests: number;
  hits: number;
  misses: number;
  hit_rate: number;
  avg_latency_ms: number | null;
  est_tokens_saved: number;
  easy_count: number;
  hard_count: number;
  models_used: string[];
  truncation_rate: number;
};

export type DeptStatsItem = {
  workspace: string;
  department: string;
  department_name: string;
  requests: number;
  hits: number;
  misses: number;
  hit_rate: number;
  avg_latency_ms: number | null;
  est_tokens_saved: number;
  easy_count: number;
  hard_count: number;
  models_used: string[];
  truncation_rate: number;
};

export type DeptStatsReport = {
  workspace: string;
  items: DeptStatsItem[];
  total: DeptStatsItem;
};

export type ApiKeyItem = {
  id: number;
  token_prefix: string;
  created_at: string;
  revoked_at: string | null;
};

export type ApiKeyCreated = {
  id: number;
  workspace_slug: string;
  token: string;
  created_at: string;
};

export type ApiKeyRevoked = {
  id: number;
  revoked: boolean;
  already_revoked: boolean;
  revoked_at: string | null;
};

export type ApiKeyDeleted = {
  id: number;
  deleted: boolean;
};

export type RagDocumentItem = {
  id: number;
  title: string;
  kind: string;        // text | pdf | docx | markdown | url | image
  source: string;      // paste | upload | url | ocr
  source_ref: string | null;
  char_count: number;
  byte_size: number;
  chunk_count: number;
  status: "processing" | "ready" | "failed";
  progress_current: number;
  progress_total: number | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type LlmConfigResponse = {
  external_model: string | null;
  local_model: string | null;
  // Read-only, derived fresh from Ollama's /api/show on every read - not an
  // override, so it has no counterpart in LlmConfigUpdate. null means
  // unknown (Ollama unreachable, or local_model not installed there).
  local_model_supports_vision: boolean | null;
  generalizer_model: string | null;
  adjuster_model: string | null;
  enricher_model: string | null;
  normalizer_model: string | null;
  validator_model: string | null;
  enricher_system_prompt: string | null;
  normalizer_system_prompt: string | null;
  validator_system_prompt: string | null;
  validator_image_system_prompt: string | null;
  adjuster_system_prompt: string | null;
  generalizer_system_prompt: string | null;
  local_model_system_prompt: string | null;
  routing_threshold: number | null;
  // Which difficulty classifier is active: "legacy" (NVIDIA DeBERTa) or
  // "labse" (LaBSE, the shipped default). routing_threshold above is
  // LaBSE's own threshold; legacy_routing_threshold below is the legacy
  // classifier's own - the two score on completely different scales and
  // are never interchangeable.
  classifier_choice: "legacy" | "labse";
  legacy_routing_threshold: number | null;
  default_max_tokens: number;
  rewrite_max_tokens: number;
  ollama_num_ctx: number;
  // The shipped/global default for each token budget field, regardless of
  // whether this workspace overrides it - use this for a placeholder/hint
  // that says what clearing the field restores, never the effective fields
  // above (those show the override once one is set).
  token_budget_defaults: Record<TokenBudgetField, number>;
  // Alternative drafts (the semantic tie-breaker). Effective values -
  // override-or-default, like the token budgets above.
  drafts_enabled: boolean;
  drafts_max_distance: number;
  drafts_max_delta: number;
  // Same contract as token_budget_defaults: what clearing the field restores.
  draft_defaults: Record<DraftThresholdField, number>;
  overrides: Record<string, unknown>;
  is_default: boolean;
  updated_at: string | null;
  credentials_configured: string[];
};

export type LlmConfigUpdate = Partial<{
  external_model: string | null;
  local_model: string | null;
  generalizer_model: string | null;
  adjuster_model: string | null;
  enricher_model: string | null;
  normalizer_model: string | null;
  validator_model: string | null;
  enricher_system_prompt: string | null;
  normalizer_system_prompt: string | null;
  validator_system_prompt: string | null;
  validator_image_system_prompt: string | null;
  adjuster_system_prompt: string | null;
  generalizer_system_prompt: string | null;
  local_model_system_prompt: string | null;
  routing_threshold: number | null;
  classifier_choice: "legacy" | "labse" | null;
  legacy_routing_threshold: number | null;
  default_max_tokens: number | null;
  rewrite_max_tokens: number | null;
  ollama_num_ctx: number | null;
  drafts_enabled: boolean | null;
  drafts_max_distance: number | null;
  drafts_max_delta: number | null;
}>;

/** The two alternative-draft thresholds. `drafts_enabled` is a switch, not a
 * threshold, so it is deliberately not one of these. */
export type DraftThresholdField = "drafts_max_distance" | "drafts_max_delta";

/** Prompt field identifiers - keys into LlmConfigResponse/Update's
 * *_system_prompt fields. */
export type PromptField =
  | "enricher_system_prompt"
  | "normalizer_system_prompt"
  | "validator_system_prompt"
  | "validator_image_system_prompt"
  | "adjuster_system_prompt"
  | "generalizer_system_prompt"
  | "local_model_system_prompt";

/** Pipeline role identifiers - keys into LlmConfigResponse/Update's *_model
 * fields, used by the Pipeline page's flow + editor to address one stage. */
export type PipelineRole =
  | "enricher_model"
  | "normalizer_model"
  | "validator_model"
  | "adjuster_model"
  | "generalizer_model"
  | "local_model";

/** Token budget field identifiers - keys into LlmConfigResponse/Update's
 * integer override fields, used by the Pipeline page to attach a budget
 * editor to every stage it governs. */
export type TokenBudgetField = "default_max_tokens" | "rewrite_max_tokens" | "ollama_num_ctx";

export type AvailableModelsResponse = {
  models: string[];
  error: string | null;
};

export type CredentialItem = {
  provider: string;
  key_preview: string;
  created_at: string;
  updated_at: string;
};

// The new LiteLLM-backed catalog (migration stage A1). Providers are listed
// with counts only - GET /admin/v1/model-catalog/providers/{key}/models is
// fetched per provider, never all at once (the full catalog is 349 KB).
export type CatalogProviderItem = {
  key: string;
  model_count: number;
};

export type CatalogProvidersListResponse = {
  providers: CatalogProviderItem[];
};

export type CatalogModel = {
  id: string;
  deprecation_date: string | null;
};

export type CatalogProviderModelsResponse = {
  provider: string;
  models: CatalogModel[];
};

export type TestProviderResponse = {
  ok: boolean;
  model_used: string;
  provider: string;
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
};
