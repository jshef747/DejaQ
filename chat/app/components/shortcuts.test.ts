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
  // Cmd/Ctrl+N is browser-reserved (new window); Cmd/Ctrl+Shift+O turned out
  // to collide with Chrome's own Bookmark Manager shortcut on
  // Windows/Linux/ChromeOS. Pinned here so a future change can't silently
  // reintroduce a chord Chrome reserves - the test below would still pass
  // against a reserved chord since it only checks internal consistency.
  it("is not the reserved Cmd/Ctrl+N or the Bookmark-Manager-colliding Cmd/Ctrl+Shift+O", () => {
    expect(NEW_CHAT_SHORTCUT).not.toEqual({ key: "n", shift: false });
    expect(NEW_CHAT_SHORTCUT).not.toEqual({ key: "o", shift: true });
  });

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
