import { NextResponse } from "next/server";

export const API_TIMEOUT_MS = 30_000;
export const FEEDBACK_TIMEOUT_MS = 70_000;

export type ModelProfile = "default" | "weak_cpu";
export type RoutingMode = "auto" | "easy_local" | "hard_external";

interface DejaQConfig {
  apiBaseUrl: string;
  apiKey: string;
}

export function getDejaQConfig(): DejaQConfig | NextResponse {
  const apiKey = process.env.DEJAQ_API_KEY?.trim();
  if (!apiKey) {
    return NextResponse.json(
      {
        code: "missing_dejaq_api_key",
        message: "Chat app is missing DEJAQ_API_KEY in chat/.env.local.",
      },
      { status: 424 },
    );
  }

  const apiBaseUrl = (process.env.DEJAQ_API_BASE_URL ?? "http://127.0.0.1:8000")
    .trim()
    .replace(/\/$/, "");

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
): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${apiKey}`,
    "X-DejaQ-Model-Profile": modelProfile,
    "X-DejaQ-Routing-Mode": routingMode,
  };

  const dept = deptSlug?.trim();
  if (dept) headers["X-DejaQ-Department"] = dept;

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
