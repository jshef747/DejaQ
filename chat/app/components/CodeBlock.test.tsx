import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { codeChild } from "./CodeBlock";

// react-markdown nests the code text inside <pre><code>, sometimes split
// across several children. Both the language label and what the Copy button
// puts on the clipboard come from walking that tree.
describe("codeChild", () => {
  it("reads the language and the text out of a <code> child", () => {
    const code = createElement("code", { className: "language-python" }, "print(1)\n");
    expect(codeChild(code)).toEqual({ lang: "python", text: "print(1)\n" });
  });

  it("joins text split across nested children", () => {
    const code = createElement(
      "code",
      { className: "language-ts" },
      "const a = ",
      createElement("span", null, "1;"),
    );
    expect(codeChild(code)).toEqual({ lang: "ts", text: "const a = 1;" });
  });

  it("has no language when the fence gave none", () => {
    expect(codeChild(createElement("code", null, "plain")).lang).toBeNull();
  });

  it("survives a <pre> with no element child", () => {
    expect(codeChild("stray text")).toEqual({ lang: null, text: "" });
  });
});
