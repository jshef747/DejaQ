import { NextRequest, NextResponse } from "next/server";
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
        stream: false,
      }),
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
  } catch {
    return backendUnavailableError();
  }
  const latencyMs = Date.now() - fetchStart;

  if (!response.ok) {
    return proxyError(response.status, await parseErrorDetail(response));
  }

  const data = await response.json();
  const choice = data.choices?.[0];
  const usage = data.usage ?? {};

  return NextResponse.json({
    text: choice?.message?.content ?? "",
    modelUsed: response.headers.get("x-dejaq-model-used"),
    responseId: response.headers.get("x-dejaq-response-id"),
    conversationId: response.headers.get("x-dejaq-conversation-id"),
    promptDifficulty: response.headers.get("x-dejaq-prompt-difficulty"),
    promptTokens: usage.prompt_tokens ?? 0,
    completionTokens: usage.completion_tokens ?? 0,
    latencyMs,
  });
}
