"use client";

import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
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
  const [apiKey, setApiKey] = useState(initialSettings.apiKey);
  const [showApiKey, setShowApiKey] = useState(false);
  const [deptSlug, setDeptSlug] = useState(initialSettings.deptSlug);
  const [modelProfile, setModelProfile] = useState<ModelProfile>(initialSettings.modelProfile);
  const [routingMode, setRoutingMode] = useState<RoutingMode>(initialSettings.routingMode);
  const [health, setHealth] = useState<HealthStatus>("idle");
  const [healthText, setHealthText] = useState("");
  const [departments, setDepartments] = useState<Department[]>([]);
  const [deptStatus, setDeptStatus] = useState<DeptLoadStatus>("idle");
  // The server + key the department list currently in `departments` was
  // actually fetched against. Editing either field without re-fetching would
  // otherwise let Save send a department picked from a stale list - PR #78
  // made an existing department mandatory on every /v1/* call, so a mismatch
  // here is a "connected but every send 404s" trap, not just a stale label.
  const [deptsFetchedFor, setDeptsFetchedFor] = useState({
    server: initialSettings.serverBaseUrl,
    apiKey: initialSettings.apiKey,
  });
  // Set only when a fallback silently swapped the selection (the previously
  // selected department no longer exists in the freshly fetched list) -
  // shown once, next to the dropdown, instead of changing the value with no
  // acknowledgment at all.
  const [deptSwitchedNotice, setDeptSwitchedNotice] = useState<string | null>(null);
  const firstInputRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    if (!open) return;
    setServerBaseUrl(initialSettings.serverBaseUrl);
    setApiKey(initialSettings.apiKey);
    setShowApiKey(false);
    setDeptSlug(initialSettings.deptSlug);
    setModelProfile(initialSettings.modelProfile);
    setRoutingMode(initialSettings.routingMode);
    setHealth("idle");
    setHealthText("");
    setDepartments([]);
    setDeptStatus("loading");
    setDeptSwitchedNotice(null);
    setDeptsFetchedFor({ server: initialSettings.serverBaseUrl, apiKey: initialSettings.apiKey });
    setTimeout(() => firstInputRef.current?.focus(), 50);

    let cancelled = false;
    fetchDepartments({ server: initialSettings.serverBaseUrl, apiKey: initialSettings.apiKey }).then(
      (result) => {
        if (cancelled) return;
        if (isApiError(result)) {
          setDepartments([]);
          setDeptStatus("error");
          setHealth("error");
          setHealthText(result.status === 401 ? "API key rejected. Check the key and try again." : result.message);
          return;
        }

        setDepartments(result);
        setDeptStatus("loaded");
        const { slug, notice } = resolveDeptSelection(result, initialSettings.deptSlug);
        setDeptSlug(slug);
        setDeptSwitchedNotice(notice);
      },
    );

    return () => {
      cancelled = true;
    };
  }, [
    open,
    initialSettings.serverBaseUrl,
    initialSettings.apiKey,
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
    const key = apiKey.trim();
    const result = await checkServerHealth({ server: target, apiKey: key });
    if (!result.reachable) {
      setHealth("error");
      setHealthText(result.message ?? "Cannot reach the DejaQ server.");
      return;
    }

    // Pull departments from the entered server + key so the dropdown, and the
    // key's validity, both match what's currently typed.
    setDeptStatus("loading");
    const depts = await fetchDepartments({ server: target, apiKey: key });
    if (isApiError(depts)) {
      setDepartments([]);
      setDeptStatus("error");
      setHealth("error");
      setHealthText(depts.status === 401 ? "API key rejected. Check the key and try again." : depts.message);
      return;
    }

    setDepartments(depts);
    setDeptStatus("loaded");
    setDeptsFetchedFor({ server: target, apiKey: key });
    const { slug, notice } = resolveDeptSelection(depts, deptSlug);
    setDeptSlug(slug);
    setDeptSwitchedNotice(notice);
    setHealth("ok");
    setHealthText(`Connected. Celery: ${result.celery}`);
  }

  function handleSave() {
    onSave({
      serverBaseUrl: serverBaseUrl.trim(),
      apiKey: apiKey.trim(),
      deptSlug: deptSlug.trim(),
      modelProfile,
      routingMode,
    });
    onClose();
  }

  // The department list in `departments` was fetched against
  // deptsFetchedFor, not necessarily the server/key currently typed. Saving
  // anyway would send a department picked from a stale list against a
  // server/key that may not even have it - "Test again" is what refreshes
  // both together.
  const fieldsDrifted =
    serverBaseUrl.trim() !== deptsFetchedFor.server || apiKey.trim() !== deptsFetchedFor.apiKey;
  const canSave = deptSlug.trim().length > 0 && !fieldsDrifted;
  const deptDisabled = deptStatus === "loading" || departments.length === 0;

  if (!open) return null;

  return (
    <div
      onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{
        alignItems: "center",
        backdropFilter: "blur(2px)",
        background: "var(--scrim)",
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
          borderRadius: "16px",
          boxShadow: "var(--shadow)",
          display: "flex",
          flexDirection: "column",
          // Capped at 700px on a tall window, but never taller than the
          // viewport itself (minus a margin) — otherwise a short window just
          // pushes the header and footer off-screen instead of scrolling.
          maxHeight: "min(700px, calc(100vh - 40px))",
          width: "552px",
          maxWidth: "calc(100vw - 40px)",
        }}
      >
        <div
          style={{
            alignItems: "center",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            flexShrink: 0,
            height: "58px",
            padding: "0 14px 0 24px",
          }}
        >
          <h2 style={{ flex: 1, fontSize: "17px", fontWeight: 600, letterSpacing: "-0.018em", margin: 0 }}>
            Settings
          </h2>
          <button
            onClick={onClose}
            aria-label="Close settings"
            style={{
              alignItems: "center",
              background: "transparent",
              border: "none",
              borderRadius: "8px",
              color: "var(--fg-dimmer)",
              cursor: "pointer",
              display: "flex",
              height: "30px",
              justifyContent: "center",
              width: "30px",
            }}
          >
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              <path d="M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8" />
            </svg>
          </button>
        </div>

        {/* Height-capped body with its own scroll, so a short window never
            clips the Developer group off the bottom. */}
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "22px 24px 24px" }}>
          {/* ── Connection ── */}
          <SectionLabel>Connection</SectionLabel>
          <div style={{ display: "grid", gap: "12px 16px", gridTemplateColumns: "128px 1fr", marginTop: "12px" }}>
            <RowLabel>Server</RowLabel>
            <input
              type="text"
              value={serverBaseUrl}
              onChange={(e) => setServerBaseUrl(e.target.value)}
              placeholder="http://127.0.0.1:8000"
              spellCheck={false}
              autoComplete="off"
              style={inputStyle}
            />

            <RowLabel>API key</RowLabel>
            <div style={{ position: "relative" }}>
              <input
                type={showApiKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="paste your workspace API key"
                spellCheck={false}
                autoComplete="off"
                style={{ ...inputStyle, paddingRight: "38px" }}
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
                  padding: "4px",
                  position: "absolute",
                  right: "6px",
                  top: "50%",
                  transform: "translateY(-50%)",
                }}
              >
                {showApiKey ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>
          <div style={{ alignItems: "center", display: "flex", gap: "10px", marginLeft: "144px", marginTop: "12px" }}>
            <span
              aria-hidden
              style={{
                background: health === "ok" ? "var(--green)" : health === "error" ? "var(--red)" : "var(--fg-dimmer)",
                borderRadius: "999px",
                flexShrink: 0,
                height: "6px",
                width: "6px",
              }}
            />
            <span style={{ color: health === "error" ? "var(--red)" : health === "ok" ? "var(--green)" : "var(--fg-dim)", fontSize: "12.5px" }}>
              {health === "idle" && "Not tested yet"}
              {health === "checking" && "Checking…"}
              {(health === "ok" || health === "error") && healthText}
            </span>
            <div style={{ flex: 1 }} />
            <button onClick={handleTest} disabled={health === "checking"} style={btn("ghost", health === "checking")}>
              {health === "checking" ? "Testing…" : "Test again"}
            </button>
          </div>

          <Divider />

          {/* ── Workspace ── */}
          <SectionLabel>Workspace</SectionLabel>
          <div style={{ alignItems: "center", display: "grid", gap: "12px 16px", gridTemplateColumns: "128px 1fr", marginTop: "12px" }}>
            <span style={{ alignItems: "center", color: "var(--fg-dim)", display: "flex", fontSize: "13px", gap: "6px" }}>
              Department
              {deptStatus === "loading" && <span style={{ color: "var(--fg-dimmer)", fontSize: "11px" }}>Loading…</span>}
              {deptStatus === "error" && <span style={{ color: "var(--red)", fontSize: "11px" }}>Could not load</span>}
            </span>
            <select
              ref={firstInputRef}
              value={deptSlug}
              onChange={(e) => {
                setDeptSlug(e.target.value);
                setDeptSwitchedNotice(null);
              }}
              disabled={deptDisabled}
              style={{ ...inputStyle, cursor: deptDisabled ? "not-allowed" : "pointer", opacity: deptDisabled ? 0.55 : 1 }}
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
          </div>
          {deptSwitchedNotice && (
            <p style={{ color: "var(--amber)", fontSize: "11.5px", lineHeight: "17px", marginLeft: "144px", marginTop: "8px" }}>
              {deptSwitchedNotice}
            </p>
          )}
          {fieldsDrifted && (
            <p style={{ color: "var(--amber)", fontSize: "11.5px", lineHeight: "17px", marginLeft: "144px", marginTop: "8px" }}>
              Server or API key changed since the department list was loaded - click &ldquo;Test again&rdquo; before saving.
            </p>
          )}
          <p style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", lineHeight: "17px", marginLeft: "144px", marginTop: "8px" }}>
            Each department has its own cache. Answers are never shared across them.
          </p>

          <Divider />

          {/* ── Developer ── */}
          <div style={{ alignItems: "baseline", display: "flex", gap: "9px" }}>
            <SectionLabel>Developer</SectionLabel>
            <span style={{ color: "var(--fg-dimmer)", fontSize: "11.5px" }}>affects this browser only</span>
          </div>
          <div style={{ display: "grid", gap: "14px 16px", gridTemplateColumns: "128px 1fr", marginTop: "12px" }}>
            <RowLabel>Routing</RowLabel>
            <SegmentedControl value={routingMode} onChange={setRoutingMode} />

            <RowLabel>Local profile</RowLabel>
            <select
              value={modelProfile}
              onChange={(e) => setModelProfile(e.target.value as ModelProfile)}
              style={{ ...inputStyle, cursor: "pointer" }}
            >
              <option value="default">Default</option>
              <option value="weak_cpu">Weak CPU Test</option>
            </select>
          </div>
          <p style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", lineHeight: "17px", marginLeft: "144px", marginTop: "8px" }}>
            Forced routing skips the difficulty classifier. Weak CPU drops local roles to Qwen 0.5B.
          </p>
        </div>

        <div style={{ alignItems: "center", borderTop: "1px solid var(--border)", display: "flex", flexShrink: 0, gap: "9px", padding: "14px 24px" }}>
          <span style={{ color: "var(--fg-dimmer)", flex: 1, fontSize: "11.5px" }}>Stored in this browser</span>
          <button onClick={onClose} style={btn("ghost")}>
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!canSave}
            title={
              fieldsDrifted
                ? "Server or API key changed - click Test again first"
                : !canSave
                  ? "Department is required"
                  : undefined
            }
            style={btn("primary", !canSave)}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

