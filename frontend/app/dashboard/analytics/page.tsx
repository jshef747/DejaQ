import { redirect } from "next/navigation";
import Topbar from "@/components/Topbar";
import { listWorkspaces } from "@/app/actions/workspaces";
import { listDeptStatsRange } from "@/app/actions/stats";
import AnalyticsClient from "./AnalyticsClient";
import type { DeptStatsReport } from "@/lib/types";

export const dynamic = "force-dynamic";

function rangeToFromTo(range: string): { from: string; to: string } {
  const to = new Date();
  const from = new Date();
  const days = range === "24h" ? 1 : range === "30d" ? 30 : 7;
  from.setDate(from.getDate() - days);
  to.setDate(to.getDate() + 1);
  return {
    from: from.toISOString().slice(0, 10),
    to: to.toISOString().slice(0, 10),
  };
}

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string; range?: string }>;
}) {
  const { workspace, range: rangeParam } = await searchParams;
  const range = rangeParam && ["24h", "7d", "30d"].includes(rangeParam) ? rangeParam : "7d";

  let activeSlug = workspace;

  if (!activeSlug) {
    try {
      const workspaces = await listWorkspaces();
      if (workspaces.length > 0) {
        redirect(`/dashboard/analytics?workspace=${workspaces[0].slug}&range=${range}`);
      }
    } catch {
      // Fall through
    }
  }

  if (!activeSlug) {
    return (
      <>
        <Topbar section="Analytics" />
        <div style={{ padding: "24px 28px", flex: 1 }}>
          <h1 style={{ fontSize: "22px", fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 20px" }}>
            Analytics
          </h1>
          <div
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              color: "var(--fg-dim)",
              fontSize: "12px",
              padding: "20px 18px",
            }}
          >
            No workspaces found. Use the onboarding flow or run{" "}
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--fg)", fontSize: "11px" }}>
              dejaq-admin workspace create
            </span>
            , then come back here.
          </div>
        </div>
      </>
    );
  }

  const { from, to } = rangeToFromTo(range);

  let deptStats: DeptStatsReport = {
    workspace: activeSlug,
    items: [],
    total: {
      workspace: activeSlug,
      department: "",
      department_name: "",
      requests: 0,
      hits: 0,
      misses: 0,
      hit_rate: 0,
      avg_latency_ms: null,
      est_tokens_saved: 0,
      easy_count: 0,
      hard_count: 0,
      models_used: [],
    },
  };
  let error: string | null = null;

  try {
    deptStats = await listDeptStatsRange(activeSlug, from, to);
  } catch (e) {
    error = (e as Error).message;
  }

  return (
    <>
      <Topbar section="Analytics" workspaceId={activeSlug} />
      <AnalyticsClient
        workspaceSlug={activeSlug}
        range={range}
        deptStats={deptStats}
        error={error}
      />
    </>
  );
}
