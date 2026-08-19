"use client";

import type { ReactNode } from "react";

// TurnShell's own wrapper padding (16px) plus half of --rail (52px / 2 =
// 26px): the x-offset, from the wrapper's left edge, where every marker
// centres. RailTrack draws the hairline at this same offset so the line
// passes through the centre of every ring without per-turn coordination.
const SHELL_MAX_WIDTH = "calc(var(--shell) + 32px)";
const RAIL_CENTER = "42px";

// The continuous hairline down the left of the reading column. It shares
// TurnShell's exact centring formula (same maxWidth, same margin: auto), so
// its line lands under every turn's marker at any viewport width without
// either side needing to know the other's position.
export function RailTrack() {
  return (
    <div
      aria-hidden
      style={{
        bottom: 0,
        left: 0,
        margin: "0 auto",
        maxWidth: SHELL_MAX_WIDTH,
        // The track is positioned and the turns under it are not, so it paints
        // above them whatever the DOM order, and every control inside the
        // reading column — feedback thumbs, response detail, Retry — would be
        // clicking this hairline's box instead. It is decoration; it takes no
        // clicks.
        pointerEvents: "none",
        position: "absolute",
        right: 0,
        top: 0,
      }}
    >
      <div
        style={{
          background: "var(--border)",
          bottom: 0,
          left: RAIL_CENTER,
          position: "absolute",
          top: 0,
          width: "1px",
        }}
      />
    </div>
  );
}

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
      className="dq-turn"
      style={{
        display: "flex",
        margin: "0 auto",
        // The shell plus its own side padding, so the text column still
        // measures 704px once the padding is taken off.
        maxWidth: SHELL_MAX_WIDTH,
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
