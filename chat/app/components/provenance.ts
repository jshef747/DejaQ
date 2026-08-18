// Shared route classification + colour vocabulary for the provenance rail,
// the answer strip, and the sidebar dashes. One place so the three surfaces
// can never disagree about what a route is or what colour it gets.

export type Route = "cache" | "local" | "cloud";

// The server sends "cache" for cache hits; external models use well-known
// vendor prefixes (gemini-, gpt-, claude-, o1-/o3-/o4-); everything else is local.
export function classifyRoute(
  tier: "cache" | "local" | "external" | null | undefined,
  modelUsed: string | null | undefined,
): Route {
  if (tier === "cache" || (!tier && (!modelUsed || modelUsed === "cache"))) return "cache";
  if (tier === "external") return "cloud";
  if (tier === "local") return "local";
  const m = (modelUsed ?? "").toLowerCase();
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

export function formatLatency(ms: number | undefined): string {
  if (ms === undefined) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}
