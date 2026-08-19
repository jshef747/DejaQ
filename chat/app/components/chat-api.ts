// Browser-side API utility for the standalone chat app.
// It only calls this Next.js app's /api/* routes. The workspace API key
// comes from the connect screen or Settings (localStorage) when set, otherwise
// the /api/* routes fall back to DEJAQ_API_KEY in chat/.env.local server-side.

import { loadApiKey, loadServerBaseUrl, type Attachment, type ModelProfile, type RoutingMode } from "./chat-store";

// Attach the user-selected DejaQ server + API key as headers the /api/*
// routes read. `overrides` lets the connect screen and the Settings modal test
// unsaved values; otherwise the saved settings are used. Empty values omit
// their header so routes fall back to their server-side default, which is how
// a blank key on the connect screen reaches the env DEJAQ_API_KEY.
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
  // "human" when the served cache entry holds an answer a person wrote through
  // Edit & Save. Null on a miss, and on an ordinary cache entry.
  answerAuthored: string | null;
  // Set when the SSE body broke part-way through the answer: `text` is
  // whatever arrived before the break, not a finished reply. The caller shows
  // it AND says so, because a silently truncated answer reads as a complete
  // one. Null on a clean stream.
  streamError: string | null;
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
  // Stop's client-side abort path. Aborting mid-fetch rejects the fetch()
  // below; aborting mid-stream rejects the pending reader.read() instead
  // (the stream is tied to the same controller) — both are handled below.
  signal?: AbortSignal,
): Promise<ChatResult> {
  // Measured here rather than read from x-dejaq-latency-ms, which the proxy
  // sets when the upstream RESPONSE HEAD arrives. That used to be the same
  // number: the gateway withheld its headers until the whole answer existed.
  // It streams now, so the head lands in ~150ms and the header would report a
  // 47-second answer as "153ms" - and poison the generated-answer baseline the
  // cache comparison comes from. Time to the last delta is what "how long did
  // this answer take" means, and only the client is still around to see it.
  const startedAt = Date.now();
  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...dejaqHeaders() },
      body: JSON.stringify({ messages, deptSlug, modelProfile, routingMode, attachment }),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      return { kind: "error", status: 0, message: "Stopped." };
    }
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
  const rawDistance = response.headers.get("x-dejaq-cache-distance");
  const cacheDistance = rawDistance !== null ? Number(rawDistance) : null;
  const cacheMatchedQuery = response.headers.get("x-dejaq-cache-matched-query") ?? null;
  const answerAuthored = response.headers.get("x-dejaq-answer-authored") ?? null;

  onMeta?.({ modelUsed, tier });

  // Parse SSE stream.
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";

  // The body now stays open for the whole generation, so it is the part of the
  // request most likely to fail: the proxy's AbortSignal.timeout(120s) fires
  // DURING the body rather than before the head, and a server-side error after
  // the last delta errors the stream instead of arriving as an HTTP status.
  // Either way `reader.read()` rejects, and an unhandled rejection here would
  // throw out of handleSend and leave the typing indicator spinning forever.
  // (A non-abort rejection here used to escape uncaught and strand the caller
  // in `generating` with no way out - the outer try/catch below is what fixes
  // that now, by turning it into a `streamError` result instead of a throw.)
  let streamError: string | null = null;
  try {
    outer: while (true) {
      let value: Uint8Array | undefined;
      let done: boolean;
      try {
        ({ value, done } = await reader.read());
      } catch (err) {
        // Stop aborted the signal while a read was pending — the stream is
        // already torn down by the browser; nothing left to cancel by hand.
        // This is the user's own Stop, not a connection failure, so it must
        // not fall into the streamError path below.
        if (err instanceof DOMException && err.name === "AbortError") break outer;
        throw err;
      }
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
  } catch {
    streamError = "The answer was cut off before it finished streaming. What you see below is incomplete.";
  }

  // Nothing arrived at all: there is no partial answer worth keeping, so this
  // is an ordinary failed send and the caller reverts the turn for a retry.
  if (streamError && !text) {
    return {
      kind: "error",
      status: 0,
      message: "The connection dropped before the answer started. Try again.",
    };
  }

  const latencyMs = Date.now() - startedAt;

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
    answerAuthored,
    streamError,
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

export type EditStatus = "saved" | "created" | "not_cached" | "message_mismatch";

export interface EditSuccess {
  kind: "success";
  editStatus: EditStatus | null;
  // The entry the edit landed on. Differs from the one we sent when the answer
  // was served through an alias (the write redirects to its root) or when the
  // entry had to be created under a freshly derived key — so the caller adopts
  // it, or later feedback would address an entry that no longer holds this text.
  responseId: string | null;
  newScore?: number;
}

export type EditResult = EditSuccess | ApiError;

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

/** Save a human-edited answer. This IS the thumbs-up: one request carries the
 * corrected text and the positive rating, so the score lands on what the person
 * wrote rather than on the answer it replaced.
 *
 * `messages` is the request replay the server hash-verifies before using it to
 * build a cache entry that does not exist yet. Pass null for a turn that
 * carried an attachment — the replay is blind to the file, and the server will
 * only overwrite an existing gated entry rather than create an ungated one.
 */
export async function saveEditedAnswer(
  responseId: string | null,
  interactionId: string | null,
  messages: ChatApiMessage[] | null,
  editedAnswer: string,
  deptSlug: string,
): Promise<EditResult> {
  let response: Response;
  try {
    response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...dejaqHeaders() },
      body: JSON.stringify({
        responseId,
        interactionId,
        messages,
        editedAnswer,
        rating: "positive",
        comment: "",
        deptSlug,
      }),
    });
  } catch {
    return { kind: "error", status: 0, message: "Network error. Could not save the edit." };
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    return { kind: "error", status: response.status, message: userFacingError(response.status, detail) };
  }

  const data = await response.json();
  return {
    kind: "success",
    editStatus: data.editStatus ?? null,
    responseId: data.responseId ?? null,
    newScore: data.newScore,
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
