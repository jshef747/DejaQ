import { describe, expect, it } from "vitest";
import { outcomeLabel, renderTurnMarkdown, renderSessionHeader, type RawTurnInput } from "./session-log";

function baseTurn(overrides: Partial<RawTurnInput> = {}): RawTurnInput {
  return {
    turnNumber: 1,
    timestampMs: 1700000000000,
    originalQuestion: "What is DejaQ?",
    attachmentName: null,
    attachmentKind: null,
    ragDocumentTitle: null,
    outcome: "success",
    errorMessage: null,
    answerText: "DejaQ is a caching layer.",
    tier: "local",
    modelUsed: "gemma4:e4b",
    cacheDistance: null,
    cacheMatchedQuery: null,
    cacheEnrichedQuery: "What is DejaQ?",
    validatorVerdict: null,
    nearestCacheDistance: null,
    nearestCacheQuery: null,
    promptDifficulty: "easy",
    promptDifficultyScore: 0.12,
    latencyMs: 800,
    finishStatus: "completed",
    failureMessage: null,
    serverPromptTokens: 10,
    serverCompletionTokens: 20,
    ragChunks: null,
    answerAuthored: null,
    ...overrides,
  };
}

describe("outcomeLabel", () => {
  it("labels a cache hit", () => {
    expect(outcomeLabel(baseTurn({ tier: "cache" }))).toBe("Success - cache hit");
  });

  it("labels an external miss", () => {
    expect(outcomeLabel(baseTurn({ tier: "external" }))).toBe("Success - cache miss, answered by external model");
  });

  it("never claims success for an api error", () => {
    expect(outcomeLabel(baseTurn({ outcome: "api_error", errorMessage: "Network error." }))).toBe(
      "Error - request failed: Network error.",
    );
  });

  it("distinguishes an HTTP-200-but-empty answer from a real error", () => {
    expect(outcomeLabel(baseTurn({ outcome: "empty_answer" }))).toContain("HTTP 200 with no answer text");
  });

  it("marks a truncated stream as partial, not success", () => {
    expect(outcomeLabel(baseTurn({ finishStatus: "incomplete" }))).toContain("Partial answer");
  });

  it("marks a mid-stream pipeline failure honestly, with its message", () => {
    expect(outcomeLabel(baseTurn({ finishStatus: "failed", failureMessage: "vision unsupported" }))).toBe(
      "Error - generation failed: vision unsupported",
    );
  });

  it("marks a dropped connection as partial even though the outcome is 'success'", () => {
    expect(outcomeLabel(baseTurn({ errorMessage: "The answer was cut off before it finished streaming." }))).toContain(
      "Partial answer - stream did not finish cleanly",
    );
  });

  it("marks a user Stop as partial", () => {
    expect(outcomeLabel(baseTurn({ outcome: "stopped" }))).toContain("Partial answer - stopped by user");
  });
});

describe("renderTurnMarkdown", () => {
  it("never substitutes a stale difficulty score on a cache hit", () => {
    const md = renderTurnMarkdown(baseTurn({ tier: "cache", promptDifficulty: null, promptDifficultyScore: null }));
    expect(md).toContain("Not run (cache hit");
    expect(md).not.toMatch(/Difficulty label/);
  });

  it("reports a missing difficulty score as Not available, not None, when the pipeline gave nothing", () => {
    const md = renderTurnMarkdown(baseTurn({ tier: "local", promptDifficulty: null, promptDifficultyScore: null }));
    expect(md).toContain("Difficulty classification:** Not available");
  });

  it("distinguishes 'no rewrite happened' from 'not available' for the enriched question", () => {
    const md = renderTurnMarkdown(baseTurn({ cacheEnrichedQuery: null }));
    expect(md).toContain("None (no rewrite");
  });

  it("reports validator Not run distinctly from a real verdict", () => {
    const noCandidate = renderTurnMarkdown(baseTurn({ tier: "local", nearestCacheDistance: null, validatorVerdict: null }));
    expect(noCandidate).toContain("Not run (no candidate reached the validator)");

    const rejected = renderTurnMarkdown(
      baseTurn({ tier: "local", nearestCacheDistance: 0.18, nearestCacheQuery: "what is dejaq", validatorVerdict: "invalid" }),
    );
    expect(rejected).toContain("Validator result:** invalid");
    expect(rejected).toContain("Nearest cached question distance:** 0.1800");
  });

  it("labels token counts as provider-reported only on the external tier", () => {
    const external = renderTurnMarkdown(baseTurn({ tier: "external", serverPromptTokens: 5, serverCompletionTokens: 6 }));
    expect(external).toContain("provider-reported");

    const local = renderTurnMarkdown(baseTurn({ tier: "local", serverPromptTokens: 5, serverCompletionTokens: 6 }));
    expect(local).toContain("word-count estimate");
  });

  it("reports Not available for token counts when no terminal event arrived", () => {
    const md = renderTurnMarkdown(baseTurn({ serverPromptTokens: null, serverCompletionTokens: null }));
    expect(md).toContain("Token counts:** Not available");
  });

  it("always states adjustment outcome is not exposed, never inventing one", () => {
    const md = renderTurnMarkdown(baseTurn());
    expect(md).toContain("Adjustment outcome:** Not available (not exposed to the client on any path today)");
  });

  it("includes the attachment name and kind when present, and None when absent", () => {
    expect(renderTurnMarkdown(baseTurn({ attachmentName: "invoice.pdf", attachmentKind: "pdf" }))).toContain(
      "**Attachment:** invoice.pdf (pdf)",
    );
    expect(renderTurnMarkdown(baseTurn())).toContain("**Attachment:** None");
  });

  it("preserves the answer text verbatim, including markdown, without escaping it", () => {
    const md = renderTurnMarkdown(baseTurn({ answerText: "Use `foo()` and **bold** text." }));
    expect(md).toContain("Use `foo()` and **bold** text.");
  });
});

describe("renderSessionHeader", () => {
  it("names the conversation id and department, and never claims server-side session state", () => {
    const header = renderSessionHeader("conv_123", "demo", 1700000000000);
    expect(header).toContain("conv_123");
    expect(header).toContain("demo");
    expect(header).toContain("stateless");
  });
});
