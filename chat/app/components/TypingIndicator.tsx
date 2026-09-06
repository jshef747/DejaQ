"use client";

import type { CSSProperties } from "react";
import TurnShell from "./ReadingColumn";
import { WaitRing } from "./RouteMarker";
import { ROUTE_STYLE, type Route } from "./provenance";

const ESCALATION_DESTINATION: Record<"local" | "cloud", string> = {
  local: "the local model",
  cloud: "the external provider",
};

// Shown while waiting for the assistant's response. The rail marker appears
// immediately in a neutral "deciding" state; once the route is known (as soon
// as the gateway sends headers - see the note in the body) it adopts that
// route's colour and narrates what's happening, so an 18-second local
// generation reads as the product explaining its decision rather than as dead air.
export default function TypingIndicator({
  route,
  modelUsed,
  sinceMs,
  escalating = false,
}: {
  route: Route | null;
  modelUsed: string | null;
  sinceMs: number | null;
  // Set for a thumbs-down replay (ChatApp.handleFeedback): unlike a fresh
  // send, the destination is already known the instant the wait strip
  // mounts - there is no streaming response to carry headers ahead of the
  // answer - so it names that destination right away instead of opening on
  // the neutral "Checking cache…" state, then settles into the identical
  // generating-on-X look a fresh send ends up in for that same route. The
  // crossfade between the two is a CSS animation with a fixed timeline, not
  // JS state: it has nothing to clean up, so it can never outlive the real
  // request the wait strip is unmounted for (see ChatApp's isWaiting gate).
  escalating?: boolean;
}) {
  return (
    <TurnShell gap={40} marker={<WaitRing route={route} sinceMs={sinceMs} />}>
      {escalating && (route === "local" || route === "cloud") ? (
        <div style={{ height: "34px", position: "relative" }}>
          <div className="dq-escalation-intro" style={escalationPillStyle(route)}>
            Escalating to
            <span style={{ color: ROUTE_STYLE[route].ink, fontFamily: "var(--font-mono)", fontSize: "12px", fontWeight: 500 }}>
              {ESCALATION_DESTINATION[route]}
            </span>
          </div>
          <div className="dq-escalation-handoff" style={{ ...escalationPillStyle(route), left: 0, position: "absolute", top: 0 }}>
            Generating on
            <span style={{ color: ROUTE_STYLE[route].ink, fontFamily: "var(--font-mono)", fontSize: "12px", fontWeight: 500 }}>
              {modelUsed ?? ESCALATION_DESTINATION[route]}
            </span>
          </div>
        </div>
      ) : (
        /*
          Reachable since the gateway started streaming: run_chat_pipeline
          returns before generation on a cache miss, so the X-DejaQ-* headers
          this branch (and WaitRing's ticking counter) read now land seconds
          ahead of the first token - measured 0.2-0.8s to headers against
          9-15s to first content. The neutral "Checking cache…" state below is
          what renders until they arrive, and all a cache hit ever shows,
          since a hit resolves before its headers.
        */
        route === "local" || route === "cloud" ? (
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
        )
      )}
    </TurnShell>
  );
}

function escalationPillStyle(route: "local" | "cloud"): CSSProperties {
  return {
    alignItems: "center",
    background: ROUTE_STYLE[route].bg,
    border: `1px solid ${ROUTE_STYLE[route].border}`,
    borderRadius: "9px",
    color: "var(--fg-dim)",
    display: "flex",
    fontSize: "12.5px",
    gap: "8px",
    height: "34px",
    padding: "0 12px",
    width: "fit-content",
  };
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="var(--green)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3.2 8.4 6.4 11.6 12.8 5" />
    </svg>
  );
}
