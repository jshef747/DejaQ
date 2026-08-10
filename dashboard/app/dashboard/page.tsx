import { apiFetch } from "@/lib/api";
import Topbar from "@/components/Topbar";
import { listWorkspaces } from "@/app/actions/workspaces";
import { listDeptStatsRange } from "@/app/actions/stats";
import type { DeptStatsItem } from "@/lib/types";

export const dynamic = "force-dynamic";

const fmtPct = (n: number) => (n * 100).toFixed(1) + "%";

async function getBackendStatus(): Promise<"connected" | "unavailable"> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const res = await apiFetch("/health", { signal: controller.signal });
    clearTimeout(timeout);
    return res.ok ? "connected" : "unavailable";
  } catch {
    return "unavailable";
  }
}

async function getTodayStats(): Promise<{ total: DeptStatsItem; hint: string } | null> {
  try {
    const workspaces = await listWorkspaces();
    if (workspaces.length === 0) return null;
    const to = new Date();
    const from = new Date();
    from.setDate(from.getDate() - 1);
    const report = await listDeptStatsRange(
      workspaces[0].slug,
      from.toISOString().slice(0, 10),
      to.toISOString().slice(0, 10),
    );
    return { total: report.total, hint: `workspace ${workspaces[0].slug}` };
  } catch {
    return null;
  }
}

export default async function DashboardPage() {
  const email = "dev@localhost";
  const backendStatus = await getBackendStatus();
  const connected = backendStatus === "connected";
  const stats = connected ? await getTodayStats() : null;
  const total = stats?.total;
  const noDataHint = connected ? "no workspace yet" : "connect backend";
  const hint = total ? stats!.hint : noDataHint;

  const tiles = [
    { label: "Cache Hit Rate", value: total ? fmtPct(total.hit_rate) : "—", hint },
    { label: "Requests Today", value: total ? total.requests.toLocaleString() : "—", hint },
    {
      label: "Avg Latency",
      value: total?.avg_latency_ms != null ? `${total.avg_latency_ms.toFixed(0)}ms` : "—",
      hint,
    },
    { label: "Cost Saved", value: total ? `$${(total.est_tokens_saved * 0.000003).toFixed(2)}` : "—", hint },
  ];

  return (
    <>
      <Topbar section="Overview" />
      <div className="ds-page">
        {/* Header */}
        <div className="ds-page-header">
          <div>
            <h1 className="ds-page-title">Welcome back</h1>
            <p className="ds-page-sub">
              Signed in as{" "}
              <span style={{ fontFamily: "var(--font-mono)", color: "var(--fg)", fontSize: 12 }}>
                {email}
              </span>
            </p>
          </div>
        </div>

        {/* Backend health pill */}
        <div style={{ marginBottom: 24 }}>
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 10,
            background: connected ? "var(--green-bg)" : "var(--red-bg)",
            border: `1px solid ${connected ? "var(--green-border)" : "var(--red-border)"}`,
            borderRadius: 6, padding: "10px 14px", fontSize: 12,
          }}>
            <span style={{
              width: 8, height: 8, borderRadius: "50%",
              background: connected ? "var(--green)" : "var(--red)",
              boxShadow: connected ? "0 0 6px var(--green)" : "0 0 6px var(--red)",
              flexShrink: 0,
            }} />
            <span style={{ color: connected ? "var(--green)" : "var(--red)", fontWeight: 500 }}>
              {connected ? "Backend connected" : "Backend unavailable"}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-dimmer)" }}>
              {process.env.NEXT_PUBLIC_API_BASE_URL ?? "—"}
            </span>
          </div>
        </div>

        {/* KPI metric grid */}
        <div className="ds-metric-grid">
          {tiles.map((m) => (
            <div key={m.label} className="ds-metric">
              <div className="ds-metric-label">{m.label}</div>
              <div className="ds-metric-value" style={{ fontFamily: "var(--font-mono)" }}>{m.value}</div>
              {m.hint && <div className="ds-metric-delta">{m.hint}</div>}
            </div>
          ))}
        </div>

        {/* Quick-start card when backend unavailable */}
        {!connected && (
          <div className="ds-card" style={{ marginTop: 8 }}>
            <div className="ds-card-header">
              <p className="ds-card-title">Getting started</p>
            </div>
            <div className="ds-card-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                "1. Start the backend: ./start.sh --stack=server",
                "2. Create a workspace and API key (Workspaces → Keys)",
                "3. Set NEXT_PUBLIC_API_BASE_URL in dashboard/.env.local",
              ].map((step) => (
                <div key={step} style={{ display: "flex", alignItems: "flex-start", gap: 10, fontSize: 13, color: "var(--fg-dim)" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent)", flexShrink: 0 }}>›</span>
                  <code style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--fg)" }}>{step}</code>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
