"use client";

import TurnShell from "./ReadingColumn";
import { WaitRing } from "./RouteMarker";
import { ROUTE_STYLE, type Route } from "./provenance";

// Shown while waiting for the assistant's response. The rail marker appears
// immediately in a neutral "deciding" state; once the route is known
// (headers land before any content does) it adopts that route's colour and
// narrates what's happening, so an 18-second local generation reads as the
// product explaining its decision rather than as dead air.
export default function TypingIndicator({
  route,
  modelUsed,
  sinceMs,
}: {
  route: Route | null;
  modelUsed: string | null;
  sinceMs: number | null;
}) {
  return (
    <TurnShell gap={40} marker={<WaitRing route={route} sinceMs={sinceMs} />}>
      {route === "local" || route === "cloud" ? (
        <div
          style={{
            alignItems: "center",
            background: "var(--bg-3)",
            borderRadius: "9px",
            display: "flex",
            gap: "12px",
            height: "34px",
            padding: "0 12px",
          }}
        >
          <span style={{ alignItems: "center", color: "var(--fg-dimmer)", display: "flex", fontSize: "12px", gap: "6px" }}>
            <CheckIcon />
            Cache checked
          </span>
          <span style={{ background: "var(--border-2)", height: "14px", width: "1px" }} />
          <span style={{ color: "var(--fg-dim)", fontSize: "12.5px" }}>No stored answer close enough — generating on</span>
          <span style={{ color: ROUTE_STYLE[route].ink, fontFamily: "var(--font-mono)", fontSize: "12px", fontWeight: 500 }}>
            {modelUsed}
          </span>
        </div>
      ) : (
        <div
          style={{
            alignItems: "center",
            color: "var(--fg-dimmer)",
            display: "flex",
            fontSize: "12.5px",
            height: "27px",
          }}
        >
          Checking cache…
        </div>
      )}
    </TurnShell>
  );
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="var(--green)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3.2 8.4 6.4 11.6 12.8 5" />
    </svg>
  );
}
