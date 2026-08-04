import type { Provider } from "@/lib/types";

// Last verified: 2026-08-04
// Sources: OpenAI models (https://developers.openai.com/api/docs/models) and
// deprecations (https://developers.openai.com/api/docs/deprecations);
// Anthropic Claude models overview (https://platform.claude.com/docs/en/about-claude/models/overview);
// Google Gemini API models (https://ai.google.dev/gemini-api/docs/models).
// Each provider's current-generation lineup is listed in full; older
// generations still GA but superseded by a full current-generation tier
// (e.g. OpenAI GPT-5.x/4.x, Claude 4.x) are omitted to keep the picker to a
// sensible working range. Gemini keeps gemini-2.5-pro alongside the 3.x
// Flash tiers because Gemini 3.x has no GA Pro-class model yet (only a
// preview one).
export const EXTERNAL_MODELS: Record<Provider, { value: string; label: string }[]> = {
  google: [
    { value: "gemini-3.6-flash", label: "Gemini 3.6 Flash" },
    { value: "gemini-3.5-flash", label: "Gemini 3.5 Flash" },
    { value: "gemini-3.5-flash-lite", label: "Gemini 3.5 Flash-Lite" },
    { value: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
    { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
    { value: "gemini-2.5-flash-lite", label: "Gemini 2.5 Flash-Lite" },
  ],
  openai: [
    { value: "gpt-5.6-sol", label: "GPT-5.6 Sol" },
    { value: "gpt-5.6-terra", label: "GPT-5.6 Terra" },
    { value: "gpt-5.6-luna", label: "GPT-5.6 Luna" },
  ],
  anthropic: [
    { value: "claude-fable-5", label: "Claude Fable 5" },
    { value: "claude-opus-5", label: "Claude Opus 5" },
    { value: "claude-sonnet-5", label: "Claude Sonnet 5" },
    { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
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
