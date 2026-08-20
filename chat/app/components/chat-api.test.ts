import { afterEach, describe, expect, it, vi } from "vitest";
import { sendFeedback } from "./chat-api";

// Feedback race (server: feedback_service.py retry) still 404s once its retry
// budget is spent. The backend's real message must reach the user - not the
// generic "endpoint not found" text this status code used to be mapped to,
// which pointed the user at the wrong fix (server config, not a transient race).
describe("sendFeedback error mapping", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("surfaces the backend's real message on a 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: "dejaq_backend_error", message: "response_id not found" }), {
          status: 404,
        }),
      ),
    );

    const result = await sendFeedback("acme__eng:doc1", null, null, "positive", "", "eng");

    expect(result).toEqual({ kind: "error", status: 404, message: "response_id not found" });
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
