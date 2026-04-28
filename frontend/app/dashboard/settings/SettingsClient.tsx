"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ConfirmDialog from "@/components/ConfirmDialog";
import { deleteCredential, upsertCredential } from "@/app/actions/credentials";
import { updateLlmConfig } from "@/app/actions/llm-config";
import { testProvider } from "@/app/actions/test-provider";
import {
  DEFAULT_EXTERNAL_MODEL,
  EXTERNAL_MODELS,
  modelBelongsToProvider,
  providerForExternalModel,
} from "@/lib/external-models";
import type {
  CredentialItem,
  LlmConfigResponse,
  LlmConfigUpdate,
  Provider,
  TestProviderResponse,
} from "@/lib/types";

const LOCAL_MODEL = "gemma-4-e4b";
const PROVIDER_LABEL: Record<Provider, string> = {
  google: "Google",
  openai: "OpenAI",
  anthropic: "Anthropic",
};

type Status = { kind: "idle" | "success" | "error" | "info"; text: string };
type TestResult =
  | { kind: "success"; data: TestProviderResponse }
  | { kind: "error"; text: string; status?: number }
  | null;

interface Props {
  orgSlug: string;
  orgName: string;
  initialConfig: LlmConfigResponse;
  initialCredentials: CredentialItem[];
  loadError: string | null;
}

