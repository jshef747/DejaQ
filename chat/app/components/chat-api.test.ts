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
});
