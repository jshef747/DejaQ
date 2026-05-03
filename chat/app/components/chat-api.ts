// Browser-side API utility for the standalone chat app.
// It only calls this Next.js app's /api/* routes; DejaQ credentials stay
// server-side in chat/.env.local.

import type { ModelProfile, RoutingMode } from "./chat-store";

export interface ChatApiMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatSuccess {
  kind: "success";
  text: string;
  modelUsed: string | null;
  responseId: string | null;
  conversationId: string | null;
  promptDifficulty: string | null;
  promptTokens: number;
  completionTokens: number;
  latencyMs: number;
  cacheHit: boolean;
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
  401: "The server-side DejaQ API key was rejected. Check DEJAQ_API_KEY in chat/.env.local.",
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
): Promise<ChatResult> {
  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, deptSlug, modelProfile, routingMode }),
    });
  } catch {
    return { kind: "error", status: 0, message: "Network error. Could not reach the chat server." };
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    return { kind: "error", status: response.status, message: userFacingError(response.status, detail) };
  }

  const data = await response.json();
  const modelUsed = data.modelUsed ?? null;
  return {
    kind: "success",
    text: data.text ?? "",
    modelUsed,
    responseId: data.responseId ?? null,
    conversationId: data.conversationId ?? null,
    promptDifficulty: data.promptDifficulty ?? null,
    promptTokens: data.promptTokens ?? 0,
    completionTokens: data.completionTokens ?? 0,
    latencyMs: data.latencyMs ?? 0,
    cacheHit: modelUsed === "cache",
  };
}

export type FeedbackRating = "positive" | "negative";

export interface FeedbackSuccess {
  kind: "success";
  status: "ok" | "deleted";
  newScore?: number;
}

export type FeedbackResult = FeedbackSuccess | ApiError;

export async function sendFeedback(
  responseId: string,
  rating: FeedbackRating,
  comment: string,
  deptSlug: string,
): Promise<FeedbackResult> {
  let response: Response;
  try {
    response = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ responseId, rating, comment, deptSlug }),
    });
  } catch {
    return { kind: "error", status: 0, message: "Network error. Could not submit feedback." };
  }

  if (!response.ok) {
    const detail = await parseErrorDetail(response);
    return { kind: "error", status: response.status, message: userFacingError(response.status, detail) };
  }

  const data = await response.json();
  return { kind: "success", status: data.status, newScore: data.newScore };
}

export interface Department {
  id: number;
  label: string;
  slug: string;
}

export type DepartmentsResult = Department[] | ApiError;

export async function fetchDepartments(): Promise<DepartmentsResult> {
  try {
    const response = await fetch("/api/departments", { signal: AbortSignal.timeout(5000) });
    if (!response.ok) {
      const detail = await parseErrorDetail(response);
      return { kind: "error", status: response.status, message: userFacingError(response.status, detail) };
    }
    return (await response.json()) as Department[];
  } catch {
    return { kind: "error", status: 0, message: "Network error. Could not load departments." };
  }
}

export async function checkServerHealth(): Promise<{ reachable: boolean; celery: string; message?: string }> {
  try {
    const response = await fetch("/api/health", { signal: AbortSignal.timeout(5000) });
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
