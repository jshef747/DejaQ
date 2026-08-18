// Browser-side API utility for the standalone chat app.
// It only calls this Next.js app's /api/* routes. The workspace API key
// comes from Settings (localStorage) when set, otherwise the /api/* routes
// fall back to DEJAQ_API_KEY in chat/.env.local server-side.

import { loadApiKey, loadServerBaseUrl, type Attachment, type ModelProfile, type RoutingMode } from "./chat-store";

// Attach the user-selected DejaQ server + API key as headers the /api/*
// routes read. `overrides` lets the Settings modal test unsaved values;
// otherwise the saved settings are used. Empty values omit their header so
// routes fall back to their server-side default.
function dejaqHeaders(overrides?: { server?: string; apiKey?: string }): Record<string, string> {
  const server = (overrides?.server ?? loadServerBaseUrl()).trim();
  const apiKey = (overrides?.apiKey ?? loadApiKey()).trim();
  const headers: Record<string, string> = {};
  if (server) headers["X-DejaQ-Server"] = server;
  if (apiKey) headers["X-DejaQ-Key"] = apiKey;
  return headers;
}

export interface ChatApiMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatSuccess {
  kind: "success";
  text: string;
  modelUsed: string | null;
  interactionId: string | null;
  tier: "cache" | "local" | "external" | null;
  responseId: string | null;
  conversationId: string | null;
  promptDifficulty: string | null;
  promptTokens: number;
  completionTokens: number;
  latencyMs: number;
  cacheHit: boolean;
  // Already forwarded by /api/chat's SSE_HEADERS_TO_FORWARD — just not
  // surfaced to callers before. Both come straight from the cache lookup on
  // a hit; neither is fabricated or inferred.
  cacheDistance: number | null;
  cacheMatchedQuery: string | null;
}

// Route + model become known as soon as the response headers land, well
// before the first content delta — the wait strip narrates from this, not
// from a client-side guess.
export interface ChatMeta {
  modelUsed: string | null;
  tier: "cache" | "local" | "external" | null;
}

export interface ApiError {
  kind: "error";
  status: number;
  message: string;
}

export type ChatResult = ChatSuccess | ApiError;

export function isApiError(v: unknown): v is ApiError {
  return typeof v === "object" && v !== null && (v as ApiError).kind === "error";
}

const HTTP_MESSAGES: Record<number, string> = {
  401: "The DejaQ API key was rejected. Check the key in Settings, or DEJAQ_API_KEY in chat/.env.local.",
  402: "No external LLM credential configured for this organization. Add a provider key in the DejaQ dashboard.",
  403: "Access denied to this organization.",
  404: "Endpoint not found. Verify the chat app API routes and backend URL.",
  422: "Malformed request body.",
  429: "Rate limited. Wait a moment and try again.",
  500: "Internal server error from the DejaQ backend.",
  503: "Service unavailable. Make sure the DejaQ server is running.",
};

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body?.message ?? body?.detail ?? "";
  } catch {
    return "";
  }
}

function userFacingError(status: number, fallback: string): string {
  if (status === 424 || fallback.includes("DEJAQ_API_BASE_URL")) {
    return fallback.trim() || `Request failed (HTTP ${status}).`;
  }
  return HTTP_MESSAGES[status] ?? (fallback.trim() || `Request failed (HTTP ${status}).`);
}

