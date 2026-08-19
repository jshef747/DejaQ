// Shared route classification + colour vocabulary for the provenance rail,
// the answer strip, and the sidebar dashes. One place so the three surfaces
// can never disagree about what a route is or what colour it gets.

export type Route = "cache" | "local" | "cloud";

// The server sends "cache" for cache hits; external models use well-known
// vendor prefixes (gemini-, gpt-, claude-, o1-/o3-/o4-); everything else is local.
//
// Returns null when there is nothing to classify yet — a streaming answer
// before its headers land, or a response that carried neither header. That
// case must never fall through to a route: orange means cache and nothing
// else, so "unknown" gets the neutral marker instead of a wrong colour.
export function classifyRoute(
  tier: "cache" | "local" | "external" | null | undefined,
  modelUsed: string | null | undefined,
): Route | null {
  if (tier === "cache" || modelUsed === "cache") return "cache";
  if (tier === "external") return "cloud";
  if (tier === "local") return "local";
  if (!modelUsed) return null;
  const m = modelUsed.toLowerCase();
  if (m.startsWith("gemini-") || m.startsWith("gpt-") || m.startsWith("claude-") || m.startsWith("o1-") || m.startsWith("o3-") || m.startsWith("o4-")) {
    return "cloud";
  }
  return "local";
}

export interface RouteStyle {
  ink: string;
  solid: string;
  bg: string;
  border: string;
}

// var() strings, not resolved colours — these follow the active theme automatically.
export const ROUTE_STYLE: Record<Route, RouteStyle> = {
  cache: {
    ink: "var(--accent)",
    solid: "var(--accent-solid)",
    bg: "var(--accent-bg)",
    border: "var(--accent-border)",
  },
  local: {
    ink: "var(--local)",
    solid: "var(--local)",
    bg: "var(--local-bg)",
    border: "var(--local-border)",
  },
  cloud: {
    ink: "var(--blue)",
    solid: "var(--blue)",
    bg: "var(--blue-bg)",
    border: "var(--blue-border)",
  },
};

// Neutral marker styling for a route that isn't known yet. Deliberately not
// an entry in ROUTE_STYLE: it is the absence of a route, not a fourth one.
export const NEUTRAL_STYLE: RouteStyle = {
  ink: "var(--fg-dim)",
  solid: "var(--border-2)",
  bg: "var(--bg-3)",
  border: "var(--border-2)",
};

export function routeStyle(route: Route | null): RouteStyle {
  return route === null ? NEUTRAL_STYLE : ROUTE_STYLE[route];
}

export function formatLatency(ms: number | undefined): string {
  if (ms === undefined) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// How this cache hit compares with this session's own generated answers.
// The baseline is a client-side rolling average of non-cache latencies, so
// it does not exist until the session has generated at least one answer —
// "no-baseline" then, and every surface must say so rather than invent a
// number. "not-faster" is a real outcome, not an error: a hit that runs the
// context adjuster costs a second or two on top of the lookup, which a fast
// external generation can beat. Stating that as "0.6× faster" would be the
// opposite of the truth, so the multiplier is only ever handed out when it
// is genuinely above 1. One implementation because the answer strip and the
// response detail panel both quote it and must never disagree.
export type CacheComparison =
  | { kind: "no-baseline" }
  | { kind: "faster"; multiplier: number }
  | { kind: "not-faster" };

// Below this the multiplier rounds to "1.0×", which claims a speed-up that
// isn't there.
const MIN_MEANINGFUL_SPEEDUP = 1.1;

export function cacheComparison(
  latencyMs: number | undefined,
  baselineMs: number | null,
  sampleCount: number,
): CacheComparison {
  if (latencyMs === undefined || baselineMs === null || sampleCount === 0) return { kind: "no-baseline" };
  const multiplier = baselineMs / Math.max(latencyMs, 1);
  return multiplier >= MIN_MEANINGFUL_SPEEDUP ? { kind: "faster", multiplier } : { kind: "not-faster" };
}

export function formatMultiplier(multiplier: number): string {
  return `${multiplier.toFixed(multiplier >= 10 ? 0 : 1)}×`;
}
