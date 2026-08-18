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
  label: string;
}

// var() strings, not resolved colours — these follow the active theme automatically.
export const ROUTE_STYLE: Record<Route, RouteStyle> = {
  cache: {
    ink: "var(--accent)",
    solid: "var(--accent-solid)",
    bg: "var(--accent-bg)",
    border: "var(--accent-border)",
    label: "cache",
  },
  local: {
    ink: "var(--local)",
    solid: "var(--local)",
    bg: "var(--local-bg)",
    border: "var(--local-border)",
    label: "local",
  },
  cloud: {
    ink: "var(--blue)",
    solid: "var(--blue)",
    bg: "var(--blue-bg)",
    border: "var(--blue-border)",
    label: "cloud",
  },
};

// Neutral marker styling for a route that isn't known yet. Deliberately not
// an entry in ROUTE_STYLE: it is the absence of a route, not a fourth one.
export const NEUTRAL_STYLE: RouteStyle = {
  ink: "var(--fg-dim)",
  solid: "var(--border-2)",
  bg: "var(--bg-3)",
  border: "var(--border-2)",
  label: "pending",
};

export function routeStyle(route: Route | null): RouteStyle {
  return route === null ? NEUTRAL_STYLE : ROUTE_STYLE[route];
}

export function formatLatency(ms: number | undefined): string {
  if (ms === undefined) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// How much faster this cache hit was than this session's own generated
// answers. The baseline is a client-side rolling average of non-cache
// latencies, so it does not exist until the session has generated at least
// one answer — null then, and every surface must say so rather than invent
// a number. One implementation because the answer strip and the response
// detail panel both quote it and must never disagree.
export function cacheSpeedup(
  latencyMs: number | undefined,
  baselineMs: number | null,
  sampleCount: number,
): number | null {
  if (latencyMs === undefined || baselineMs === null || sampleCount === 0) return null;
  return baselineMs / Math.max(latencyMs, 1);
}

export function formatMultiplier(multiplier: number): string {
  return `${multiplier.toFixed(multiplier >= 10 ? 0 : 1)}×`;
}
