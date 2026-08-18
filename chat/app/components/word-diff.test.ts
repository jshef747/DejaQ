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
  it("accepts an ordinary question, question mark and all", () => {
    expect(isLossyHeaderText("What are the main benefits of semantic caching?")).toBe(false);
    expect(isLossyHeaderText("Why? Because it is cached.")).toBe(false);
  });

  it("rejects a value the server truncated at its 200-character limit", () => {
    expect(isLossyHeaderText("a".repeat(199))).toBe(false);
    expect(isLossyHeaderText("a".repeat(200))).toBe(true);
  });

  it("rejects latin-1 replacement marks", () => {
    expect(isLossyHeaderText("what doesn?t the cache store")).toBe(true);
    expect(isLossyHeaderText("?????? ?????")).toBe(true);
    expect(isLossyHeaderText("the cache ? and the store")).toBe(true);
  });
});
