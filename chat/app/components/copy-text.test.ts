import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./copy-text";

// The copy controls run on an insecure origin whenever `start.sh --lan` is
// used, where navigator.clipboard is undefined, and writeText can reject on a
// denied permission. Neither may throw out of a click handler.
describe("copyText", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("writes through the async clipboard when there is one", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    expect(await copyText("print(1)")).toBe(true);
    expect(writeText).toHaveBeenCalledWith("print(1)");
  });

  it("reports failure rather than throwing when there is no clipboard", async () => {
    vi.stubGlobal("navigator", {});
    vi.stubGlobal("document", undefined);

    expect(await copyText("print(1)")).toBe(false);
  });

  it("reports failure rather than throwing when the write is denied", async () => {
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    vi.stubGlobal("document", undefined);

    expect(await copyText("print(1)")).toBe(false);
  });

  it("falls back to the selection copy when the clipboard is unavailable", async () => {
    const remove = vi.fn();
    const area = { setAttribute: vi.fn(), select: vi.fn(), remove, style: {}, value: "" };
    const execCommand = vi.fn().mockReturnValue(true);
    vi.stubGlobal("navigator", {});
    vi.stubGlobal("document", {
      createElement: () => area,
      body: { appendChild: vi.fn() },
      execCommand,
    });

    expect(await copyText("print(1)")).toBe(true);
    expect(area.value).toBe("print(1)");
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(remove).toHaveBeenCalled();
  });
});
