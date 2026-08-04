import { NextRequest, NextResponse } from "next/server";
import {
  API_TIMEOUT_MS,
  backendUnavailableError,
  getDejaQConfig,
  isNextResponse,
  parseErrorDetail,
  proxyError,
} from "../_lib/dejaq";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const config = getDejaQConfig(
    request.headers.get("x-dejaq-server"),
    request.headers.get("x-dejaq-key"),
  );
  if (isNextResponse(config)) return config;

  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}/departments`, {
      headers: {
        Authorization: `Bearer ${config.apiKey}`,
      },
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
  } catch {
    return backendUnavailableError();
  }

  if (!response.ok) {
    return proxyError(response.status, await parseErrorDetail(response));
  }

  return NextResponse.json(await response.json());
}