export default function SettingsClient({
  orgSlug,
  orgName,
  initialConfig,
  initialCredentials,
  loadError,
}: Props) {
  const router = useRouter();
  const initialProvider = providerForExternalModel(initialConfig.external_model);

  const [provider, setProvider] = useState<Provider>(initialProvider);
  const [externalModel, setExternalModel] = useState(
    initialConfig.external_model ?? DEFAULT_EXTERNAL_MODEL[initialProvider],
  );
  const [threshold, setThreshold] = useState(initialConfig.routing_threshold ?? 0.75);
  const [apiKey, setApiKey] = useState("");
  const [credentials, setCredentials] = useState(initialCredentials);

  const [saveBusy, setSaveBusy] = useState(false);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [saveStatus, setSaveStatus] = useState<Status>({ kind: "idle", text: "" });

  const [prompt, setPrompt] = useState("");
  const [testBusy, setTestBusy] = useState(false);
  const [testResult, setTestResult] = useState<TestResult>(null);

  useEffect(() => {
    const nextProvider = providerForExternalModel(initialConfig.external_model);
    setProvider(nextProvider);
    setExternalModel(initialConfig.external_model ?? DEFAULT_EXTERNAL_MODEL[nextProvider]);
    setThreshold(initialConfig.routing_threshold ?? 0.75);
    setCredentials(initialCredentials);
    setApiKey("");
  }, [initialConfig, initialCredentials]);

  const currentCredential = credentials.find((item) => item.provider === provider);
  const models = useMemo(() => {
    const catalog = EXTERNAL_MODELS[provider];
    if (catalog.some((model) => model.value === externalModel)) return catalog;
    return [{ value: externalModel, label: `${externalModel} (custom)` }, ...catalog];
  }, [externalModel, provider]);

  const hasUnsavedKey = apiKey.trim().length > 0;
  const canTest = prompt.trim().length > 0 && !!currentCredential && !hasUnsavedKey && !testBusy;
  const testHint = hasUnsavedKey
    ? "Save the API key first to enable Test."
    : currentCredential
      ? `Testing with the stored ${PROVIDER_LABEL[provider]} key.`
      : `No ${PROVIDER_LABEL[provider]} API key configured for this organization.`;

  function onProviderChange(next: Provider) {
    setProvider(next);
    setExternalModel(
      modelBelongsToProvider(externalModel, next) ? externalModel : DEFAULT_EXTERNAL_MODEL[next],
    );
    setApiKey("");
    setTestResult(null);
  }

  async function handleSave() {
    const trimmedKey = apiKey.trim();
    const patch: LlmConfigUpdate = {};
    if (externalModel !== initialConfig.external_model) patch.external_model = externalModel;
    if (threshold !== initialConfig.routing_threshold) patch.routing_threshold = threshold;

    if (!trimmedKey && Object.keys(patch).length === 0) {
      setSaveStatus({ kind: "info", text: "No changes to save." });
      return;
    }

    setSaveBusy(true);
    setSaveStatus({ kind: "idle", text: "" });

    if (trimmedKey) {
      const credentialRes = await upsertCredential(orgSlug, provider, trimmedKey);
      if (!credentialRes.ok) {
        setSaveBusy(false);
        setSaveStatus({ kind: "error", text: credentialRes.error });
        return;
      }
      setCredentials((items) => [
        credentialRes.data,
        ...items.filter((item) => item.provider !== credentialRes.data.provider),
      ]);
    }

    if (Object.keys(patch).length > 0) {
      const configRes = await updateLlmConfig(orgSlug, patch);
      if (!configRes.ok) {
        setSaveBusy(false);
        setSaveStatus({ kind: "error", text: configRes.error });
        return;
      }
      setThreshold(configRes.data.routing_threshold ?? threshold);
      setExternalModel(configRes.data.external_model ?? externalModel);
    }

    setApiKey("");
    setSaveBusy(false);
    setSaveStatus({ kind: "success", text: `Saved ${formatTime(new Date())}` });
    router.refresh();
  }

  async function handleReset() {
    setSaveBusy(true);
    setSaveStatus({ kind: "idle", text: "" });
    const res = await updateLlmConfig(orgSlug, {
      external_model: null,
      local_model: null,
      routing_threshold: null,
    });
    setSaveBusy(false);
    if (!res.ok) {
      setSaveStatus({ kind: "error", text: res.error });
      return;
    }
    const nextProvider = providerForExternalModel(res.data.external_model);
    setProvider(nextProvider);
    setExternalModel(res.data.external_model ?? DEFAULT_EXTERNAL_MODEL[nextProvider]);
    setThreshold(res.data.routing_threshold ?? 0.75);
    setApiKey("");
    setSaveStatus({ kind: "success", text: `Defaults restored ${formatTime(new Date())}` });
    router.refresh();
  }

  async function handleRemoveCredential() {
    setRemoveBusy(true);
    setSaveStatus({ kind: "idle", text: "" });
    const res = await deleteCredential(orgSlug, provider);
    setRemoveBusy(false);
    if (!res.ok) {
      setSaveStatus({ kind: "error", text: res.error });
      return;
    }
    setCredentials((items) => items.filter((item) => item.provider !== provider));
    setConfirmRemove(false);
    setSaveStatus({ kind: "success", text: `${PROVIDER_LABEL[provider]} key removed ${formatTime(new Date())}` });
    router.refresh();
  }

  async function handleTest() {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    setTestBusy(true);
    setTestResult(null);
    const res = await testProvider(orgSlug, trimmed, externalModel);
    setTestBusy(false);
    if (!res.ok) {
      setTestResult({ kind: "error", status: res.status, text: testErrorText(res.status, res.error, provider) });
      return;
    }
    setTestResult({ kind: "success", data: res.data });
  }

  return (
    <div style={{ flex: 1, maxWidth: "900px", padding: "24px 28px" }}>
      <div style={{ marginBottom: "24px" }}>
        <h1 style={pageTitleStyle}>Settings</h1>
        <p style={pageSubtitleStyle}>
          Configure cache routing and provider credentials for{" "}
          <span style={monoStrongStyle}>{orgSlug}</span>.
        </p>
      </div>

      {loadError && <Notice kind="error" text={loadError} />}

      <Section
        title="LLM Configuration"
        subtitle="Choose where hard queries go, and keep provider credentials scoped to this organization."
      >
        <div style={cardBodyStyle}>
          <Field label="Local model (easy queries)" hint="only model available - more coming soon">
            <select disabled value={LOCAL_MODEL} style={{ ...selectStyle, opacity: 0.62, cursor: "not-allowed" }}>
              <option value={LOCAL_MODEL}>{LOCAL_MODEL}</option>
            </select>
          </Field>

          <div style={{ display: "grid", gap: "12px", gridTemplateColumns: "220px 1fr" }}>
            <Field label="External provider" hint="provider is inferred from the selected model">
              <select
                value={provider}
                onChange={(e) => onProviderChange(e.target.value as Provider)}
                style={selectStyle}
              >
                {(["google", "openai", "anthropic"] as Provider[]).map((item) => (
                  <option key={item} value={item}>
                    {PROVIDER_LABEL[item]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="External model (hard queries)" hint="used on cache misses that exceed the threshold">
              <select value={externalModel} onChange={(e) => setExternalModel(e.target.value)} style={selectStyle}>
                {models.map((model) => (
                  <option key={model.value} value={model.value}>
                    {model.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field
            label={`${PROVIDER_LABEL[provider]} API key`}
            hint="leave blank to keep the stored key unchanged"
          >
            <div style={{ display: "flex", gap: "8px" }}>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={currentCredential?.key_preview ?? "Enter API key"}
                style={{ ...inputStyle, flex: 1 }}
              />
              {currentCredential && (
                <button
                  type="button"
                  onClick={() => setConfirmRemove(true)}
                  disabled={saveBusy || removeBusy}
                  style={buttonStyle("dangerGhost", saveBusy || removeBusy)}
                >
                  Remove key
                </button>
              )}
            </div>
          </Field>

          <Field label="Difficulty threshold" hint="lower = more local answers, higher = more provider calls">
            <div style={{ alignItems: "center", display: "flex", gap: "12px" }}>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={threshold}
                onChange={(e) => setThreshold(parseFloat(e.target.value))}
                style={{ accentColor: "var(--accent)", flex: 1 }}
              />
              <div style={sliderValueStyle}>{threshold.toFixed(2)}</div>
            </div>
          </Field>
        </div>
        <div style={cardFooterStyle}>
          <StatusRow status={saveStatus} />
          <button type="button" onClick={handleReset} disabled={saveBusy} style={buttonStyle("secondary", saveBusy)}>
            Reset to defaults
          </button>
          <button type="button" onClick={handleSave} disabled={saveBusy} style={buttonStyle("primary", saveBusy)}>
            {saveBusy ? "Saving..." : "Save changes"}
          </button>
        </div>
      </Section>

      <Section
        title="Provider Test"
        subtitle="Send one prompt through the selected external model using the saved organization key."
      >
        <div style={cardBodyStyle}>
          <textarea
            rows={4}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Hello, are you there?"
            style={{ ...inputStyle, lineHeight: 1.5, resize: "vertical" }}
          />
          <div style={{ alignItems: "center", display: "flex", gap: "10px", justifyContent: "space-between" }}>
            <div style={{ color: hasUnsavedKey ? "var(--amber)" : "var(--fg-dimmer)", fontSize: "12px" }}>
              {testHint}
            </div>
            <button type="button" onClick={handleTest} disabled={!canTest} style={buttonStyle("primary", !canTest)}>
              {testBusy ? "Sending..." : "Send"}
            </button>
          </div>
          {testResult && <ProviderTestResult result={testResult} />}
        </div>
      </Section>

      <Section title="Danger Zone" subtitle="Irreversible actions. Proceed with caution." danger>
        <div style={{ ...cardBodyStyle, borderColor: "var(--red-border)" }}>
          <div style={{ alignItems: "center", display: "flex", gap: "18px", justifyContent: "space-between" }}>
            <div>
              <h4 style={{ color: "var(--fg)", fontSize: "13px", margin: "0 0 4px" }}>Delete organization</h4>
              <p style={{ color: "var(--fg-dim)", fontSize: "12px", lineHeight: 1.55, margin: 0 }}>
                Permanently remove {orgName}, including all departments, API keys, cache data, and credentials.
              </p>
            </div>
            <button
              type="button"
              disabled
              title={`Org deletion is currently CLI-only. Run dejaq-admin org delete ${orgSlug} from a server shell.`}
              style={buttonStyle("danger", true)}
            >
              Delete organization
            </button>
          </div>
        </div>
      </Section>

      <ConfirmDialog
        open={confirmRemove}
        title={`Remove ${PROVIDER_LABEL[provider]} key?`}
        message={`This will remove the stored ${PROVIDER_LABEL[provider]} API key for ${orgSlug}. Hard queries using ${PROVIDER_LABEL[provider]} will fail until a new key is saved.`}
        confirmLabel="Remove key"
        destructive
        busy={removeBusy}
        onCancel={() => setConfirmRemove(false)}
        onConfirm={handleRemoveCredential}
      />
    </div>
  );
}

function Section({
  title,
  subtitle,
  danger = false,
  children,
}: {
  title: string;
  subtitle: string;
  danger?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginBottom: "28px" }}>
      <div style={{ marginBottom: "10px" }}>
        <h2 style={{ color: danger ? "var(--red)" : "var(--fg)", fontSize: "14px", fontWeight: 600, letterSpacing: 0, margin: "0 0 3px" }}>
          {title}
        </h2>
        <p style={{ color: "var(--fg-dim)", fontSize: "12px", lineHeight: 1.5, margin: 0 }}>
          {subtitle}
        </p>
      </div>
      <div style={{ background: "var(--bg-2)", border: `1px solid ${danger ? "var(--red-border)" : "var(--border)"}`, borderRadius: "6px", overflow: "hidden" }}>
        {children}
      </div>
    </section>
  );
}

function Field({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: "6px", marginBottom: "16px" }}>
      <span style={{ color: "var(--fg)", fontSize: "12px", fontWeight: 500 }}>{label}</span>
      {children}
      <span style={{ color: "var(--fg-dimmer)", fontSize: "11px" }}>{hint}</span>
    </label>
  );
}

function Notice({ kind, text }: { kind: "error"; text: string }) {
  return (
    <div
      style={{
        background: kind === "error" ? "var(--red-bg)" : "var(--bg-2)",
        border: `1px solid ${kind === "error" ? "var(--red-border)" : "var(--border)"}`,
        borderRadius: "6px",
        color: kind === "error" ? "var(--red)" : "var(--fg-dim)",
        fontSize: "12px",
        marginBottom: "16px",
        padding: "10px 14px",
      }}
    >
      {text}
    </div>
  );
}

function StatusRow({ status }: { status: Status }) {
  if (status.kind === "idle" || !status.text) {
    return <div style={{ flex: 1 }} />;
  }
  const color = status.kind === "success" ? "var(--green)" : status.kind === "error" ? "var(--red)" : "var(--fg-dim)";
  return (
    <div style={{ color, flex: 1, fontSize: "12px" }}>
      {status.kind === "success" ? "OK: " : status.kind === "error" ? "Failed: " : ""}
      {status.text}
    </div>
  );
}

function ProviderTestResult({ result }: { result: TestResult }) {
  if (!result) return null;
  if (result.kind === "error") {
    return (
      <div
        style={{
          background: "var(--red-bg)",
          border: "1px solid var(--red-border)",
          borderRadius: "6px",
          color: "var(--red)",
          fontSize: "12px",
          lineHeight: 1.55,
          padding: "12px",
        }}
      >
        {result.text}
      </div>
    );
  }
  const tokens = result.data.prompt_tokens + result.data.completion_tokens;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <pre
        style={{
          background: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: "6px",
          color: "var(--fg)",
          fontFamily: "var(--font-mono)",
          fontSize: "12px",
          lineHeight: 1.55,
          margin: 0,
          overflow: "auto",
          padding: "12px",
          whiteSpace: "pre-wrap",
        }}
      >
        {result.data.text}
      </pre>
      <div style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: "11px" }}>
        model / {result.data.model_used} / {Math.round(result.data.latency_ms)}ms / {tokens} tokens
      </div>
    </div>
  );
}

function testErrorText(status: number | undefined, error: string, provider: Provider) {
  if (status === 401) return `API key was rejected by ${PROVIDER_LABEL[provider]}.`;
  if (status === 402) return `No ${PROVIDER_LABEL[provider]} API key configured for this organization.`;
  if (status === 422) return error;
  return error || "Provider test failed.";
}

function buttonStyle(kind: "primary" | "secondary" | "danger" | "dangerGhost", disabled = false) {
  const base = {
    borderRadius: "5px",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: "12px",
    fontWeight: 500,
    opacity: disabled ? 0.55 : 1,
    padding: "7px 12px",
    whiteSpace: "nowrap" as const,
  };
  if (kind === "primary") {
    return { ...base, background: "var(--accent)", border: "1px solid var(--accent)", color: "#1a0d00" };
  }
  if (kind === "danger") {
    return { ...base, background: "var(--red-bg)", border: "1px solid var(--red-border)", color: "var(--red)" };
  }
  if (kind === "dangerGhost") {
    return { ...base, background: "transparent", border: "1px solid var(--red-border)", color: "var(--red)" };
  }
  return { ...base, background: "var(--bg-3)", border: "1px solid var(--border-2)", color: "var(--fg-dim)" };
}

function formatTime(date: Date) {
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

const pageTitleStyle = {
  fontSize: "22px",
  fontWeight: 600,
  letterSpacing: 0,
  margin: "0 0 4px",
};

const pageSubtitleStyle = {
  color: "var(--fg-dim)",
  fontSize: "13px",
  margin: 0,
};

const monoStrongStyle = {
  color: "var(--fg)",
  fontFamily: "var(--font-mono)",
  fontSize: "12px",
};

const cardBodyStyle = {
  display: "flex",
  flexDirection: "column" as const,
  gap: "0",
  padding: "16px 20px",
};

const cardFooterStyle = {
  alignItems: "center",
  borderTop: "1px solid var(--border)",
  display: "flex",
  gap: "8px",
  justifyContent: "flex-end",
  padding: "12px 20px",
};

const inputStyle = {
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

const selectStyle = {
  ...inputStyle,
  cursor: "pointer",
};

const sliderValueStyle = {
  background: "var(--accent-bg)",
  border: "1px solid var(--accent-border)",
  borderRadius: "5px",
  color: "var(--accent)",
  fontFamily: "var(--font-mono)",
  fontSize: "12px",
  minWidth: "52px",
  padding: "5px 8px",
  textAlign: "center" as const,
};
