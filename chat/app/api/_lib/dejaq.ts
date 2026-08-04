import { NextResponse } from "next/server";

// Generous: a cold first request loads several Ollama models + the classifier serially.
export const API_TIMEOUT_MS = 120_000;
export const FEEDBACK_TIMEOUT_MS = 120_000;

export type ModelProfile = "default" | "weak_cpu";
export type RoutingMode = "auto" | "easy_local" | "hard_external";

interface DejaQConfig {
  apiBaseUrl: string;
  apiKey: string;
}

// Resolve the DejaQ backend URL. A client-supplied override (X-DejaQ-Server,
// set from the chat Settings modal so users can target a server on another
// machine) wins when it is a valid http(s) URL; otherwise fall back to the
// server-side default. Invalid overrides are ignored rather than erroring.
function resolveBaseUrl(override?: string | null): string {
  const fallback = process.env.DEJAQ_API_BASE_URL ?? "http://127.0.0.1:8000";
  const candidate = (override ?? "").trim();
  if (candidate) {
    try {
      const url = new URL(candidate);
      if (url.protocol === "http:" || url.protocol === "https:") {
        return candidate.replace(/\/$/, "");
      }
    } catch {
      // fall through to the default
    }
  }
  return fallback.trim().replace(/\/$/, "");
}

// Resolve the workspace API key. A client-supplied override (X-DejaQ-Key, set
// from the chat Settings modal so a workspace created during dev testing can
// be used without a restart) wins when non-empty; otherwise fall back to
// DEJAQ_API_KEY in chat/.env.local.
function resolveApiKey(override?: string | null): string {
  const candidate = (override ?? "").trim();
  return candidate || (process.env.DEJAQ_API_KEY?.trim() ?? "");
}

export function getDejaQConfig(
  serverOverride?: string | null,
  keyOverride?: string | null,
): DejaQConfig | NextResponse {
  const apiKey = resolveApiKey(keyOverride);
  if (!apiKey) {
    return NextResponse.json(
      {
        code: "missing_dejaq_api_key",
        message:
          "No DejaQ API key configured. Paste one into Settings, or set DEJAQ_API_KEY in chat/.env.local.",
      },
      { status: 424 },
    );
  }

  const apiBaseUrl = resolveBaseUrl(serverOverride);

  return { apiBaseUrl, apiKey };
}

export function isNextResponse(value: DejaQConfig | NextResponse): value is NextResponse {
  return value instanceof NextResponse;
}

export function buildGatewayHeaders(
  apiKey: string,
  deptSlug?: string,
  modelProfile: ModelProfile = "default",
  routingMode: RoutingMode = "auto",
  // True when the attachment was carried over from an earlier turn rather than
  // freshly picked. Diagnostic only — the server logs it and changes nothing.
  attachmentSticky = false,
): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${apiKey}`,
    "X-DejaQ-Model-Profile": modelProfile,
    "X-DejaQ-Routing-Mode": routingMode,
  };

  const dept = deptSlug?.trim();
  if (dept) headers["X-DejaQ-Department"] = dept;
  if (attachmentSticky) headers["X-DejaQ-Attachment-Sticky"] = "true";

  return headers;
}

export async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body?.detail ?? body?.message ?? "";
  } catch {
    return "";
  }
}

export function proxyError(status: number, message: string): NextResponse {
  return NextResponse.json(
    {
      code: "dejaq_backend_error",
      message: message.trim() || `DejaQ backend request failed (HTTP ${status}).`,
    },
    { status },
  );
}

export function backendUnavailableError(): NextResponse {
  return NextResponse.json(
    {
      code: "dejaq_backend_unavailable",
      message: "Could not reach the DejaQ backend. Check DEJAQ_API_BASE_URL in chat/.env.local.",
    },
    { status: 503 },
  );
}
