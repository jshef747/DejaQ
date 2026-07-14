"use client";

import { useEffect, useRef, useState } from "react";
import { checkServerHealth, fetchDepartments, isApiError, type Department } from "./chat-api";
import type { ChatSettings, ModelProfile, RoutingMode } from "./chat-store";

interface Props {
  open: boolean;
  initialSettings: ChatSettings;
  onSave: (settings: ChatSettings) => void;
  onClose: () => void;
}

type HealthStatus = "idle" | "checking" | "ok" | "error";
type DeptLoadStatus = "idle" | "loading" | "loaded" | "error";

export default function SettingsModal({ open, initialSettings, onSave, onClose }: Props) {
  const [serverBaseUrl, setServerBaseUrl] = useState(initialSettings.serverBaseUrl);
  const [deptSlug, setDeptSlug] = useState(initialSettings.deptSlug);
  const [modelProfile, setModelProfile] = useState<ModelProfile>(initialSettings.modelProfile);
  const [routingMode, setRoutingMode] = useState<RoutingMode>(initialSettings.routingMode);
  const [health, setHealth] = useState<HealthStatus>("idle");
  const [healthText, setHealthText] = useState("");
  const [departments, setDepartments] = useState<Department[]>([]);
  const [deptStatus, setDeptStatus] = useState<DeptLoadStatus>("idle");
  const firstInputRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    if (!open) return;
    setServerBaseUrl(initialSettings.serverBaseUrl);
    setDeptSlug(initialSettings.deptSlug);
    setModelProfile(initialSettings.modelProfile);
    setRoutingMode(initialSettings.routingMode);
    setHealth("idle");
    setHealthText("");
    setDepartments([]);
    setDeptStatus("loading");
    setTimeout(() => firstInputRef.current?.focus(), 50);

    let cancelled = false;
    fetchDepartments(initialSettings.serverBaseUrl).then((result) => {
      if (cancelled) return;
      if (isApiError(result)) {
        setDepartments([]);
        setDeptStatus("error");
        setHealth("error");
        setHealthText(result.message);
        return;
      }

      setDepartments(result);
      setDeptStatus("loaded");
      setDeptSlug((prev) => (result.some((d) => d.slug === prev) ? prev : result[0]?.slug ?? ""));
    });

    return () => {
      cancelled = true;
    };
  }, [
    open,
    initialSettings.serverBaseUrl,
    initialSettings.deptSlug,
    initialSettings.modelProfile,
    initialSettings.routingMode,
  ]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function handleTest() {
    setHealth("checking");
    setHealthText("");
    const target = serverBaseUrl.trim();
    const result = await checkServerHealth(target);
    if (result.reachable) {
      setHealth("ok");
      setHealthText(`Connected. Celery: ${result.celery}`);
      // Pull departments from the entered server so the dropdown matches it.
      setDeptStatus("loading");
      const depts = await fetchDepartments(target);
      if (isApiError(depts)) {
        setDepartments([]);
        setDeptStatus("error");
      } else {
        setDepartments(depts);
        setDeptStatus("loaded");
        setDeptSlug((prev) => (depts.some((d) => d.slug === prev) ? prev : depts[0]?.slug ?? ""));
      }
    } else {
      setHealth("error");
      setHealthText(result.message ?? "Cannot reach the DejaQ server.");
    }
  }

  function handleSave() {
    onSave({
      serverBaseUrl: serverBaseUrl.trim(),
      deptSlug: deptSlug.trim(),
      modelProfile,
      routingMode,
    });
    onClose();
  }

  const canSave = deptSlug.trim().length > 0;
  const deptDisabled = deptStatus === "loading" || departments.length === 0;

  if (!open) return null;

  return (
    <div
      onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{
        alignItems: "center",
        backdropFilter: "blur(2px)",
        background: "rgba(0,0,0,0.6)",
        bottom: 0,
        display: "flex",
        justifyContent: "center",
        left: 0,
        position: "fixed",
        right: 0,
        top: 0,
        zIndex: 50,
      }}
    >
      <div
        style={{
          background: "var(--bg-2)",
          border: "1px solid var(--border-2)",
          borderRadius: "10px",
          boxShadow: "0 20px 60px rgba(0,0,0,0.6)",
          display: "flex",
          flexDirection: "column",
          gap: 0,
          maxWidth: "460px",
          width: "calc(100vw - 40px)",
        }}
      >
        <div
          style={{
            alignItems: "center",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            padding: "16px 20px",
          }}
        >
          <div>
            <h2 style={{ fontSize: "14px", fontWeight: 600, margin: 0 }}>Chat Settings</h2>
            <p style={{ color: "var(--fg-dim)", fontSize: "12px", margin: "2px 0 0" }}>
              Credentials are configured server-side in chat/.env.local.
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "transparent",
              border: "none",
              borderRadius: "4px",
              color: "var(--fg-dimmer)",
              cursor: "pointer",
              fontSize: "16px",
              marginLeft: "auto",
              padding: "2px 6px",
            }}
            aria-label="Close settings"
          >
            x
          </button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "16px", padding: "20px" }}>
          <Field
            label="DejaQ server"
            hint="Leave blank to use this machine (http://127.0.0.1:8000). Set to http://<other-host>:8000 to use a server running on another computer on the network."
          >
            <input
              type="text"
              value={serverBaseUrl}
              onChange={(e) => setServerBaseUrl(e.target.value)}
              placeholder="http://127.0.0.1:8000"
              spellCheck={false}
              autoComplete="off"
              style={inputStyle}
            />
          </Field>

          <Field
            label={
              <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                Department
                <span style={{ color: "var(--red)", fontSize: "11px" }}>required</span>
                {deptStatus === "loading" && (
                  <span style={{ color: "var(--fg-dimmer)", fontSize: "11px" }}>Loading...</span>
                )}
                {deptStatus === "error" && (
                  <span style={{ color: "var(--red)", fontSize: "11px" }}>Could not load</span>
                )}
              </span>
            }
            hint="Select the department whose cache namespace you want to use"
          >
            <select
              ref={firstInputRef}
              value={deptSlug}
              onChange={(e) => setDeptSlug(e.target.value)}
              disabled={deptDisabled}
              style={{
                ...inputStyle,
                cursor: deptDisabled ? "not-allowed" : "pointer",
                opacity: deptDisabled ? 0.55 : 1,
              }}
            >
              {departments.length === 0 ? (
                <option value={deptSlug}>{deptSlug || "--"}</option>
              ) : (
                departments.map((d) => (
                  <option key={d.id} value={d.slug}>
                    {d.label} ({d.slug})
                  </option>
                ))
              )}
            </select>
          </Field>

          <div
            style={{
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "12px",
            }}
          >
            <div style={{ marginBottom: "12px" }}>
              <div style={{ color: "var(--fg)", fontSize: "12px", fontWeight: 600 }}>
                Developer overrides
              </div>
              <div style={{ color: "var(--fg-dimmer)", fontSize: "11px", lineHeight: 1.45, marginTop: "3px" }}>
                Browser controls for CPU-only testing and routing diagnostics.
              </div>
            </div>
            <div style={{ display: "grid", gap: "12px", gridTemplateColumns: "1fr" }}>
              <Field
                label="Local model profile"
                hint="Weak CPU uses Qwen 0.5B for local roles"
              >
                <select
                  value={modelProfile}
                  onChange={(e) => setModelProfile(e.target.value as ModelProfile)}
                  style={{ ...inputStyle, cursor: "pointer" }}
                >
                  <option value="default">Default</option>
                  <option value="weak_cpu">Weak CPU Test</option>
                </select>
              </Field>
              <Field
                label="Routing mode"
                hint="Forced modes skip the classifier"
              >
                <select
                  value={routingMode}
                  onChange={(e) => setRoutingMode(e.target.value as RoutingMode)}
                  style={{ ...inputStyle, cursor: "pointer" }}
                >
                  <option value="auto">Auto</option>
                  <option value="easy_local">Force Easy/Local</option>
                  <option value="hard_external">Force Hard/External</option>
                </select>
              </Field>
            </div>
          </div>

          <div
            style={{
              alignItems: "center",
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              display: "flex",
              gap: "10px",
              padding: "10px 14px",
            }}
          >
            <div style={{ flex: 1 }}>
              {health === "idle" && (
                <span style={{ color: "var(--fg-dimmer)", fontSize: "12px" }}>
                  Test the DejaQ server above and load its departments.
                </span>
              )}
              {health === "checking" && (
                <span style={{ color: "var(--fg-dim)", fontSize: "12px" }}>Checking...</span>
              )}
              {health === "ok" && (
                <span style={{ color: "var(--green)", fontSize: "12px" }}>{healthText}</span>
              )}
              {health === "error" && (
                <span style={{ color: "var(--red)", fontSize: "12px" }}>{healthText}</span>
              )}
            </div>
            <button
              onClick={handleTest}
              disabled={health === "checking"}
              style={btn("secondary", health === "checking")}
            >
              {health === "checking" ? "Testing..." : "Test connection"}
            </button>
          </div>
        </div>

        <div
          style={{
            borderTop: "1px solid var(--border)",
            display: "flex",
            gap: "8px",
            justifyContent: "flex-end",
            padding: "14px 20px",
          }}
        >
          <button onClick={onClose} style={btn("secondary")}>
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!canSave}
            title={!canSave ? "Department is required" : undefined}
            style={btn("primary", !canSave)}
          >
            Save settings
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: React.ReactNode;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
      <span style={{ color: "var(--fg)", fontSize: "12px", fontWeight: 500 }}>{label}</span>
      {children}
      <span style={{ color: "var(--fg-dimmer)", fontSize: "11px" }}>{hint}</span>
    </label>
  );
}

function btn(kind: "primary" | "secondary", disabled = false) {
  const base = {
    borderRadius: "5px",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: "12px",
    fontWeight: 500,
    opacity: disabled ? 0.55 : 1,
    padding: "7px 14px",
    whiteSpace: "nowrap" as const,
  };
  if (kind === "primary")
    return { ...base, background: "var(--accent)", border: "1px solid var(--accent)", color: "#1a0d00" };
  return { ...base, background: "var(--bg-3)", border: "1px solid var(--border-2)", color: "var(--fg-dim)" };
}

const inputStyle: React.CSSProperties = {
  background: "var(--bg)",
  border: "1px solid var(--border-2)",
  borderRadius: "5px",
  color: "var(--fg)",
  fontFamily: "var(--font-sans)",
  fontSize: "13px",
  outline: "none",
  padding: "8px 10px",
  width: "100%",
};
