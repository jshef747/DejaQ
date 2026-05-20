import { NextRequest, NextResponse } from "next/server";
import {
  FEEDBACK_TIMEOUT_MS,
  backendUnavailableError,
  buildGatewayHeaders,
  getDejaQConfig,
  isNextResponse,
  parseErrorDetail,
  proxyError,
} from "../_lib/dejaq";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const config = getDejaQConfig();
  if (isNextResponse(config)) return config;

  const body = await request.json();
  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}/v1/feedback`, {
      method: "POST",
      headers: buildGatewayHeaders(config.apiKey, body.deptSlug),
      body: JSON.stringify({
        ...(body.responseId ? { response_id: body.responseId } : {}),
        ...(body.interactionId ? { interaction_id: body.interactionId } : {}),
        rating: body.rating,
        ...(Array.isArray(body.messages) ? { messages: body.messages } : {}),
        ...(typeof body.comment === "string" && body.comment.trim()
          ? { comment: body.comment.trim() }
          : {}),
      }),
      signal: AbortSignal.timeout(FEEDBACK_TIMEOUT_MS),
    });
  } catch {
    return backendUnavailableError();
  }

  if (!response.ok) {
    return proxyError(response.status, await parseErrorDetail(response));
  }

  const data = await response.json();
  return NextResponse.json({
    status: data.status,
    newScore: data.new_score,
    escalatedResponse: data.escalated_response
      ? {
          content: data.escalated_response.content,
          tier: data.escalated_response.tier,
          interactionId: data.escalated_response.interaction_id ?? null,
          responseId: data.escalated_response.response_id ?? null,
        }
      : null,
    escalationStatus: data.escalation_status ?? null,
  });
}
