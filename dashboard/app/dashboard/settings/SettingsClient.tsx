"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import ConfirmDialog from "@/components/ConfirmDialog";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Field from "@/components/ui/Field";
import SectionHeader from "@/components/ui/SectionHeader";
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

  const [testBusy, setTestBusy] = useState(false);
  const [testResult, setTestResult] = useState<TestResult>(null);

  const configKey = JSON.stringify(initialConfig);
  const credsKey = JSON.stringify(initialCredentials);

  useEffect(() => {
    const nextProvider = providerForExternalModel(initialConfig.external_model);
    setProvider(nextProvider);
    setExternalModel(initialConfig.external_model ?? DEFAULT_EXTERNAL_MODEL[nextProvider]);
    setThreshold(initialConfig.routing_threshold ?? 0.75);
    setCredentials(initialCredentials);
    setApiKey("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configKey, credsKey]);

  const currentCredential = credentials.find((item) => item.provider === provider);
  const models = useMemo(() => {
    const catalog = EXTERNAL_MODELS[provider];
    if (catalog.some((model) => model.value === externalModel)) return catalog;
    return [{ value: externalModel, label: `${externalModel} (custom)` }, ...catalog];
  }, [externalModel, provider]);

  const hasUnsavedKey = apiKey.trim().length > 0;
  const canTest = !!currentCredential && !hasUnsavedKey && !testBusy;
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
    setTestBusy(true);
    setTestResult(null);
    const res = await testProvider(orgSlug, externalModel);
    setTestBusy(false);
    if (!res.ok) {
      setTestResult({ kind: "error", status: res.status, text: testErrorText(res.status, res.error, provider) });
      return;
    }
    setTestResult({ kind: "success", data: res.data });
  }

  return (
    <div className="ds-page">
      <SectionHeader
        title="Settings"
        subtitle={`Configure cache routing and provider credentials for ${orgSlug}.`}
      />

      {loadError && (
        <div className="ds-pill ds-pill-err" style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
          {loadError}
        </div>
      )}

      {/* LLM Configuration */}
      <section className="ds-settings-section" style={{ marginBottom: 28 }}>
        <div className="ds-settings-header">
          <h2 className="ds-settings-title">LLM Configuration</h2>
          <p className="ds-settings-sub">Choose where hard queries go, and keep provider credentials scoped to this organization.</p>
        </div>
        <div className="ds-card" style={{ overflow: "hidden" }}>
          <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 0 }}>
            <Field label="Local model (easy queries)" hint="Only model available — more coming soon">
              <select disabled value={LOCAL_MODEL} className="ds-input" style={{ opacity: 0.62, cursor: "not-allowed" }}>
                <option value={LOCAL_MODEL}>{LOCAL_MODEL}</option>
              </select>
            </Field>

            <div style={{ display: "grid", gap: 12, gridTemplateColumns: "220px 1fr" }}>
              <Field label="External provider" hint="Provider is inferred from the selected model">
                <select
                  value={provider}
                  onChange={(e) => onProviderChange(e.target.value as Provider)}
                  className="ds-input"
                  style={{ cursor: "pointer" }}
                >
                  {(["google", "openai", "anthropic"] as Provider[]).map((item) => (
                    <option key={item} value={item}>{PROVIDER_LABEL[item]}</option>
                  ))}
                </select>
              </Field>
              <Field label="External model (hard queries)" hint="Used on cache misses that exceed the threshold">
                <select
                  value={externalModel}
                  onChange={(e) => setExternalModel(e.target.value)}
                  className="ds-input"
                  style={{ cursor: "pointer" }}
                >
                  {models.map((model) => (
                    <option key={model.value} value={model.value}>{model.label}</option>
                  ))}
                </select>
              </Field>
            </div>

            <Field label={`${PROVIDER_LABEL[provider]} API key`} hint="Leave blank to keep the stored key unchanged">
              <div style={{ display: "flex", gap: 8 }}>
                <Input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={currentCredential?.key_preview ?? "Enter API key"}
                  reveal
                  style={{ flex: 1 }}
                />
                {currentCredential && (
                  <Button
                    variant="ghost-danger"
                    size="sm"
                    onClick={() => setConfirmRemove(true)}
                    disabled={saveBusy || removeBusy}
                  >
                    Remove key
                  </Button>
                )}
              </div>
            </Field>

            <Field label="Difficulty threshold" hint="Lower = more provider calls, higher = more local answers">
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={threshold}
                  onChange={(e) => setThreshold(parseFloat(e.target.value))}
                  className="ds-slider"
                  style={{ flex: 1 }}
                />
                <div style={{ background: "var(--accent-bg)", border: "1px solid var(--accent-border)", borderRadius: 5, color: "var(--accent)", fontFamily: "var(--font-mono)", fontSize: 12, minWidth: 52, padding: "5px 8px", textAlign: "center" }}>
                  {threshold.toFixed(2)}
                </div>
              </div>
            </Field>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end", padding: "12px 20px", borderTop: "1px solid var(--border)" }}>
            <StatusText status={saveStatus} />
            <Button onClick={handleReset} disabled={saveBusy}>Reset to defaults</Button>
            <Button variant="primary" onClick={handleSave} loading={saveBusy}>Save changes</Button>
          </div>
        </div>
      </section>

      {/* Provider Test */}
      <section className="ds-settings-section" style={{ marginBottom: 28 }}>
        <div className="ds-settings-header">
          <h2 className="ds-settings-title">Provider Test</h2>
          <p className="ds-settings-sub">Verify that the saved organization key can reach the selected external model.</p>
        </div>
        <div className="ds-card">
          <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, justifyContent: "space-between" }}>
              <div style={{ color: hasUnsavedKey ? "var(--amber)" : "var(--fg-dimmer)", fontSize: 12 }}>
                {testHint}
              </div>
              <Button variant="primary" onClick={handleTest} disabled={!canTest} loading={testBusy}>
                Run test
              </Button>
            </div>
            {testResult && <ProviderTestResult result={testResult} />}
          </div>
        </div>
      </section>

      {/* Danger Zone */}
      <section className="ds-settings-section" style={{ marginBottom: 28 }}>
        <div className="ds-settings-header">
          <h2 className="ds-settings-title" style={{ color: "var(--red)" }}>Danger Zone</h2>
          <p className="ds-settings-sub">Irreversible actions. Proceed with caution.</p>
        </div>
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--red-border)", borderRadius: 6, overflow: "hidden" }}>
          <div style={{ padding: "16px 20px", display: "flex", alignItems: "center", gap: 18, justifyContent: "space-between" }}>
            <div>
              <h4 style={{ color: "var(--fg)", fontSize: 13, margin: "0 0 4px" }}>Delete organization</h4>
              <p style={{ color: "var(--fg-dim)", fontSize: 12, lineHeight: 1.55, margin: 0 }}>
                Permanently remove {orgName}, including all departments, API keys, cache data, and credentials.
              </p>
            </div>
            <Button
              variant="danger"
              disabled
              title={`Org deletion is currently CLI-only. Run dejaq-admin org delete ${orgSlug} from a server shell.`}
            >
              Delete organization
            </Button>
          </div>
        </div>
      </section>

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

