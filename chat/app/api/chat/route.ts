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

interface ChatMsg {
  role: "user" | "assistant" | "system";
  content: string;
}

// Convert the flat message list into Responses API `input` items, attaching the
// image (a data: URL) to the most recent user message as an input_image part.
function buildResponsesInput(messages: ChatMsg[], imageDataUrl: string) {
  const items = messages.map((m) => ({
    role: m.role,
    content: [{ type: "input_text", text: m.content }] as Array<Record<string, string>>,
  }));
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].role === "user") {
      items[i].content.push({ type: "input_image", image_url: imageDataUrl });
      break;
    }
  }
  return items;
}

export async function POST(request: NextRequest) {
  const config = getDejaQConfig(request.headers.get("x-dejaq-server"));
  if (isNextResponse(config)) return config;

  const body = await request.json();
  const hasImage = typeof body.image === "string" && body.image.startsWith("data:");

  // Image requests must use the Responses API — it's the only endpoint that
  // accepts images and runs the CLIP+dHash fingerprint gate. Text-only requests
  // stay on chat/completions. Both stream SSE; the client parser handles both.
  const endpoint = hasImage ? "/v1/responses" : "/v1/chat/completions";
  const payload = hasImage
    ? { model: "default", input: buildResponsesInput(body.messages, body.image), stream: true }
    : { model: "default", messages: body.messages, stream: true };

  let response: Response;
  const fetchStart = Date.now();
  try {
    response = await fetch(`${config.apiBaseUrl}${endpoint}`, {
      method: "POST",
      headers: buildGatewayHeaders(
        config.apiKey,
        body.deptSlug,
        body.modelProfile as ModelProfile,
        body.routingMode as RoutingMode,
      ),
      body: JSON.stringify(payload),
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
