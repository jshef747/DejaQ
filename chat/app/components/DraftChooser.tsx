"use client";

import { useState } from "react";
import { MarkdownContent } from "./ChatMessage";
import type { Draft } from "./chat-api";

/** Two cached answers the embedding could not separate, offered as a choice.
 *
 * Tabbed rather than side by side, and that is a deliberate layout decision:
 * the reading column is 704px of serif prose carrying code blocks, tables and
 * KaTeX. Halving the measure to show both at once wrecks all three. One draft
 * occupies the full width; the toggle steps between them. It is the pattern
 * that survived into normal use in the products that ship this - a comparison
 * grid works when comparison is the whole purpose of the page, not inside a
 * chat transcript.
 *
 * The choice is optional. Draft A is the answer that was served, and a user who
 * ignores this entirely has a complete, correct answer already.
 */
export default function DraftChooser({
  drafts,
  busy,
  onChoose,
}: {
  drafts: Draft[];
  busy: boolean;
  onChoose: (draft: Draft) => void;
}) {
  const [active, setActive] = useState(0);
  const shown = drafts[active] ?? drafts[0];
  if (!shown) return null;

  return (
    <div>
      <div
        style={{
          alignItems: "center",
          display: "flex",
          gap: "10px",
          marginBottom: "14px",
        }}
      >
        <span style={{ color: "var(--fg-dim)", fontSize: "12.5px", fontWeight: 600 }}>
          Two close matches
        </span>
        <span
          title="Two saved answers scored almost identically for this question, so DejaQ is asking rather than guessing."
          style={{
            alignItems: "center",
            border: "1px solid var(--border-2)",
            borderRadius: "999px",
            color: "var(--fg-dimmer)",
            cursor: "help",
            display: "inline-flex",
            fontSize: "10px",
            height: "15px",
            justifyContent: "center",
            width: "15px",
          }}
          aria-label="Why am I seeing two answers?"
        >
          i
        </span>
      </div>

      {/* Segmented toggle. role=tablist so the two drafts read as one control
          with two panels rather than as two separate answers. */}
      <div
        role="tablist"
        aria-label="Alternative answers"
        style={{
          background: "var(--bg-2)",
          border: "1px solid var(--border)",
          borderRadius: "9px",
          display: "inline-flex",
          gap: "2px",
          marginBottom: "16px",
          padding: "3px",
        }}
      >
        {drafts.map((draft, index) => {
          const selected = index === active;
          return (
            <button
              key={draft.label}
              role="tab"
              aria-selected={selected}
              onClick={() => setActive(index)}
              style={{
                background: selected ? "var(--bg-3)" : "transparent",
                border: `1px solid ${selected ? "var(--border-2)" : "transparent"}`,
                borderRadius: "7px",
                color: selected ? "var(--fg)" : "var(--fg-dimmer)",
                cursor: "pointer",
                fontSize: "12px",
                fontWeight: selected ? 600 : 500,
                height: "26px",
                padding: "0 14px",
                transition: "background var(--t-base), color var(--t-base), border-color var(--t-base)",
              }}
            >
              Draft {draft.label}
            </button>
          );
        })}
      </div>

      <div role="tabpanel">
        <MarkdownContent content={shown.content} />
      </div>

      <div
        style={{
          borderTop: "1px solid var(--border)",
          marginTop: "20px",
          paddingTop: "14px",
        }}
      >
        <div style={{ color: "var(--fg-dim)", fontSize: "12.5px", marginBottom: "10px" }}>
          Which answer is better?
        </div>
        <div style={{ alignItems: "center", display: "flex", flexWrap: "wrap", gap: "8px" }}>
          {drafts.map((draft) => (
            <button
              key={draft.label}
              onClick={() => onChoose(draft)}
              disabled={busy}
              style={{
                alignItems: "center",
                background: "transparent",
                border: "1px solid var(--border-2)",
                borderRadius: "999px",
                color: busy ? "var(--fg-dimmer)" : "var(--fg-dim)",
                cursor: busy ? "not-allowed" : "pointer",
                display: "inline-flex",
                fontSize: "12px",
                fontWeight: 500,
                gap: "7px",
                height: "28px",
                opacity: busy ? 0.55 : 1,
                padding: "0 14px",
                transition: "background var(--t-base), border-color var(--t-base), color var(--t-base)",
              }}
              onMouseEnter={(e) => {
                if (busy) return;
                e.currentTarget.style.background = "var(--bg-3)";
                e.currentTarget.style.color = "var(--fg)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "transparent";
                e.currentTarget.style.color = busy ? "var(--fg-dimmer)" : "var(--fg-dim)";
              }}
            >
              Keep Draft {draft.label}
            </button>
          ))}
          {/* The blast radius, said plainly - the same register the answer
              editor uses. This is not a private preference. */}
          <span style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", marginLeft: "2px" }}>
            Your pick becomes the preferred answer for your department.
          </span>
        </div>
      </div>
    </div>
  );
}