function StatusText({ status }: { status: Status }) {
  if (status.kind === "idle" || !status.text) return <div style={{ flex: 1 }} />;
  const color = status.kind === "success" ? "var(--green)" : status.kind === "error" ? "var(--red)" : "var(--fg-dim)";
  return (
    <div style={{ color, flex: 1, fontSize: 12 }}>
      {status.kind === "success" ? "OK: " : status.kind === "error" ? "Failed: " : ""}
      {status.text}
    </div>
  );
}

function ProviderTestResult({ result }: { result: TestResult }) {
  if (!result) return null;
  if (result.kind === "error") {
    return (
      <div style={{ background: "var(--red-bg)", border: "1px solid var(--red-border)", borderRadius: 6, color: "var(--red)", fontSize: 12, lineHeight: 1.55, padding: 12 }}>
        {result.text}
      </div>
    );
  }
  const tokens = result.data.prompt_tokens + result.data.completion_tokens;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ background: "var(--green-bg)", border: "1px solid var(--green-border)", borderRadius: 6, color: "var(--green)", fontSize: 12, lineHeight: 1.55, padding: 12 }}>
        Provider connection verified.
      </div>
      <div style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
        model / {result.data.model_used} / {Math.round(result.data.latency_ms)}ms / {tokens} tokens
      </div>
    </div>
  );
}

function testErrorText(status: number | undefined, error: string, provider: Provider) {
  if (status === 401) return `API key was rejected by ${PROVIDER_LABEL[provider]}.`;
  if (status === 402) return `No ${PROVIDER_LABEL[provider]} API key configured for this organization.`;
  if (status === 429) return "Provider test recently succeeded. Please wait before running it again.";
  if (status === 422) return error;
  return error || "Provider test failed.";
}

function formatTime(date: Date) {
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}