export async function sendChatMessage(
  messages: ChatApiMessage[],
  deptSlug: string,
  modelProfile: ModelProfile = "default",
  routingMode: RoutingMode = "auto",
  attachment: Attachment | null = null,
  onDelta?: (chunk: string) => void,
  onMeta?: (meta: ChatMeta) => void,
): Promise<ChatResult> {
  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...dejaqHeaders() },
      body: JSON.stringify({ messages, deptSlug, modelProfile, routingMode, attachment }),
    });
  } catch {
    return { kind: "error", status: 0, message: "Network error. Could not reach the chat server." };
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    return { kind: "error", status: response.status, message: userFacingError(response.status, detail) };
  }

  // Read headers before consuming the body.
  const modelUsed = response.headers.get("x-dejaq-model-used") ?? null;
  const interactionId = response.headers.get("x-dejaq-interaction-id") ?? null;
  const rawTier = response.headers.get("x-dejaq-tier");
  const tier = rawTier === "cache" || rawTier === "local" || rawTier === "external" ? rawTier : null;
  const responseId = response.headers.get("x-dejaq-response-id") ?? null;
  const conversationId = response.headers.get("x-dejaq-conversation-id") ?? null;
  const promptDifficulty = response.headers.get("x-dejaq-prompt-difficulty") ?? null;
  const latencyMs = Number(response.headers.get("x-dejaq-latency-ms") ?? "0");
  const rawDistance = response.headers.get("x-dejaq-cache-distance");
  const cacheDistance = rawDistance !== null ? Number(rawDistance) : null;
  const cacheMatchedQuery = response.headers.get("x-dejaq-cache-matched-query") ?? null;

  onMeta?.({ modelUsed, tier });

  // Parse SSE stream.
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";

  outer: while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE events are separated by double newline.
    const parts = buffer.split("\n\n");
    buffer = parts.pop()!; // last incomplete chunk stays in buffer

    for (const part of parts) {
      for (const line of part.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        if (raw === "[DONE]") break outer;
        try {
          const chunk = JSON.parse(raw);
          // chat/completions chunk, or Responses API text delta (image requests
          // go through /v1/responses, whose stream uses response.output_text.delta).
          const delta: string =
            chunk?.choices?.[0]?.delta?.content ??
            (chunk?.type === "response.output_text.delta" ? chunk?.delta ?? "" : "");
          if (delta) {
            text += delta;
            onDelta?.(delta);
          }
        } catch {
          // malformed chunk — skip
        }
      }
    }
  }

  // Approximate token counts using the same formula the backend uses.
  const promptWords = messages.reduce((n, m) => n + m.content.split(/\s+/).length, 0);
  const promptTokens = Math.round(promptWords * 1.3);
  const completionTokens = Math.round(text.split(/\s+/).length * 1.3);

  return {
    kind: "success",
    text,
    modelUsed,
    interactionId,
    tier,
    responseId,
    conversationId,
    promptDifficulty,
    promptTokens,
    completionTokens,
    latencyMs,
    cacheHit: modelUsed === "cache",
    cacheDistance,
    cacheMatchedQuery,
  };
}

export type FeedbackRating = "positive" | "negative";

export interface FeedbackSuccess {
  kind: "success";
  status: "ok" | "deleted";
  newScore?: number;
  escalatedResponse?: {
    content: string;
    tier: "local" | "external";
    interactionId: string | null;
    responseId: string | null;
  } | null;
  escalationStatus?:
    | "answered"
    | "not_requested"
    | "no_further_escalation"
    | "no_credential"
    | "provider_error"
    | "timeout"
    | "message_mismatch"
    | "already_escalated"
    | null;
}

export type FeedbackResult = FeedbackSuccess | ApiError;

export async function sendFeedback(
  responseId: string | null,
  interactionId: string | null,
  messages: ChatApiMessage[] | null,
  rating: FeedbackRating,
  comment: string,
  deptSlug: string,
): Promise<FeedbackResult> {
  let response: Response;
  try {
    response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...dejaqHeaders() },
      body: JSON.stringify({ responseId, interactionId, messages, rating, comment, deptSlug }),
    });
  } catch {
    return { kind: "error", status: 0, message: "Network error. Could not submit feedback." };
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    return { kind: "error", status: response.status, message: userFacingError(response.status, detail) };
  }

  const data = await response.json();
  return {
    kind: "success",
    status: data.status,
    newScore: data.newScore,
    escalatedResponse: data.escalatedResponse ?? null,
    escalationStatus: data.escalationStatus ?? null,
  };
}

export interface Department {
  id: number;
  label: string;
  slug: string;
}

export type DepartmentsResult = Department[] | ApiError;

export async function fetchDepartments(
  overrides?: { server?: string; apiKey?: string },
): Promise<DepartmentsResult> {
  try {
    const response = await fetch("/api/departments", {
      headers: dejaqHeaders(overrides),
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      const detail = await parseErrorDetail(response);
      return { kind: "error", status: response.status, message: userFacingError(response.status, detail) };
    }
    return (await response.json()) as Department[];
  } catch {
    return { kind: "error", status: 0, message: "Network error. Could not load departments." };
  }
}

export async function checkServerHealth(
  overrides?: { server?: string; apiKey?: string },
): Promise<{ reachable: boolean; celery: string; message?: string }> {
  try {
    const response = await fetch("/api/health", {
      headers: dejaqHeaders(overrides),
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      const detail = await parseErrorDetail(response);
      return { reachable: false, celery: "", message: userFacingError(response.status, detail) };
    }
    const data = await response.json();
    return { reachable: data.status === "ok", celery: data.celery ?? "" };
  } catch {
    return { reachable: false, celery: "", message: "Network error. Could not reach the chat server." };
  }
}
