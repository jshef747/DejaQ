"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { checkServerHealth, fetchDepartments, isApiError } from "./chat-api";
import type { ChatSettings } from "./chat-store";

interface Props {
  initialSettings: ChatSettings;
  onConnected: (settings: ChatSettings) => void;
  dashboardUrl: string;
}

type Status = "idle" | "testing" | "rejected" | "error";

// The connect form IS the screen — replaces the old settings-modal ambush
// that opened on every reload before the saved settings had even loaded.
// A department is picked automatically from whatever the key can see; a
// specific department is a Settings concern, not a first-run one.
export default function ConnectScreen({ initialSettings, onConnected, dashboardUrl }: Props) {
  const [serverBaseUrl, setServerBaseUrl] = useState(initialSettings.serverBaseUrl);
  const [apiKey, setApiKey] = useState(initialSettings.apiKey);
  const [showApiKey, setShowApiKey] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [errorText, setErrorText] = useState("");

  async function handleConnect(e: React.FormEvent) {
    e.preventDefault();
    const server = serverBaseUrl.trim();
    const key = apiKey.trim();
    if (status === "testing" || key.length === 0) return;
    setStatus("testing");
    setErrorText("");

    const health = await checkServerHealth({ server, apiKey: key });
    if (!health.reachable) {
      setStatus("error");
      setErrorText(health.message ?? "Could not reach the DejaQ server.");
      return;
    }

    const depts = await fetchDepartments({ server, apiKey: key });
    if (isApiError(depts)) {
      setStatus(depts.status === 401 ? "rejected" : "error");
      setErrorText(
        depts.status === 401
          ? "That key was rejected (401). Generate a fresh one under Keys in the dashboard."
          : depts.message,
      );
      return;
    }
    if (depts.length === 0) {
      setStatus("error");
      setErrorText("Connected, but this workspace has no departments yet. Create one in the dashboard.");
      return;
    }

    onConnected({
      serverBaseUrl: server,
      apiKey: key,
      deptSlug: depts[0].slug,
      modelProfile: initialSettings.modelProfile,
      routingMode: initialSettings.routingMode,
    });
  }

  const rejected = status === "rejected";
  const connecting = status === "testing";

  return (
    <div style={{ alignItems: "center", display: "flex", flex: 1, justifyContent: "center", minHeight: 0, paddingBottom: "40px" }}>
      <form onSubmit={handleConnect} style={{ width: "460px" }}>
        <div style={{ fontSize: "24px", fontWeight: 600, letterSpacing: "-0.024em", lineHeight: "30px" }}>
          Connect this chat to DejaQ
        </div>
        <div style={{ color: "var(--fg-dim)", fontSize: "14px", lineHeight: "22px", marginTop: "8px" }}>
          Paste a workspace API key. It is kept in this browser only and never leaves it except to the
          server below.
        </div>

        <div style={{ marginTop: "26px" }}>
          <FieldLabel>Workspace API key</FieldLabel>
          <div
            style={{
              alignItems: "center",
              background: "var(--bg-2)",
              border: `1.5px solid ${rejected ? "var(--red)" : "var(--border-2)"}`,
              borderRadius: "9px",
              display: "flex",
              gap: "8px",
              height: "38px",
              marginTop: "7px",
              padding: "0 6px 0 12px",
            }}
          >
            <input
              type={showApiKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                if (status !== "idle") setStatus("idle");
              }}
              placeholder="dq_..."
              spellCheck={false}
              autoComplete="off"
              style={{
                background: "transparent",
                border: "none",
                color: "var(--fg)",
                flex: 1,
                fontFamily: "var(--font-mono)",
                fontSize: "12.5px",
                height: "100%",
                outline: "none",
              }}
            />
            <button
              type="button"
              onClick={() => setShowApiKey((v) => !v)}
              aria-label={showApiKey ? "Hide API key" : "Show API key"}
              style={{
                alignItems: "center",
                background: "transparent",
                border: "none",
                color: "var(--fg-dimmer)",
                cursor: "pointer",
                display: "flex",
                flexShrink: 0,
                height: "28px",
                justifyContent: "center",
                width: "28px",
              }}
            >
              {showApiKey ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
          {(status === "rejected" || status === "error") && (
            <div style={{ alignItems: "flex-start", display: "flex", gap: "7px", marginTop: "8px" }}>
              <span style={{ color: "var(--red)", display: "flex", flexShrink: 0, paddingTop: "1px" }}>
                <ErrorIcon />
              </span>
              <span style={{ color: "var(--red)", fontSize: "12px", lineHeight: "18px" }}>{errorText}</span>
            </div>
          )}
        </div>

        <div style={{ marginTop: "20px" }}>
          <div style={{ alignItems: "baseline", display: "flex", gap: "8px" }}>
            <FieldLabel>Server</FieldLabel>
            <span style={{ color: "var(--fg-dimmer)", fontSize: "11px" }}>optional</span>
          </div>
          <input
            type="text"
            value={serverBaseUrl}
            onChange={(e) => setServerBaseUrl(e.target.value)}
            placeholder="http://127.0.0.1:8000"
            spellCheck={false}
            autoComplete="off"
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border-2)",
              borderRadius: "9px",
              color: "var(--fg-dim)",
              fontFamily: "var(--font-mono)",
              fontSize: "12.5px",
              height: "38px",
              marginTop: "7px",
              outline: "none",
              padding: "0 12px",
              width: "100%",
            }}
          />
          <div style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", marginTop: "7px" }}>
            Leave blank for the DejaQ server on this machine.
          </div>
        </div>

        <div style={{ alignItems: "center", display: "flex", gap: "9px", marginTop: "26px" }}>
          <button
            type="submit"
            disabled={connecting || apiKey.trim().length === 0}
            style={{
              alignItems: "center",
              background: "var(--accent-solid)",
              border: "1px solid var(--accent-solid)",
              borderRadius: "8px",
              color: "#fff5ee",
              cursor: connecting || apiKey.trim().length === 0 ? "not-allowed" : "pointer",
              display: "inline-flex",
              fontSize: "13px",
              fontWeight: 600,
              height: "36px",
              opacity: connecting || apiKey.trim().length === 0 ? 0.6 : 1,
              padding: "0 18px",
            }}
          >
            {connecting ? "Connecting…" : "Connect"}
          </button>
          <a
            href={dashboardUrl}
            style={{
              alignItems: "center",
              background: "transparent",
              border: "1px solid transparent",
              borderRadius: "8px",
              color: "var(--fg-dim)",
              display: "inline-flex",
              fontSize: "13px",
              fontWeight: 500,
              height: "36px",
              padding: "0 14px",
              textDecoration: "none",
            }}
          >
            Open dashboard
          </a>
        </div>

        <div style={{ background: "var(--border)", height: "1px", margin: "28px 0 0" }} />
        <div style={{ color: "var(--fg-dimmer)", fontSize: "12px", lineHeight: "19px", marginTop: "16px" }}>
          No key? An operator can mint one with{" "}
          <span style={{ color: "var(--fg-dim)", fontFamily: "var(--font-mono)", fontSize: "11.5px" }}>
            dejaq-admin key generate
          </span>
        </div>
      </form>
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ color: "var(--fg-dimmer)", fontSize: "10.5px", fontWeight: 600, letterSpacing: "0.10em", textTransform: "uppercase" }}>
      {children}
    </div>
  );
}

function ErrorIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <circle cx="8" cy="8" r="6.2" />
      <path d="M8 4.8v3.7M8 11h.01" />
    </svg>
  );
}
