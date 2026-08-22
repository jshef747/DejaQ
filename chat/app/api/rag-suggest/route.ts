import { NextRequest, NextResponse } from "next/server";
import {
  backendUnavailableError,
  getDejaQConfig,
  isNextResponse,
  parseErrorDetail,
  proxyError,
} from "../_lib/dejaq";

export const dynamic = "force-dynamic";

// Short of the chat/attachment routes' 120s on purpose — this is a debounced
// background lookup, not an answer the user is waiting on, so a slow
// suggestion should just fail to appear rather than hold a fetch open that
// long. Not as short as the measured warm latency alone (well under a
// second — see firstmate/data/dejaq-rag-suggest/report.md) would suggest,
// though: the FIRST call in a freshly started process pays for loading the
// text embedder (measured ~6s cold on this machine), same one-time cost
// every other embed_text call already pays. 15s covers that plus margin.
const SUGGEST_TIMEOUT_MS = 15_000;

export async function POST(request: NextRequest) {
  const config = getDejaQConfig(
    request.headers.get("x-dejaq-server"),
    request.headers.get("x-dejaq-key"),
  );
  if (isNextResponse(config)) return config;

  const body = await request.json();
  const query = typeof body?.query === "string" ? body.query : "";

  let response: Response;
  try {
    response = await fetch(`${config.apiBaseUrl}/rag-suggest`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${config.apiKey}`,
      },
      body: JSON.stringify({ query }),
      signal: AbortSignal.timeout(SUGGEST_TIMEOUT_MS),
    });
  } catch {
    return backendUnavailableError();
  }

  if (!response.ok) {
    return proxyError(response.status, await parseErrorDetail(response));
  }

  return NextResponse.json(await response.json());
}
