import { describe, expect, it } from "vitest";
import { cacheComparison, classifyRoute } from "./provenance";

describe("classifyRoute", () => {
  it("returns null when nothing identifies the route", () => {
    expect(classifyRoute(null, null)).toBeNull();
    expect(classifyRoute(undefined, undefined)).toBeNull();
  });

  it("resolves cache only from an explicit cache signal", () => {
    expect(classifyRoute("cache", null)).toBe("cache");
    expect(classifyRoute(null, "cache")).toBe("cache");
    expect(classifyRoute("local", "gemma4:e4b")).toBe("local");
    expect(classifyRoute("external", "gemini-2.5-flash")).toBe("cloud");
    expect(classifyRoute(null, "gemini-2.5-flash")).toBe("cloud");
    expect(classifyRoute(null, "gemma4:e4b")).toBe("local");
  });
});

describe("cacheComparison", () => {
  it("has no baseline before the session generates an answer", () => {
    expect(cacheComparison(200, null, 0)).toEqual({ kind: "no-baseline" });
    expect(cacheComparison(200, 1000, 0)).toEqual({ kind: "no-baseline" });
    expect(cacheComparison(undefined, 1000, 3)).toEqual({ kind: "no-baseline" });
  });

  it("hands out a multiplier only above the meaningful threshold", () => {
    expect(cacheComparison(1000, 1050, 2)).toEqual({ kind: "not-faster" });
    expect(cacheComparison(1000, 1100, 2)).toEqual({ kind: "faster", multiplier: 1.1 });
  });

  it("never calls a slower cache hit faster", () => {
    expect(cacheComparison(3000, 1200, 4)).toEqual({ kind: "not-faster" });
  });
});
