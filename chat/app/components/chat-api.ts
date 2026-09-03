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

// x-dejaq-cache-matched-query / -enriched-query / -nearest-cache-prompt carry
// free user text (any script, em-dashes, curly quotes) percent-encoded by the
// server (openai_compat.py `_encode_header_text`) since HTTP headers are
// Latin-1 only. Malformed input can't actually reach here - the server always
// encodes - but a raw fallback is cheap insurance against a future drift.
// All three are decoded here; `nearestCacheQuery` is carried on ChatSuccess
// but not yet rendered anywhere - the near-miss diagnostic it would power
// isn't wired into the UI yet.
function decodeHeaderText(value: string | null): string | null {
  if (value === null) return null;
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
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
  // The standalone question the context enricher rewrote a follow-up into
  // before searching the cache. Null only when there was nothing to rewrite
  // (enrich() returned the message unchanged) - the server sends this header
  // on a cache miss too, not just a hit.
  cacheEnrichedQuery: string | null;
  // The server's own validator outcome for this response's cache lookup:
  // "valid" on every cache hit (skipped or actually run, the server doesn't
  // currently distinguish the two in this header), "invalid" when a
  // near-miss candidate was found and rejected on a miss. Null when no
  // candidate was close enough to validate at all.
  validatorVerdict: string | null;
  // Diagnostics for the closest cache entry when this answer did NOT come
  // from the cache (a miss that still had a near-miss candidate). Not
  // currently rendered anywhere in chat/ - forwarded so a future "why didn't
  // this hit" panel doesn't need another round of header plumbing.
  nearestCacheDistance: number | null;
  nearestCacheQuery: string | null;
  // Count of knowledge-base passages RAG injected on a miss it grounded.
  // Null on a cache hit or when nothing was retrieved.
  ragChunks: number | null;
  // Title of the knowledge-base document this answer was explicitly grounded
  // in, when the message referenced one with `@`. Null otherwise — including
  // when a reference was sent but the server has no title to report.
  ragDocumentTitle: string | null;
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
  422: "Malformed request body.",
  429: "Rate limited. Wait a moment and try again.",
  500: "Internal server error from the DejaQ backend.",
  503: "Service unavailable. Make sure the DejaQ server is running.",
};

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    // FastAPI's own request-validation errors put a list of {loc, msg, ...}
    // objects here, not a string — that's not a user-facing message, so it
    // falls through to HTTP_MESSAGES/generic below instead of being shown raw.
    const detail = body?.message ?? body?.detail;
    return typeof detail === "string" ? detail : "";
  } catch {
    return "";
  }
}

// The server's own message always wins — HTTP_MESSAGES is a last resort for
// responses that carry no usable detail/message, not a competing source of
// truth. Never add a per-status special case here again: a status the server
// already explains (424, DEJAQ_API_BASE_URL misconfig, ...) is handled by
// this same fallback-first check, with no table entry required.
function userFacingError(status: number, fallback: string): string {
  const trimmed = fallback.trim();
  if (trimmed) return trimmed;
  return HTTP_MESSAGES[status] ?? `Request failed (HTTP ${status}).`;
}

