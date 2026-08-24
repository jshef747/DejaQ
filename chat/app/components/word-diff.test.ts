import { describe, expect, it } from "vitest";
import { diffQueries, isLossyHeaderText } from "./word-diff";

describe("diffQueries", () => {
  it("marks only the changed word on a single typo", () => {
    const { typed, stored } = diffQueries(
      "What are the main benifits of semantic caching?",
      "What are the main benefits of semantic caching?",
    );
    expect(typed.filter((w) => w.changed).map((w) => w.text)).toEqual(["benifits"]);
    expect(stored.filter((w) => w.changed).map((w) => w.text)).toEqual(["benefits"]);
  });

  it("marks nothing changed on an exact match", () => {
    const { typed, stored } = diffQueries("same question", "same question");
    expect(typed.every((w) => !w.changed)).toBe(true);
    expect(stored.every((w) => !w.changed)).toBe(true);
  });
});

describe("isLossyHeaderText", () => {
  it("accepts ordinary questions, question marks and all", () => {
    expect(isLossyHeaderText("What are the main benefits of semantic caching?")).toBe(false);
    expect(isLossyHeaderText("what does foo?.bar do")).toBe(false);
    expect(isLossyHeaderText("why does /search?q=1 return 404")).toBe(false);
  });

  it("accepts non-Latin-1 text unchanged - headers are percent-encoded, not replaced", () => {
    expect(isLossyHeaderText("מה זה מטמון סמנטי")).toBe(false);
    expect(isLossyHeaderText("什么是语义缓存")).toBe(false);
  });

  it("rejects a value the server truncated at its 200-character limit", () => {
    expect(isLossyHeaderText("a".repeat(199))).toBe(false);
    expect(isLossyHeaderText("a".repeat(200))).toBe(true);
  });
});
