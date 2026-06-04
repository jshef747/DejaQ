import { createClient } from "@/lib/supabase/server";
import { isLocalAuth } from "@/lib/authMode";
import { apiFetch } from "@/lib/api";
import Topbar from "@/components/Topbar";

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

export default async function DashboardPage() {
  let email = "dev@localhost";
  if (!isLocalAuth) {
    const supabase = await createClient();
    const { data: { user } } = await supabase.auth.getUser();
    email = user?.email ?? "unknown";
  }
  const backendStatus = await getBackendStatus();
  const connected = backendStatus === "connected";

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
          {[
            { label: "Cache Hit Rate", value: "—", delta: null, hint: "connect backend" },
            { label: "Requests Today",  value: "—", delta: null, hint: "" },
            { label: "Avg Latency",     value: "—", delta: null, hint: "" },
            { label: "Cost Saved",      value: "—", delta: null, hint: "" },
          ].map((m) => (
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
                "3. Set NEXT_PUBLIC_API_BASE_URL in frontend/.env.local",
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
