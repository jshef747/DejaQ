"use client";

import type { ReactNode } from "react";

/**
 * One turn, laid out on the reading column.
 *
 * 52px marker column + 24px gutter + 704px of text = 780px, centred at
 * every window width. The 704 is the point of the whole thing: it is
 * about 72 characters at the answer's size, against the ~150 a 82%-wide
 * bubble gave on a 1440px window.
 *
 * ChatMessage and TypingIndicator both render through this so the reply
 * cannot shift when the first token lands — they used to carry their own
 * copies of these numbers, and had drifted (gap 10 vs 28).
 */
export default function TurnShell({
  marker,
  children,
  gap,
}: {
  // Sits in the marker column, top-aligned with the first line of text.
  marker?: ReactNode;
  children: ReactNode;
  // Space below this turn, before the next one.
  gap: number;
}) {
  return (
    <div
      style={{
        display: "flex",
        margin: "0 auto",
        // The shell plus its own side padding, so the text column still
        // measures 704px once the padding is taken off.
        maxWidth: "calc(var(--shell) + 32px)",
        padding: `0 16px ${gap}px`,
        width: "100%",
      }}
    >
      <div
        style={{
          display: "flex",
          flex: "none",
          justifyContent: "center",
          width: "var(--rail)",
        }}
      >
        {marker}
      </div>
      <div style={{ flex: "none", width: "var(--gutter)" }} />
      <div style={{ flex: 1, maxWidth: "var(--col)", minWidth: 0 }}>{children}</div>
    </div>
  );
}
