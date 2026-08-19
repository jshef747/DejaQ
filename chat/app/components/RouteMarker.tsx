"use client";

import { useEffect, useState } from "react";
import { formatLatency, ROUTE_STYLE, type Route } from "./provenance";

// The ring hung on the provenance rail: a route-coloured circle with the
// latency set underneath in mono. Every answer gets exactly one of these,
// so a scrolled conversation reads as its own cost history.
export function RouteRing({
  route,
  latencyMs,
  active = false,
}: {
  route: Route;
  latencyMs?: number;
  active?: boolean;
}) {
  const s = ROUTE_STYLE[route];
  return (
    <div style={{ alignItems: "center", display: "flex", flexDirection: "column", gap: "10px" }}>
      <div
        style={{
          alignItems: "center",
          background: s.bg,
          border: `1.5px solid ${active ? s.solid : s.border}`,
          borderRadius: "50%",
          boxShadow: active ? `0 0 0 5px var(--bg), 0 0 0 8px ${s.bg}` : "0 0 0 5px var(--bg)",
          color: s.ink,
          display: "flex",
          height: "28px",
          justifyContent: "center",
          width: "28px",
        }}
      >
        <RouteIcon route={route} />
      </div>
      {latencyMs !== undefined && (
        <div
          style={{
            background: "var(--bg)",
            color: s.ink,
            fontFamily: "var(--font-mono)",
            fontSize: "10.5px",
            fontWeight: 500,
            lineHeight: "13px",
            padding: "0 4px",
          }}
        >
          {formatLatency(latencyMs)}
        </div>
      )}
    </div>
  );
}

// Shown on the rail while an answer is in flight. Neutral until the route is
// known (the pipeline hasn't decided cache-hit-vs-miss yet); once it is, the
// ring adopts that route's colour and an elapsed counter starts ticking —
// so an 18-second local generation reads as the product counting its own
// wait, not as a stalled spinner.
// The `route !== null` half of this (the coloured ring and its ticking elapsed
// counter) is unreachable against the shipped backend for the reason documented
// in TypingIndicator.tsx: headers arrive with the first token, never before it.
// Not dead code - keep it.
export function WaitRing({ route, sinceMs }: { route: Route | null; sinceMs: number | null }) {
  const [now, setNow] = useState(sinceMs);
  useEffect(() => {
    if (sinceMs === null) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [sinceMs]);

  if (!route) {
    return (
      <div
        style={{
          alignItems: "center",
          background: "var(--bg-2)",
          border: "1.5px solid var(--border-2)",
          borderRadius: "50%",
          boxShadow: "0 0 0 5px var(--bg)",
          color: "var(--fg-dimmer)",
          display: "flex",
          height: "28px",
          justifyContent: "center",
          width: "28px",
        }}
      >
        <PulseDots color="var(--fg-dimmer)" />
      </div>
    );
  }

  const elapsed = now !== null && sinceMs !== null ? now - sinceMs : 0;
  return (
    <div style={{ alignItems: "center", display: "flex", flexDirection: "column", gap: "10px" }}>
      <RouteRing route={route} />
      <div
        style={{
          background: "var(--bg)",
          color: ROUTE_STYLE[route].ink,
          fontFamily: "var(--font-mono)",
          fontSize: "10.5px",
          fontWeight: 500,
          lineHeight: "13px",
          padding: "0 4px",
        }}
      >
        {formatLatency(elapsed)}
      </div>
    </div>
  );
}

function PulseDots({ color }: { color: string }) {
  return (
    <div style={{ alignItems: "center", display: "flex", gap: "2.5px" }}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            animation: `bounce-dot 1.2s ease-in-out ${i * 0.2}s infinite`,
            background: color,
            borderRadius: "50%",
            display: "block",
            height: "3.5px",
            width: "3.5px",
          }}
        />
      ))}
    </div>
  );
}

export function RouteIcon({ route }: { route: Route }) {
  if (route === "cache") {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M13.5 7.4A5.6 5.6 0 0 0 3.4 5" />
        <path d="M2.5 8.6a5.6 5.6 0 0 0 10.1 2.4" />
        <path d="M3.3 2v3h3" />
        <path d="M12.7 14v-3h-3" />
      </svg>
    );
  }
  if (route === "local") {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <rect x="4.6" y="4.6" width="6.8" height="6.8" rx="1.3" />
        <path d="M6.4 1.9v2.7M9.6 1.9v2.7M6.4 11.4v2.7M9.6 11.4v2.7M1.9 6.4h2.7M1.9 9.6h2.7M11.4 6.4h2.7M11.4 9.6h2.7" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
      <path d="M4.7 12.6A3.15 3.15 0 0 1 5 6.4a4.35 4.35 0 0 1 8.3 1.3 2.65 2.65 0 0 1-.5 5.1H4.7z" />
    </svg>
  );
}
