import { afterEach, describe, expect, it, vi } from "vitest";
import { sendChatMessage, sendFeedback } from "./chat-api";

// A minimal SSE stream that mirrors what /api/chat actually sends: one
// content delta, then [DONE]. Headers are what sendChatMessage's callers
// (ResponseDetail's badges) rely on entirely - none of this is re-derived
// client-side, so a header the proxy drops or a name typo here would never
// throw, just silently show nothing.
function sseResponse(headers: Record<string, string>): Response {
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'));
      controller.enqueue(new TextEncoder().encode("data: [DONE]\n\n"));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers });
}

// Feedback race (server: feedback_service.py retry) still 404s once its retry
// budget is spent. The backend's real message must reach the user - not the
// generic "endpoint not found" text this status code used to be mapped to,
// which pointed the user at the wrong fix (server config, not a transient race).
describe("sendFeedback error mapping", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  // A 404 is the not-yet-stored race (the background store can still be
  // landing when the user presses feedback), so it must retry quietly rather
  // than surfacing the raw backend text immediately - and once its budget is
  // spent, the message must be honest, not "response_id not found".
  it("retries a persistent 404 for its full budget, then surfaces an honest message", async () => {
    vi.useFakeTimers();
    const notFound = () =>
      new Response(JSON.stringify({ code: "dejaq_backend_error", message: "response_id not found" }), {
        status: 404,
      });
    const fetchMock = vi.fn().mockResolvedValue(notFound());
    vi.stubGlobal("fetch", fetchMock);

    const promise = sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");
    await vi.advanceTimersByTimeAsync(15_000);
    const result = await promise;

    // 1 initial attempt + 4 retries = 5 calls.
    expect(fetchMock).toHaveBeenCalledTimes(5);
    expect(result).toEqual({
      kind: "error",
      status: 404,
      message: "Couldn't find this answer in the cache yet. It may still be saving - wait a moment and try again.",
    });
  });

  it("succeeds once a retry lands after the not-yet-stored race clears", async () => {
    vi.useFakeTimers();
    const notFound = new Response(JSON.stringify({ message: "response_id not found" }), { status: 404 });
    const ok = new Response(JSON.stringify({ status: "ok", newScore: 1.0 }), { status: 200 });
    const fetchMock = vi.fn().mockResolvedValueOnce(notFound).mockResolvedValueOnce(notFound).mockResolvedValueOnce(ok);
    vi.stubGlobal("fetch", fetchMock);

    const promise = sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");
    await vi.advanceTimersByTimeAsync(15_000);
    const result = await promise;

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(result).toEqual({
      kind: "success",
      status: "ok",
      newScore: 1.0,
      escalatedResponse: null,
      escalationStatus: null,
    });
  });

  // Any other error (422, network, 5xx...) is real and must not be retried or
  // delayed - only a 404 is the not-yet-stored race.
  it("does not retry a non-404 error", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Malformed." }), { status: 422 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result).toEqual({ kind: "error", status: 422, message: "Malformed." });
  });

  it("surfaces the backend's real detail on a 422 instead of the canned table text", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "No external model configured for this workspace. Configure a provider and model in Settings." }),
          { status: 422 },
        ),
      ),
    );

    const result = await sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");

    expect(result).toEqual({
      kind: "error",
      status: 422,
      message: "No external model configured for this workspace. Configure a provider and model in Settings.",
    });
  });

  it("falls back to the canned table text when the response body carries no message at all", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 422 })));

    const result = await sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");

    expect(result).toEqual({ kind: "error", status: 422, message: "Malformed request body." });
  });

  it("falls back to a generic message when neither a body detail nor a table entry exists", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 418 })));

    const result = await sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");

    expect(result).toEqual({ kind: "error", status: 418, message: "Request failed (HTTP 418)." });
  });

  it("still surfaces a DEJAQ_API_BASE_URL misconfiguration message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "DEJAQ_API_BASE_URL is not set." }), { status: 500 }),
      ),
    );

    const result = await sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");

    expect(result).toEqual({ kind: "error", status: 500, message: "DEJAQ_API_BASE_URL is not set." });
  });

  it("falls back to the canned table text on a raw FastAPI validation-error array instead of throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: [{ type: "missing", loc: ["body", "model"], msg: "Field required" }] }),
          { status: 422 },
        ),
      ),
    );

    const result = await sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");

    expect(result).toEqual({ kind: "error", status: 422, message: "Malformed request body." });
  });

  it("still surfaces the backend's message on a 424 missing-key response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "No DejaQ API key configured." }), { status: 424 }),
      ),
    );

    const result = await sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");

    expect(result).toEqual({ kind: "error", status: 424, message: "No DejaQ API key configured." });
  });
});

// F2/F3: the validator-verdict and nearest-cache-* headers are the server's
// own ground truth, forwarded by /api/chat's SSE_HEADERS_TO_FORWARD - chat
// must read the real values rather than guess from a distance threshold.
describe("sendChatMessage header parsing", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("parses the validator verdict and nearest-cache diagnostics", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse({
          "x-dejaq-tier": "cache",
          "x-dejaq-validator-verdict": "valid",
          "x-dejaq-nearest-cache-distance": "0.4123",
          "x-dejaq-nearest-cache-prompt": encodeURIComponent("a nearby stored question"),
        }),
      ),
    );

    const result = await sendChatMessage([{ role: "user", content: "hi" }], "eng");

    expect(result).toMatchObject({
      kind: "success",
      validatorVerdict: "valid",
      nearestCacheDistance: 0.4123,
      nearestCacheQuery: "a nearby stored question",
    });
  });

  it("reports null diagnostics when the server sends none", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse({ "x-dejaq-tier": "local" })));

    const result = await sendChatMessage([{ role: "user", content: "hi" }], "eng");

    expect(result).toMatchObject({
      kind: "success",
      validatorVerdict: null,
      nearestCacheDistance: null,
      nearestCacheQuery: null,
    });
  });

  it("still surfaces the enriched query on a miss, not just a cache hit", async () => {
    // F4's underlying data: the header itself is sent on a miss too.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse({
          "x-dejaq-tier": "local",
          "x-dejaq-enriched-query": encodeURIComponent("how many people live in Berlin, Germany?"),
        }),
      ),
    );

    const result = await sendChatMessage([{ role: "user", content: "how many people live there?" }], "eng");

    expect(result).toMatchObject({
      kind: "success",
      tier: "local",
      cacheEnrichedQuery: "how many people live in Berlin, Germany?",
    });
  });

  it("decodes the RAG document title header instead of leaving it percent-encoded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse({
          "x-dejaq-tier": "local",
          "x-dejaq-rag-document-title": encodeURIComponent("מדיניות החזרים והחזרות"),
        }),
      ),
    );

    const result = await sendChatMessage([{ role: "user", content: "hi" }], "eng");

    expect(result).toMatchObject({
      kind: "success",
      ragDocumentTitle: "מדיניות החזרים והחזרות",
    });
  });

  it("decodes a RAG document title with spaces", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseResponse({
          "x-dejaq-tier": "local",
          "x-dejaq-rag-document-title": encodeURIComponent("Return Policy Notes"),
        }),
      ),
    );

    const result = await sendChatMessage([{ role: "user", content: "hi" }], "eng");

    expect(result).toMatchObject({
      kind: "success",
      ragDocumentTitle: "Return Policy Notes",
    });
  });
});
