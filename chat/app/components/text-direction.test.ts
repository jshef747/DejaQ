import { describe, expect, it } from "vitest";
import { textDirection } from "./text-direction";

describe("textDirection", () => {
  it("reads pure Hebrew as rtl", () => {
    expect(textDirection("מה בירת צרפת?")).toBe("rtl");
  });

  it("reads pure English as ltr", () => {
    expect(textDirection("What is the capital of France?")).toBe("ltr");
  });

  it("falls back to auto when there is no strong character", () => {
    expect(textDirection("42 · 100%")).toBe("auto");
  });

  it("picks the majority script when a Hebrew sentence embeds a Latin acronym", () => {
    // dir="auto" alone would misread this as ltr: it only looks at the first
    // strong character, which here is the "R" in "REST".
    expect(textDirection("REST API הוא ארכיטקטורה לתקשורת בין שרת ללקוח.")).toBe("rtl");
  });

  it("picks the majority script when an English sentence embeds a Hebrew name", () => {
    expect(textDirection("The capital of France is פריז, a lovely city.")).toBe("ltr");
  });
});
