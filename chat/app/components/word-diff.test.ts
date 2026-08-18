import { describe, expect, it } from "vitest";
import { diffQueries } from "./word-diff";

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
