"use client";

import { useEffect, useState } from "react";

// One definition of the New chat shortcut, so the keydown binding and the hint
// the sidebar renders are derived from the same place and cannot drift.
// Cmd/Ctrl+N is reserved by the browser for a new window and never reaches the
// page, which is why this is Cmd/Ctrl+Shift+O.
export const NEW_CHAT_SHORTCUT = { key: "o", shift: true } as const;

export function matchesNewChatShortcut(e: KeyboardEvent): boolean {
  return (
    (e.metaKey || e.ctrlKey) &&
    !e.altKey &&
    e.shiftKey === NEW_CHAT_SHORTCUT.shift &&
    e.key.toLowerCase() === NEW_CHAT_SHORTCUT.key
  );
}

function shortcutLabel(mac: boolean): string {
  return `${mac ? "⌘" : "Ctrl"}${NEW_CHAT_SHORTCUT.shift ? "⇧" : ""}${NEW_CHAT_SHORTCUT.key.toUpperCase()}`;
}

// Rendered from the non-Mac form first and swapped after mount, so the server
// and the first client render agree.
export function useNewChatShortcutLabel(): string {
  const [label, setLabel] = useState(() => shortcutLabel(false));
  useEffect(() => {
    if (/Mac|iPhone|iPad/i.test(navigator.userAgent)) setLabel(shortcutLabel(true));
  }, []);
  return label;
}
