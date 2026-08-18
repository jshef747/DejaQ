"use client";

import { AssistantAvatar } from "./ChatMessage";
import TurnShell from "./ReadingColumn";

// Shown while waiting for the assistant's response. It renders through the
// same TurnShell, with the same avatar, as the answer that replaces it —
// so nothing moves when the first token lands.
export default function TypingIndicator() {
  return (
    <TurnShell gap={40} marker={<AssistantAvatar />}>
      <div
        style={{
          alignItems: "center",
          display: "flex",
          gap: "5px",
          // Centres the dots on the first line of the serif answer that
          // will take this spot (16.5/27).
          height: "27px",
        }}
      >
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            style={{
              animation: `bounce-dot 1.2s ease-in-out ${i * 0.2}s infinite`,
              background: "var(--fg-dimmer)",
              borderRadius: "50%",
              display: "block",
              height: "6px",
              width: "6px",
            }}
          />
        ))}
      </div>
    </TurnShell>
  );
}
