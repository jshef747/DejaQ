import type { Provider } from "@/lib/types";

// Last verified: 2026-08-05
// Sources: OpenAI models (https://developers.openai.com/api/docs/models) and
// deprecations (https://developers.openai.com/api/docs/deprecations);
// Anthropic Claude models overview (https://platform.claude.com/docs/en/about-claude/models/overview);
// Google Gemini API models (https://ai.google.dev/gemini-api/docs/models).
// Each provider's full still-GA lineup is listed, not just the newest
// generation: availability is the test, not recency. Older generations are
// included as long as the vendor has not marked them deprecated/retired.
// Gemini keeps gemini-2.5-pro alongside the 3.x Flash tiers because Gemini
// 3.x has no GA Pro-class model yet (only a preview one); the Gemini 2.0
// family is excluded because it has been shut down per vendor docs.
export const EXTERNAL_MODELS: Record<Provider, { value: string; label: string }[]> = {
  google: [
    { value: "gemini-3.6-flash", label: "Gemini 3.6 Flash" },
    { value: "gemini-3.5-flash", label: "Gemini 3.5 Flash" },
    { value: "gemini-3.5-flash-lite", label: "Gemini 3.5 Flash-Lite" },
    { value: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash-Lite" },
    { value: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
    { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
    { value: "gemini-2.5-flash-lite", label: "Gemini 2.5 Flash-Lite" },
  ],
  openai: [
    { value: "gpt-5.6-sol", label: "GPT-5.6 Sol" },
    { value: "gpt-5.6-terra", label: "GPT-5.6 Terra" },
    { value: "gpt-5.6-luna", label: "GPT-5.6 Luna" },
    { value: "gpt-4.1", label: "GPT-4.1" },
    { value: "gpt-4.1-mini", label: "GPT-4.1 mini" },
    { value: "gpt-4o", label: "GPT-4o" },
    { value: "gpt-4o-mini", label: "GPT-4o mini" },
  ],
  anthropic: [
    { value: "claude-fable-5", label: "Claude Fable 5" },
    { value: "claude-opus-5", label: "Claude Opus 5" },
    { value: "claude-sonnet-5", label: "Claude Sonnet 5" },
    { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
    { value: "claude-opus-4-8", label: "Claude Opus 4.8" },
    { value: "claude-opus-4-7", label: "Claude Opus 4.7" },
    { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
    { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    { value: "claude-sonnet-4-5-20250929", label: "Claude Sonnet 4.5" },
    { value: "claude-opus-4-5-20251101", label: "Claude Opus 4.5" },
  ],
};

export const DEFAULT_EXTERNAL_MODEL: Record<Provider, string> = {
  google: "gemini-2.5-flash",
  openai: "gpt-5.6-terra",
  anthropic: "claude-sonnet-5",
};

export function providerForExternalModel(modelName: string | null | undefined): Provider {
  const model = (modelName ?? "").trim().toLowerCase();
  if (model.startsWith("gemini-")) return "google";
  if (model.startsWith("gpt-") || model.startsWith("o1-") || model.startsWith("o3-") || model.startsWith("o4-") || model.startsWith("chatgpt-")) {
    return "openai";
  }
  if (model.startsWith("claude-")) return "anthropic";
  return "google";
}

export function modelBelongsToProvider(modelName: string, provider: Provider) {
  return providerForExternalModel(modelName) === provider;
}
