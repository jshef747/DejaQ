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
  const config = getDejaQConfig(
    request.headers.get("x-dejaq-server"),
    request.headers.get("x-dejaq-key"),
  );
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
        ...(typeof body.editedAnswer === "string" ? { edited_answer: body.editedAnswer } : {}),
        ...(typeof body.chosenDraftResponseId === "string"
          ? { chosen_draft_response_id: body.chosenDraftResponseId }
          : {}),
        ...(Array.isArray(body.rejectedDraftResponseIds)
          ? { rejected_draft_response_ids: body.rejectedDraftResponseIds }
          : {}),
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
    editStatus: data.edit_status ?? null,
    // "recorded" scored the kept draft; "not_found" means it was already gone.
    draftChoice: data.draft_choice ?? null,
    // The entry the edit actually landed on, when the server redirected or
    // created one. Null on an ordinary thumbs-up.
    responseId: data.response_id ?? null,
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
