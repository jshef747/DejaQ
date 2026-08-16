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
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

export type Provider = "google" | "openai" | "anthropic";

export const LIVE_PROVIDERS: Provider[] = ["google", "openai", "anthropic"];

export type LlmConfigResponse = {
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
  default_max_tokens: number;
  rewrite_max_tokens: number;
  ollama_num_ctx: number;
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
  default_max_tokens: number | null;
  rewrite_max_tokens: number | null;
  ollama_num_ctx: number | null;
}>;

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

export type TestProviderResponse = {
  ok: boolean;
  model_used: string;
  provider: string;
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
};
