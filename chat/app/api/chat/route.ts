import { NextRequest } from "next/server";
import {
  API_TIMEOUT_MS,
  backendUnavailableError,
  buildGatewayHeaders,
  getDejaQConfig,
  isNextResponse,
  parseErrorDetail,
  proxyError,
  type ModelProfile,
  type RoutingMode,
} from "../_lib/dejaq";

export const dynamic = "force-dynamic";

const SSE_HEADERS_TO_FORWARD = [
  "x-dejaq-model-used",
  "x-dejaq-interaction-id",
  "x-dejaq-tier",
  "x-dejaq-response-id",
  "x-dejaq-conversation-id",
  "x-dejaq-prompt-difficulty",
  "x-dejaq-prompt-difficulty-score",
  "x-dejaq-cache-distance",
  "x-dejaq-cache-matched-query",
];

export async function POST(request: NextRequest) {
  const config = getDejaQConfig();
  if (isNextResponse(config)) return config;

  const body = await request.json();
  let response: Response;
  const fetchStart = Date.now();
  try {
    response = await fetch(`${config.apiBaseUrl}/v1/chat/completions`, {
      method: "POST",
      headers: buildGatewayHeaders(
        config.apiKey,
        body.deptSlug,
        body.modelProfile as ModelProfile,
        body.routingMode as RoutingMode,
      ),
      body: JSON.stringify({
        model: "default",
        messages: body.messages,
        stream: true,
      }),
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
  } catch {
    return backendUnavailableError();
  }

  if (!response.ok) {
    return proxyError(response.status, await parseErrorDetail(response));
  }

  // Forward SSE headers from the upstream response plus our own latency measurement.
  const outHeaders: Record<string, string> = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
    "x-dejaq-latency-ms": String(Date.now() - fetchStart),
  };
  for (const h of SSE_HEADERS_TO_FORWARD) {
    const v = response.headers.get(h);
    if (v !== null) outHeaders[h] = v;
  }

  return new Response(response.body, { status: 200, headers: outHeaders });
}