export async function sendChatMessage(
  messages: ChatApiMessage[],
  deptSlug: string,
  modelProfile: ModelProfile = "default",
  routingMode: RoutingMode = "auto",
  attachment: Attachment | null = null,
  // Catalog id of a knowledge-base document explicitly picked with `@`. Fetched
  // by exact id server-side — see CLAUDE.md's file-gate note for why exact
  // identity, not search, is the point.
  ragDocumentId: number | null = null,
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
      body: JSON.stringify({ messages, deptSlug, modelProfile, routingMode, attachment, ragDocumentId }),
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
  const cacheMatchedQuery = decodeHeaderText(response.headers.get("x-dejaq-cache-matched-query"));
  const answerAuthored = response.headers.get("x-dejaq-answer-authored") ?? null;
  const cacheEnrichedQuery = decodeHeaderText(response.headers.get("x-dejaq-enriched-query"));
  const validatorVerdict = response.headers.get("x-dejaq-validator-verdict") ?? null;
  const rawNearestDistance = response.headers.get("x-dejaq-nearest-cache-distance");
  const nearestCacheDistance = rawNearestDistance !== null ? Number(rawNearestDistance) : null;
  const nearestCacheQuery = decodeHeaderText(response.headers.get("x-dejaq-nearest-cache-prompt"));
  const rawRagChunks = response.headers.get("x-dejaq-rag-chunks");
  const ragChunks = rawRagChunks !== null ? Number(rawRagChunks) : null;
  const ragDocumentTitle = response.headers.get("x-dejaq-rag-document-title") ?? null;

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
    cacheEnrichedQuery,
    validatorVerdict,
    nearestCacheDistance,
    nearestCacheQuery,
    ragChunks,
    ragDocumentTitle,
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

async function postFeedback(
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

// The answer is stored to the cache in the background (generalize_and_store_task),
// after the response already reached the client - so a response_id the user is
// looking at right now can 404 for a second or two with no row to attach
// feedback to yet. The server's own /v1/feedback retries internally for ~1.7s
// (feedback_service._FEEDBACK_RETRY_DELAYS_SECONDS) before giving up; measured
// against a real running stack, the store itself can still land a few seconds
// after that - so the client retries the whole call again on top, on the same
// backoff shape, for a further ~10s before treating a 404 as real. A
// response_id that will never exist just pays this same wait and then still
// 404s - correctly, and with an honest message instead of the raw backend text.
const FEEDBACK_NOT_FOUND_RETRY_DELAYS_MS = [1000, 2000, 3000, 4000];

const FEEDBACK_STILL_NOT_FOUND_MESSAGE =
  "Couldn't find this answer in the cache yet. It may still be saving - wait a moment and try again.";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function sendFeedback(
  responseId: string | null,
  interactionId: string | null,
  messages: ChatApiMessage[] | null,
  rating: FeedbackRating,
  comment: string,
  deptSlug: string,
): Promise<FeedbackResult> {
  for (let attempt = 0; ; attempt++) {
    const result = await postFeedback(responseId, interactionId, messages, rating, comment, deptSlug);
    // Only a 404 is the not-yet-stored race; every other error (network, 422,
    // 401, 5xx...) is real and must surface immediately, unretried.
    if (!isApiError(result) || result.status !== 404) return result;
    if (attempt >= FEEDBACK_NOT_FOUND_RETRY_DELAYS_MS.length) {
      return { kind: "error", status: 404, message: FEEDBACK_STILL_NOT_FOUND_MESSAGE };
    }
    await sleep(FEEDBACK_NOT_FOUND_RETRY_DELAYS_MS[attempt]);
  }
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

// One knowledge-base document, as much as the `@` picker needs — never
// content. Mirrors Department above; GET /rag-documents is the same shape as
// GET /departments, same auth, same reason (the admin catalog is
// loopback-only and the chat app needs its own read of it).
export interface RagDocument {
  id: number;
  title: string;
  kind: string;
}

export type RagDocumentsResult = RagDocument[] | ApiError;

export async function fetchRagDocuments(
  overrides?: { server?: string; apiKey?: string },
): Promise<RagDocumentsResult> {
  try {
    const response = await fetch("/api/rag-documents", {
      headers: dejaqHeaders(overrides),
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) {
      const detail = await parseErrorDetail(response);
      return { kind: "error", status: response.status, message: userFacingError(response.status, detail) };
    }
    return (await response.json()) as RagDocument[];
  } catch {
    return { kind: "error", status: 0, message: "Network error. Could not load knowledge-base documents." };
  }
}

// A visible, dismissible guess at which knowledge-base document a question is
// about — POST /rag-suggest. Never grounds anything by itself; accepting one
// in the composer sets the same RagDocument state the `@` picker sets.
export interface RagSuggestion {
  documentId: number;
  title: string;
  snippet: string | null;
  distance: number | null;
}

// Failures (network, timeout, disabled) are indistinguishable from "no
// suggestion" here on purpose — a missed suggestion degrades to silence, the
// same as an unmatched question. Nothing about sending the message depends
// on this call ever succeeding.
export async function fetchRagSuggestion(
  query: string,
  signal?: AbortSignal,
): Promise<RagSuggestion | null> {
  try {
    const response = await fetch("/api/rag-suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...dejaqHeaders() },
      body: JSON.stringify({ query }),
      signal,
    });
    if (!response.ok) return null;
    const body = await response.json();
    if (typeof body?.document_id !== "number") return null;
    return {
      documentId: body.document_id,
      title: typeof body.title === "string" ? body.title : "",
      snippet: typeof body.snippet === "string" ? body.snippet : null,
      distance: typeof body.distance === "number" ? body.distance : null,
    };
  } catch {
    return null;
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
