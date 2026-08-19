import { describe, expect, it } from "vitest";
import { matchesNewChatShortcut, NEW_CHAT_SHORTCUT } from "./shortcuts";

// The label the sidebar shows is derived from NEW_CHAT_SHORTCUT, so the
// matcher has to agree with it exactly — a hint for a chord that never fires
// is the bug this replaced.
function keyEvent(init: Partial<KeyboardEvent>): KeyboardEvent {
  return {
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    key: "a",
    ...init,
  } as KeyboardEvent;
}

describe("matchesNewChatShortcut", () => {
  it("matches the advertised chord on both platform modifiers", () => {
    const key = NEW_CHAT_SHORTCUT.key;
    expect(matchesNewChatShortcut(keyEvent({ metaKey: true, shiftKey: true, key }))).toBe(true);
    expect(matchesNewChatShortcut(keyEvent({ ctrlKey: true, shiftKey: true, key }))).toBe(true);
    expect(matchesNewChatShortcut(keyEvent({ metaKey: true, shiftKey: true, key: key.toUpperCase() }))).toBe(true);
  });

  it("ignores near misses", () => {
    const key = NEW_CHAT_SHORTCUT.key;
    expect(matchesNewChatShortcut(keyEvent({ metaKey: true, key }))).toBe(false);
    expect(matchesNewChatShortcut(keyEvent({ shiftKey: true, key }))).toBe(false);
    expect(matchesNewChatShortcut(keyEvent({ metaKey: true, shiftKey: true, altKey: true, key }))).toBe(false);
    expect(matchesNewChatShortcut(keyEvent({ metaKey: true, shiftKey: true, key: "p" }))).toBe(false);
  });
});
