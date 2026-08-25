import { describe, expect, it } from "vitest";
import {
  adoptedResponseId,
  draftChoiceNotice,
  hasPendingDrafts,
  rejectedDraftIds,
} from "./draft-choice";
import type { Draft } from "./chat-api";

const A: Draft = { label: "A", responseId: "ns:doc-a", content: "First answer.", distance: 0.02 };
const B: Draft = { label: "B", responseId: "ns:doc-b", content: "Second answer.", distance: 0.023 };

describe("hasPendingDrafts", () => {
  it("asks when two drafts arrived and none is kept", () => {
    expect(hasPendingDrafts({ drafts: [A, B] })).toBe(true);
  });

  it("never asks again once a draft is kept", () => {
    expect(hasPendingDrafts({ drafts: [A, B], chosenDraftLabel: "B" })).toBe(false);
  });

  it("does not ask on an ordinary turn", () => {
    expect(hasPendingDrafts({})).toBe(false);
    expect(hasPendingDrafts({ drafts: null })).toBe(false);
  });

  it("does not ask when only one draft survived", () => {
    expect(hasPendingDrafts({ drafts: [A] })).toBe(false);
  });
});

describe("rejectedDraftIds", () => {
  it("returns every draft but the one kept", () => {
    expect(rejectedDraftIds([A, B], B)).toEqual(["ns:doc-a"]);
    expect(rejectedDraftIds([A, B], A)).toEqual(["ns:doc-b"]);
  });

  it("identifies by response id, not by label or text", () => {
    const sameLabel: Draft = { ...B, label: "A" };
    expect(rejectedDraftIds([A, sameLabel], sameLabel)).toEqual(["ns:doc-a"]);
  });
});

describe("adoptedResponseId", () => {
  it("prefers the id the server actually scored", () => {
    // An alias-served id redirects to its root, so the two differ.
    expect(adoptedResponseId("ns:root", B)).toBe("ns:root");
  });

  it("falls back to the kept draft when the server returned none", () => {
    expect(adoptedResponseId(null, B)).toBe("ns:doc-b");
  });
});

describe("draftChoiceNotice", () => {
  it("says nothing on the ordinary success case", () => {
    expect(draftChoiceNotice("recorded")).toBeNull();
    expect(draftChoiceNotice(null)).toBeNull();
  });

  it("says so when the pick changed nothing", () => {
    const notice = draftChoiceNotice("not_found");
    expect(notice?.title).toBe("Choice not saved");
  });
});
