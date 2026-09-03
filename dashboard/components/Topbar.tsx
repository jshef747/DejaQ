"use client";

import { useEffect, useState } from "react";

interface TopbarProps {
  section: string;
  workspaceId?: string;
  extra?: React.ReactNode;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;
const HEALTH_CHECK_INTERVAL_MS = 15000;

function useBackendStatus(): "connected" | "unavailable" | "checking" {
  const [status, setStatus] = useState<"connected" | "unavailable" | "checking">("checking");

  useEffect(() => {
    let cancelled = false;

    async function check() {
      if (!API_BASE_URL) { if (!cancelled) setStatus("unavailable"); return; }
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 5000);
        const res = await fetch(`${API_BASE_URL}/health`, { signal: controller.signal });
        clearTimeout(timeout);
        if (!cancelled) setStatus(res.ok ? "connected" : "unavailable");
      } catch {
        if (!cancelled) setStatus("unavailable");
      }
    }

    check();
    const interval = setInterval(check, HEALTH_CHECK_INTERVAL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  return status;
}

export default function Topbar({ section, workspaceId, extra }: TopbarProps) {
  const status = useBackendStatus();
  const connected = status === "connected";

  return (
    <div className="ds-topbar">
      <div className="ds-breadcrumbs">
        {workspaceId && (
          <>
            <span className="ds-dimmer" style={{ fontFamily: "var(--font-mono)", fontSize: "11px" }}>{workspaceId}</span>
            <span className="sep">/</span>
          </>
        )}
        <span className="current">{section}</span>
      </div>

      <div className="ds-topbar-right">
        {extra}
        {status !== "checking" && (
          <div className="ds-env-pill" style={connected ? undefined : { background: "var(--red-bg)", borderColor: "var(--red-border)", color: "var(--red)" }}>
            <span className="ds-status-dot" style={connected ? undefined : { background: "var(--red)", boxShadow: "0 0 6px var(--red)" }} />
            {connected ? "all systems operational" : "backend unavailable"}
          </div>
        )}
        <div className="ds-env-pill">local</div>
      </div>
    </div>
  );
}
