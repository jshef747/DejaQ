"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createWorkspace } from "@/app/actions/workspaces";
import { createDepartment } from "@/app/actions/departments";
import { generateKey } from "@/app/actions/keys";

type Step = "workspace" | "dept" | "key";

export default function OnboardingWizard() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("workspace");

  // Step 1 state
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspaceSlug, setWorkspaceSlug] = useState("");
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceLoading, setWorkspaceLoading] = useState(false);

  // Step 2 state
  const [deptName, setDeptName] = useState("general");
  const [deptError, setDeptError] = useState("");
  const [deptLoading, setDeptLoading] = useState(false);

  // Step 3 state
  const [apiToken, setApiToken] = useState("");
  const [keyError, setKeyError] = useState("");
  const [copied, setCopied] = useState(false);
  const [deptSlug, setDeptSlug] = useState("general");

  async function handleCreateWorkspace(e: React.FormEvent) {
    e.preventDefault();
    if (!workspaceName.trim()) return;
    setWorkspaceLoading(true);
    setWorkspaceError("");
    const result = await createWorkspace(workspaceName.trim());
    setWorkspaceLoading(false);
    if (!result.ok) {
      setWorkspaceError(result.error);
      return;
    }
    setWorkspaceSlug(result.workspace.slug);
    setStep("dept");
  }

  async function handleCreateDept(e: React.FormEvent) {
    e.preventDefault();
    if (!deptName.trim()) return;
    setDeptLoading(true);
    setDeptError("");
    const result = await createDepartment(workspaceSlug, deptName.trim());
    setDeptLoading(false);
    if (!result.ok) {
      setDeptError(result.error);
      return;
    }
    setDeptSlug(result.dept.slug);
    // Auto-generate the key
    const keyResult = await generateKey(workspaceSlug, false);
    if (!keyResult.ok) {
      setKeyError(keyResult.error);
    } else {
      setApiToken(keyResult.key.token);
    }
    setStep("key");
  }

  function handleCopy() {
    navigator.clipboard.writeText(apiToken).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const steps: { id: Step; label: string }[] = [
    { id: "workspace", label: "Workspace" },
    { id: "dept", label: "Department" },
    { id: "key", label: "API Key" },
  ];
  const stepIndex = steps.findIndex((s) => s.id === step);

  return (
    <div>
      {/* Step indicator */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 32 }}>
        {steps.map((s, i) => (
          <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 24,
                height: 24,
                borderRadius: "50%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 11,
                fontWeight: 600,
                background: i <= stepIndex ? "var(--accent)" : "var(--bg-3)",
                color: i <= stepIndex ? "#000" : "var(--fg-dimmer)",
                transition: "background 0.2s",
              }}
            >
              {i < stepIndex ? "✓" : i + 1}
            </div>
            <span
              style={{
                fontSize: 12,
                color: i === stepIndex ? "var(--fg)" : "var(--fg-dimmer)",
                fontWeight: i === stepIndex ? 500 : 400,
              }}
            >
              {s.label}
            </span>
            {i < steps.length - 1 && (
              <div
                style={{
                  width: 28,
                  height: 1,
                  background: i < stepIndex ? "var(--accent)" : "var(--border)",
                  transition: "background 0.2s",
                }}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step 1: Workspace */}
      {step === "workspace" && (
        <div className="ds-card">
          <div className="ds-card-header">
            <p className="ds-card-title">Create your first workspace</p>
            <p style={{ fontSize: 12, color: "var(--fg-dim)", marginTop: 4 }}>
              A workspace holds API keys, provider credentials, and departments.
              Name it after your company, team, or project.
            </p>
          </div>
          <div className="ds-card-body">
            <form onSubmit={handleCreateWorkspace} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <label style={{ fontSize: 12, color: "var(--fg-dim)", display: "block", marginBottom: 6 }}>
                  Workspace name
                </label>
                <input
                  className="ds-input"
                  type="text"
                  placeholder="e.g. Acme Inc"
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  autoFocus
                  required
                  disabled={workspaceLoading}
                />
                {workspaceError && (
                  <p style={{ fontSize: 12, color: "var(--red)", marginTop: 6 }}>{workspaceError}</p>
                )}
              </div>
              <button
                type="submit"
                className="ds-btn ds-btn-primary"
                disabled={workspaceLoading || !workspaceName.trim()}
              >
                {workspaceLoading ? "Creating…" : "Create Workspace →"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Step 2: Department */}
      {step === "dept" && (
        <div className="ds-card">
          <div className="ds-card-header">
            <p className="ds-card-title">Add a department</p>
            <p style={{ fontSize: 12, color: "var(--fg-dim)", marginTop: 4 }}>
              Departments segment your cache by team or product. Each has its own namespace.
              You can add more later.
            </p>
          </div>
          <div className="ds-card-body">
            <form onSubmit={handleCreateDept} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <label style={{ fontSize: 12, color: "var(--fg-dim)", display: "block", marginBottom: 6 }}>
                  Department name
                </label>
                <input
                  className="ds-input"
                  type="text"
                  placeholder="general"
                  value={deptName}
                  onChange={(e) => setDeptName(e.target.value)}
                  autoFocus
                  required
                  disabled={deptLoading}
                />
                {deptError && (
                  <p style={{ fontSize: 12, color: "var(--red)", marginTop: 6 }}>{deptError}</p>
                )}
              </div>
              <button
                type="submit"
                className="ds-btn ds-btn-primary"
                disabled={deptLoading || !deptName.trim()}
              >
                {deptLoading ? "Creating…" : "Create Department →"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Step 3: Key reveal */}
      {step === "key" && (
        <div className="ds-card">
          <div className="ds-card-header">
            <p className="ds-card-title">Your API key</p>
            <p style={{ fontSize: 12, color: "var(--fg-dim)", marginTop: 4 }}>
              This key is shown <strong>once</strong>. Copy it now and store it somewhere safe.
            </p>
          </div>
          <div className="ds-card-body" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {keyError && (
              <p style={{ fontSize: 12, color: "var(--red)" }}>{keyError}</p>
            )}
            {apiToken && (
              <>
                <div
                  style={{
                    background: "var(--bg-2)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    padding: "12px 14px",
                    fontFamily: "var(--font-mono)",
                    fontSize: 12,
                    color: "var(--accent)",
                    wordBreak: "break-all",
                    lineHeight: 1.6,
                  }}
                >
                  {apiToken}
                </div>
                <button
                  className={`ds-btn ${copied ? "ds-btn-secondary" : "ds-btn-primary"}`}
                  onClick={handleCopy}
                >
                  {copied ? "✓ Copied!" : "Copy to clipboard"}
                </button>
              </>
            )}

            {/* Usage hint */}
            <div
              style={{
                background: "var(--bg-2)",
                border: "1px solid var(--border)",
                borderRadius: 6,
                padding: "12px 14px",
                fontSize: 11,
                color: "var(--fg-dim)",
                lineHeight: 1.8,
              }}
            >
              <p style={{ margin: 0, marginBottom: 8, fontWeight: 500, color: "var(--fg)" }}>
                Use in your chat client or API calls:
              </p>
              <code style={{ fontFamily: "var(--font-mono)", display: "block", color: "var(--fg-dim)" }}>
                Authorization: Bearer {"<your-key>"}
              </code>
              <code style={{ fontFamily: "var(--font-mono)", display: "block", color: "var(--fg-dim)" }}>
                X-DejaQ-Department: {deptSlug}
              </code>
            </div>

            <button
              className="ds-btn ds-btn-secondary"
              onClick={() => router.push("/dashboard")}
            >
              Go to dashboard →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
