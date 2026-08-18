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
    expect(isLossyHeaderText("What are the main benefits of semantic caching?", null)).toBe(false);
    expect(isLossyHeaderText("what does foo?.bar do", "what does foo?.bar do")).toBe(false);
    expect(isLossyHeaderText("why does /search?q=1 return 404", "why does /search?q=1 return 404")).toBe(false);
  });

  it("rejects a value the server truncated at its 200-character limit", () => {
    expect(isLossyHeaderText("a".repeat(199), null)).toBe(false);
    expect(isLossyHeaderText("a".repeat(200), null)).toBe(true);
  });

  it("rejects a replacement mark only when the typed question explains it", () => {
    expect(isLossyHeaderText("?????? ?????", "מה זה מטמון סמנטי")).toBe(true);
    expect(isLossyHeaderText("what doesn?t the cache store", "what doesn\u2019t the cache store")).toBe(true);
    expect(isLossyHeaderText("?????? ?????", "what is a semantic cache")).toBe(false);
  });
});
