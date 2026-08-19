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
  "x-dejaq-answer-authored",
];

interface ChatMsg {
  role: "user" | "assistant" | "system";
  content: string;
}

interface Attachment {
  dataUrl: string;
  kind: "image" | "pdf" | "docx" | "markdown";
  name: string;
  size: number;
  sticky: boolean;
}

// Convert the flat message list into Responses API `input` items, attaching the
// file (a data: URL) to the most recent user message. Images go as an
// input_image part; every other kind (PDF, DOCX, Markdown/text/code) goes as
// an input_file part — the server tells them apart by content, this route
// doesn't need to.
function buildResponsesInput(messages: ChatMsg[], attachment: Attachment) {
  const items = messages.map((m) => ({
    role: m.role,
    content: [{ type: "input_text", text: m.content }] as Array<Record<string, string>>,
  }));
  const part: Record<string, string> =
    attachment.kind === "image"
      ? { type: "input_image", image_url: attachment.dataUrl }
      : { type: "input_file", filename: attachment.name, file_data: attachment.dataUrl };
  for (let i = items.length - 1; i >= 0; i--) {
    if (items[i].role === "user") {
      items[i].content.push(part);
      break;
    }
  }
  return items;
}

function parseAttachment(value: unknown): Attachment | null {
  if (typeof value !== "object" || value === null) return null;
  const a = value as Record<string, unknown>;
  if (typeof a.dataUrl !== "string" || !a.dataUrl.startsWith("data:")) return null;
  if (a.kind !== "image" && a.kind !== "pdf" && a.kind !== "docx" && a.kind !== "markdown") return null;
  return {
    dataUrl: a.dataUrl,
    kind: a.kind,
    name: typeof a.name === "string" ? a.name : "",
    size: typeof a.size === "number" ? a.size : 0,
    sticky: a.sticky === true,
  };
}

export async function POST(request: NextRequest) {
  const config = getDejaQConfig(
    request.headers.get("x-dejaq-server"),
    request.headers.get("x-dejaq-key"),
  );
  if (isNextResponse(config)) return config;

  const body = await request.json();
  const attachment = parseAttachment(body.attachment);

  // Attachment requests must use the Responses API — it's the only endpoint that
  // accepts images and files, and the only one that runs the fingerprint gates.
  // Text-only requests stay on chat/completions. Both stream SSE; the client
  // parser handles both.
  const endpoint = attachment ? "/v1/responses" : "/v1/chat/completions";
  const payload = attachment
    ? { model: "default", input: buildResponsesInput(body.messages, attachment), stream: true }
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
        attachment?.sticky ?? false,
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

  // Forward SSE headers from the upstream response plus our own measurement of
  // how long the upstream took to send its RESPONSE HEAD. That is no longer the
  // same thing as how long the answer took: the gateway streams, so the head
  // arrives before generation starts. Kept as the diagnostic it now is - the
  // header lead over the first token - and deliberately not read as answer
  // latency; chat-api.ts times the stream itself for that.
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
