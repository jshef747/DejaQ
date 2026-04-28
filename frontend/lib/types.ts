export type OrgItem = {
  id: number;
  name: string;
  slug: string;
  created_at: string;
};

export type DepartmentItem = {
  id: number;
  org_slug: string;
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
};

export type DeptStatsItem = {
  org: string;
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
};

export type DeptStatsReport = {
  org: string;
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
  org_slug: string;
  token: string;
  created_at: string;
};

export type ApiKeyRevoked = {
  id: number;
  revoked: boolean;
  already_revoked: boolean;
  revoked_at: string | null;
};

export type Provider = "google" | "openai" | "anthropic";

export const LIVE_PROVIDERS: Provider[] = ["google", "openai", "anthropic"];

export type LlmConfigResponse = {
  external_model: string | null;
  local_model: string | null;
  routing_threshold: number | null;
  overrides: Record<string, unknown>;
  is_default: boolean;
  updated_at: string | null;
  credentials_configured: string[];
};

export type LlmConfigUpdate = Partial<{
  external_model: string | null;
  local_model: string | null;
  routing_threshold: number | null;
}>;

export type CredentialItem = {
  provider: string;
  key_preview: string;
  created_at: string;
  updated_at: string;
};

export type TestProviderResponse = {
  text: string;
  model_used: string;
  provider: string;
  latency_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
};
