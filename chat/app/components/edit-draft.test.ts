import { describe, expect, it } from "vitest";
import { canSave, editLanded, editStatusNotice, isSaveShortcut, normalizeDraft } from "./edit-draft";

describe("canSave", () => {
  it("rejects an empty or whitespace-only draft", () => {
    expect(canSave("the answer", "")).toBe(false);
    expect(canSave("the answer", "   \n  ")).toBe(false);
  });

  it("rejects a draft identical to the answer", () => {
    expect(canSave("the answer", "the answer")).toBe(false);
  });

  it("ignores a trailing-whitespace-only difference", () => {
    // Re-saving an untouched answer must not write to the shared cache just
    // because a textarea added a newline.
    expect(canSave("the answer", "the answer\n")).toBe(false);
    expect(canSave("the answer\n", "the answer")).toBe(false);
  });

  it("accepts a real change", () => {
    expect(canSave("the answer", "the correct answer")).toBe(true);
  });

  it("treats interior whitespace as a real change", () => {
    // Re-spacing a list is an edit — the stored text is what the person typed.
    expect(canSave("a\nb", "a\n\nb")).toBe(true);
  });
});

describe("normalizeDraft", () => {
  it("strips trailing whitespace and nothing else", () => {
    expect(normalizeDraft("  keep the lead\n\n")).toBe("  keep the lead");
  });
});

describe("isSaveShortcut", () => {
  const base = { key: "Enter", metaKey: false, ctrlKey: false, altKey: false };

  it("matches Cmd+Enter and Ctrl+Enter", () => {
    expect(isSaveShortcut({ ...base, metaKey: true })).toBe(true);
    expect(isSaveShortcut({ ...base, ctrlKey: true })).toBe(true);
  });

  it("ignores a bare Enter, so a newline stays a newline", () => {
    expect(isSaveShortcut(base)).toBe(false);
  });

  it("ignores the Alt variant", () => {
    expect(isSaveShortcut({ ...base, ctrlKey: true, altKey: true })).toBe(false);
  });
});

describe("editStatusNotice", () => {
  it("reports a landed edit as a success", () => {
    expect(editStatusNotice("saved")?.kind).toBe("success");
    expect(editStatusNotice("created")?.kind).toBe("success");
  });

  it("says plainly when the edit did not reach the cache", () => {
    // The failure mode this guards against is a silent no-op leaving the user
    // believing they corrected the answer for everyone.
    for (const status of ["not_cached", "message_mismatch"]) {
      const notice = editStatusNotice(status);
      expect(notice?.kind).toBe("info");
      expect(notice?.body).toMatch(/not cached|no cache entry/i);
    }
  });

  it("stays silent on an unknown or absent status", () => {
    expect(editStatusNotice(null)).toBeNull();
    expect(editStatusNotice("something-new")).toBeNull();
  });
});

describe("editLanded", () => {
  it("is true only when the server wrote the edit", () => {
    expect(editLanded("saved")).toBe(true);
    expect(editLanded("created")).toBe(true);
  });

  it("is false when nothing reached the cache", () => {
    // The server skips scoring in these cases, so the UI must not show the
    // terminal thumbs-up: it would claim a +1.0 nobody applied and remove the
    // only control left for rating the answer.
    expect(editLanded("not_cached")).toBe(false);
    expect(editLanded("message_mismatch")).toBe(false);
  });

  it("is false for an absent or unknown status", () => {
    expect(editLanded(null)).toBe(false);
    expect(editLanded(undefined)).toBe(false);
    expect(editLanded("something-new")).toBe(false);
  });
});