// Picks which department stays selected once a fresh list lands: keep the
// previous slug if it still exists, otherwise fall back to the first entry -
// and say so, since a department that vanished server-side (deleted mid-
// session) would otherwise silently reassign the active cache namespace with
// no on-screen trace.
function resolveDeptSelection(
  depts: Department[],
  prevSlug: string,
): { slug: string; notice: string | null } {
  if (depts.some((d) => d.slug === prevSlug)) return { slug: prevSlug, notice: null };
  const fallback = depts[0];
  if (!prevSlug || !fallback) return { slug: fallback?.slug ?? "", notice: null };
  return {
    slug: fallback.slug,
    notice: `"${prevSlug}" no longer exists - switched to ${fallback.label} (${fallback.slug}).`,
  };
}

// ─── Routing mode: a segmented control, not a <select> — it's a diagnostic
// three-way toggle, not an open-ended choice. ─────────────────────────────

const ROUTING_OPTIONS: { value: RoutingMode; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "easy_local", label: "Force local" },
  { value: "hard_external", label: "Force cloud" },
];

function SegmentedControl({ value, onChange }: { value: RoutingMode; onChange: (v: RoutingMode) => void }) {
  return (
    <div
      role="radiogroup"
      aria-label="Routing mode"
      style={{
        background: "var(--bg)",
        border: "1px solid var(--border-2)",
        borderRadius: "9px",
        display: "flex",
        gap: "3px",
        height: "32px",
        padding: "3px",
      }}
    >
      {ROUTING_OPTIONS.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.value)}
            style={{
              alignItems: "center",
              background: active ? "var(--bg-3)" : "transparent",
              border: active ? "1px solid var(--border-2)" : "1px solid transparent",
              borderRadius: "6px",
              color: active ? "var(--fg)" : "var(--fg-dimmer)",
              cursor: "pointer",
              display: "flex",
              flex: 1,
              fontSize: "12.5px",
              fontWeight: active ? 600 : 400,
              justifyContent: "center",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ color: "var(--fg-dimmer)", fontSize: "10.5px", fontWeight: 600, letterSpacing: "0.10em", textTransform: "uppercase" }}>
      {children}
    </div>
  );
}

function RowLabel({ children }: { children: React.ReactNode }) {
  return <span style={{ color: "var(--fg-dim)", fontSize: "13px" }}>{children}</span>;
}

function Divider() {
  return <div style={{ background: "var(--border)", height: "1px", margin: "22px 0" }} />;
}

function btn(kind: "primary" | "ghost", disabled = false): React.CSSProperties {
  const base: React.CSSProperties = {
    borderRadius: "8px",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: "12.5px",
    fontWeight: 500,
    height: "32px",
    opacity: disabled ? 0.55 : 1,
    padding: "0 14px",
    whiteSpace: "nowrap",
  };
  if (kind === "primary") {
    return { ...base, background: "var(--fg)", border: "1px solid var(--fg)", color: "var(--bg)", fontWeight: 600 };
  }
  return { ...base, background: "transparent", border: "1px solid transparent", color: "var(--fg-dim)" };
}

const inputStyle: React.CSSProperties = {
  background: "var(--bg)",
  border: "1px solid var(--border-2)",
  borderRadius: "8px",
  color: "var(--fg)",
  fontFamily: "var(--font-sans)",
  fontSize: "13px",
  height: "34px",
  outline: "none",
  padding: "0 11px",
  width: "100%",
};
