import { afterEach, describe, expect, it, vi } from "vitest";
import { isValidStoredConversation, loadConversations } from "./conversation-store";

// F1: one malformed conversation (e.g. messages: null, from a schema change
// or hand-edited localStorage) must not crash every reader downstream.
describe("isValidStoredConversation", () => {
  it("accepts a well-formed conversation", () => {
    expect(
      isValidStoredConversation({ id: "a", title: "t", messages: [], lastUpdated: 1 })
    ).toBe(true);
  });

  it("rejects messages: null, the exact shape that crashed RouteDashes", () => {
    expect(
      isValidStoredConversation({ id: "bad1", title: "Corrupt convo", messages: null, lastUpdated: Date.now() })
    ).toBe(false);
  });

  it("rejects a missing or wrong-typed field", () => {
    expect(isValidStoredConversation({ title: "t", messages: [], lastUpdated: 1 })).toBe(false);
    expect(isValidStoredConversation({ id: "a", title: "t", messages: "nope", lastUpdated: 1 })).toBe(false);
    expect(isValidStoredConversation({ id: "a", title: "t", messages: [], lastUpdated: "now" })).toBe(false);
  });

  it("rejects non-objects", () => {
    expect(isValidStoredConversation(null)).toBe(false);
    expect(isValidStoredConversation("nope")).toBe(false);
  });
});

describe("loadConversations", () => {
  const store = new Map<string, string>();
  const localStorageStub = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
  };

  afterEach(() => {
    store.clear();
    vi.unstubAllGlobals();
  });

  it("drops the corrupt entry from the report's exact localStorage payload and keeps the rest", () => {
    vi.stubGlobal("window", {});
    vi.stubGlobal("localStorage", localStorageStub);
    store.set(
      "dejaq_conversations",
      JSON.stringify([
        { id: "bad1", title: "Corrupt convo", messages: null, lastUpdated: Date.now() },
        { id: "good1", title: "Fine convo", messages: [], lastUpdated: 1 },
      ])
    );

    expect(loadConversations()).toEqual([{ id: "good1", title: "Fine convo", messages: [], lastUpdated: 1 }]);
  });
});
