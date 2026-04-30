import type { Provider } from "@/lib/types";

// Last verified: 2026-04-28
// Sources: OpenAI models, Anthropic models overview, Google Gemini API models.
export const EXTERNAL_MODELS: Record<Provider, { value: string; label: string }[]> = {
  google: [
    { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
    { value: "gemini-2.5-flash-lite", label: "Gemini 2.5 Flash-Lite" },
    { value: "gemini-2.5-pro", label: "Gemini 2.5 Pro" },
  ],
  openai: [
    { value: "gpt-4.1-mini", label: "GPT-4.1 mini" },
    { value: "gpt-4.1", label: "GPT-4.1" },
    { value: "gpt-4o", label: "GPT-4o" },
    { value: "gpt-4o-mini", label: "GPT-4o mini" },
    { value: "o4-mini", label: "o4-mini" },
  ],
  anthropic: [
    { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
    { value: "claude-opus-4-6", label: "Claude Opus 4.6" },
  ],
};

export const DEFAULT_EXTERNAL_MODEL: Record<Provider, string> = {
  google: "gemini-2.5-flash",
  openai: "gpt-4.1-mini",
  anthropic: "claude-sonnet-4-6",
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
