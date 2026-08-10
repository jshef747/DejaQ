"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Button from "@/components/ui/Button";
import Field from "@/components/ui/Field";
import SectionHeader from "@/components/ui/SectionHeader";
import { updateLlmConfig } from "@/app/actions/llm-config";
import { getAvailableModels } from "@/app/actions/available-models";
import type { AvailableModelsResponse, LlmConfigResponse, PipelineRole } from "@/lib/types";

interface Props {
  workspaceSlug: string;
  initialConfig: LlmConfigResponse;
  initialAvailableModels: AvailableModelsResponse;
  loadError: string | null;
}

interface StageMeta {
  key: PipelineRole;
  label: string;
  sub: string;
  calibrated?: boolean;
}

// Order matches the flow, top to bottom.
const STAGES: StageMeta[] = [
  { key: "enricher_model", label: "Context Enricher", sub: "makes a follow-up standalone" },
  { key: "normalizer_model", label: "Normalizer", sub: "builds the cache key" },
  { key: "validator_model", label: "Cache Validator", sub: "2 prompts: text & files" },
  { key: "adjuster_model", label: "Context Adjuster", sub: "rewrites to match phrasing", calibrated: true },
  { key: "local_model", label: "Local answer", sub: "easy questions" },
  { key: "generalizer_model", label: "Generalizer", sub: "strips tone before storing", calibrated: true },
];
const STAGE_BY_KEY = Object.fromEntries(STAGES.map((s) => [s.key, s])) as Record<PipelineRole, StageMeta>;

type SelectedStage = PipelineRole | "external_model" | null;

function onActivateKey(handler: () => void) {
  return (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handler();
    }
  };
}

export default function PipelineClient({ workspaceSlug, initialConfig, initialAvailableModels, loadError }: Props) {
  const router = useRouter();

  const [config, setConfig] = useState(initialConfig);
  const [selected, setSelected] = useState<SelectedStage>(null);
  const [draftValue, setDraftValue] = useState("");

  const [availableModels, setAvailableModels] = useState(initialAvailableModels);
  const [modelsRefreshing, setModelsRefreshing] = useState(false);

  const [saveBusy, setSaveBusy] = useState(false);
  const [resetAllBusy, setResetAllBusy] = useState(false);
  const [status, setStatus] = useState<{ kind: "idle" | "success" | "error"; text: string }>({
    kind: "idle",
    text: "",
  });

  const configKey = JSON.stringify(initialConfig);
  useEffect(() => {
    setConfig(initialConfig);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configKey]);

  useEffect(() => {
    if (!selected || selected === "external_model") return;
    setDraftValue(config[selected] ?? "");
    setStatus({ kind: "idle", text: "" });
  }, [selected, config]);

  async function handleRefreshModels() {
    setModelsRefreshing(true);
    const res = await getAvailableModels(true);
    setModelsRefreshing(false);
    setAvailableModels(res.ok ? res.data : { models: [], error: res.error });
  }

  async function handleSaveStage() {
    if (!selected || selected === "external_model") return;
    const role = selected;
    if (draftValue === (config[role] ?? "")) {
      setStatus({ kind: "idle", text: "No changes to save." });
      return;
    }
    setSaveBusy(true);
    setStatus({ kind: "idle", text: "" });
    const res = await updateLlmConfig(workspaceSlug, { [role]: draftValue });
    setSaveBusy(false);
    if (!res.ok) {
      setStatus({ kind: "error", text: res.error });
      return;
    }
    setConfig(res.data);
    setStatus({ kind: "success", text: "Saved." });
    router.refresh();
  }

  async function handleResetStage(role: PipelineRole) {
    setSaveBusy(true);
    setStatus({ kind: "idle", text: "" });
    const res = await updateLlmConfig(workspaceSlug, { [role]: null });
    setSaveBusy(false);
    if (!res.ok) {
      setStatus({ kind: "error", text: res.error });
      return;
    }
    setConfig(res.data);
    setStatus({ kind: "success", text: "Reset to default." });
    router.refresh();
  }

  async function handleResetAll() {
    setResetAllBusy(true);
    const res = await updateLlmConfig(workspaceSlug, {
      enricher_model: null,
      normalizer_model: null,
      validator_model: null,
      adjuster_model: null,
      local_model: null,
      generalizer_model: null,
    });
    setResetAllBusy(false);
    if (!res.ok) {
      setStatus({ kind: "error", text: res.error });
      return;
    }
    setConfig(res.data);
    setStatus({ kind: "success", text: "All stages reset to default." });
    router.refresh();
  }

  const overriddenCount = STAGES.filter((s) => s.key in config.overrides).length;
  const modelsUnknown = !!availableModels.error;

  return (
    <div className="ds-page">
      <SectionHeader
        title="Pipeline"
        subtitle="Choose the model for each stage of the request pipeline. Only models installed on this server are selectable."
      />

      {loadError && (
        <div className="ds-pill ds-pill-err" style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 5, fontSize: 12, display: "block" }}>
          {loadError}
        </div>
      )}

      {/* Toolbar */}
      <div
        style={{
          display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
          margin: "0 0 22px", padding: "10px 14px",
          background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: 8,
        }}
      >
        {modelsUnknown ? (
          <span style={{ fontSize: 12, color: "var(--red)" }}>{availableModels.error}</span>
        ) : (
          <span style={{ fontSize: 12, color: "var(--fg-dim)" }}>
            {availableModels.models.length} model{availableModels.models.length === 1 ? "" : "s"} installed
          </span>
        )}
        <span style={{ color: "var(--border-2)" }}>|</span>
        <Button size="sm" variant="ghost" onClick={handleRefreshModels} loading={modelsRefreshing}>
          Refresh list
        </Button>
        <div style={{ flex: 1 }} />
        <span className={`ds-pill ${overriddenCount > 0 ? "ds-pill-hit" : "ds-pill-neutral"}`}>
          {overriddenCount} stage{overriddenCount === 1 ? "" : "s"} overridden
        </span>
        <Button size="sm" onClick={handleResetAll} loading={resetAllBusy} disabled={overriddenCount === 0}>
          Reset all to defaults
        </Button>
      </div>

      <div className="ds-flow-split">
        {/* FLOW */}
        <div className="ds-flow">
          <div className="ds-flow-node io">
            <div className="ds-flow-name">User question</div>
          </div>
          <div className="ds-flow-conn" />

          <FlowNode
            stage={STAGES[0]}
            config={config}
            selected={selected === STAGES[0].key}
            onSelect={() => setSelected(STAGES[0].key)}
          />
          <div className="ds-flow-conn" />

          <FlowNode
            stage={STAGES[1]}
            config={config}
            selected={selected === STAGES[1].key}
            onSelect={() => setSelected(STAGES[1].key)}
          />
          <div className="ds-flow-conn" />

          <LockedNode name="Vector cache lookup" model="BGE" sub="similarity search, nothing to configure" />
          <div className="ds-flow-conn" />

          <div className="ds-flow-branch">
            <div>
              <span className="ds-flow-lbl hit">HIT</span>
              <FlowNode
                stage={STAGES[2]}
                config={config}
                selected={selected === STAGES[2].key}
                onSelect={() => setSelected(STAGES[2].key)}
                wide
              />
              <div className="ds-flow-conn a" />
              <FlowNode
                stage={STAGES[3]}
                config={config}
                selected={selected === STAGES[3].key}
                onSelect={() => setSelected(STAGES[3].key)}
                wide
              />
            </div>
            <div>
              <span className="ds-flow-lbl miss">MISS</span>
              <LockedNode name="Difficulty Classifier" model="DeBERTa" sub="easy or hard" wide />
              <div className="ds-flow-conn" />
              <FlowNode
                stage={STAGES[4]}
                config={config}
                selected={selected === STAGES[4].key}
                onSelect={() => setSelected(STAGES[4].key)}
                wide
              />
              <div className="ds-flow-conn" />
              <div
                className={`ds-flow-node${selected === "external_model" ? " sel" : ""}`}
                style={{ maxWidth: "none" }}
                onClick={() => setSelected("external_model")}
                role="button"
                tabIndex={0}
                aria-pressed={selected === "external_model"}
                onKeyDown={onActivateKey(() => setSelected("external_model"))}
              >
                <div className="ds-flow-row">
                  <span className="ds-flow-name">External answer</span>
                  <span className={`ds-pill ${"external_model" in config.overrides ? "ds-pill-hit" : "ds-pill-neutral"}`}>
                    {"external_model" in config.overrides ? "Overridden" : "Default"}
                  </span>
                </div>
                <div className="ds-flow-row">
                  <span className="ds-flow-model">{config.external_model}</span>
                  <span className="ds-flow-sub">hard questions</span>
                </div>
              </div>
            </div>
          </div>

          <div className="ds-flow-conn" />
          <div className="ds-flow-node io out">
            <div className="ds-flow-name" style={{ color: "var(--fg)" }}>Answer to the user</div>
          </div>

          <div className="ds-flow-storepath">
            <div className="ds-flow-storenote">on a miss, after answering — background</div>
            <FlowNode
              stage={STAGES[5]}
              config={config}
              selected={selected === STAGES[5].key}
              onSelect={() => setSelected(STAGES[5].key)}
              narrow
            />
          </div>
        </div>

        {/* EDITOR */}
        {selected === null ? (
          <div className="ds-flow-empty">Click a stage in the flow to view or change its model.</div>
        ) : selected === "external_model" ? (
          <ExternalEditor config={config} workspaceSlug={workspaceSlug} />
        ) : (
          <StageEditor
            stage={STAGE_BY_KEY[selected]}
            overridden={selected in config.overrides}
            draftValue={draftValue}
            onDraftChange={setDraftValue}
            availableModels={availableModels.models}
            modelsUnknown={modelsUnknown}
            busy={saveBusy}
            status={status}
            onSave={handleSaveStage}
            onReset={() => handleResetStage(selected)}
          />
        )}
      </div>
    </div>
  );
}

function FlowNode({
  stage,
  config,
  selected,
  onSelect,
  wide,
  narrow,
}: {
  stage: StageMeta;
  config: LlmConfigResponse;
  selected: boolean;
  onSelect: () => void;
  wide?: boolean;
  narrow?: boolean;
}) {
  const overridden = stage.key in config.overrides;
  const value = config[stage.key] ?? "";
  return (
    <div
      className={`ds-flow-node${selected ? " sel" : ""}`}
      style={wide ? { maxWidth: "none" } : narrow ? { maxWidth: 340 } : undefined}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onKeyDown={onActivateKey(onSelect)}
    >
      <div className="ds-flow-row">
        <span className="ds-flow-name">{stage.label}</span>
        {stage.calibrated ? (
          <span className="ds-pill ds-pill-err">Calibrated</span>
        ) : (
          <span className={`ds-pill ${overridden ? "ds-pill-hit" : "ds-pill-neutral"}`}>
            {overridden ? "Overridden" : "Default"}
          </span>
        )}
      </div>
      <div className="ds-flow-row">
        <span className="ds-flow-model">{value}</span>
        <span className="ds-flow-sub">{stage.sub}</span>
      </div>
    </div>
  );
}

function LockedNode({ name, model, sub, wide }: { name: string; model: string; sub: string; wide?: boolean }) {
  return (
    <div className="ds-flow-node locked" style={wide ? { maxWidth: "none" } : undefined}>
      <div className="ds-flow-row">
        <span className="ds-flow-name">{name}</span>
        <span className="ds-pill ds-pill-neutral">Not a model</span>
      </div>
      <div className="ds-flow-row">
        <span className="ds-flow-model">{model}</span>
        <span className="ds-flow-sub">{sub}</span>
      </div>
    </div>
  );
}

function StageEditor({
  stage,
  overridden,
  draftValue,
  onDraftChange,
  availableModels,
  modelsUnknown,
  busy,
  status,
  onSave,
  onReset,
}: {
  stage: StageMeta;
  overridden: boolean;
  draftValue: string;
  onDraftChange: (v: string) => void;
  availableModels: string[];
  modelsUnknown: boolean;
  busy: boolean;
  status: { kind: "idle" | "success" | "error"; text: string };
  onSave: () => void;
  onReset: () => void;
}) {
  const disabled = busy || (modelsUnknown && availableModels.length === 0);
  return (
    <div className="ds-flow-panel">
      <div className="ds-flow-panel-hd">
        <span style={{ fontWeight: 700, fontSize: 14.5 }}>{stage.label}</span>
        <span className={`ds-pill ${overridden ? "ds-pill-hit" : "ds-pill-neutral"}`}>
          {overridden ? "Overridden" : "Default"}
        </span>
      </div>
      <div className="ds-flow-panel-bd">
        {stage.calibrated && (
          <div className="ds-flow-warnrow">
            <span>&#9650;</span>
            <span>
              This stage has tuned safety limits measured against its current model and prompt. Changing either
              may need those limits revisited.
            </span>
          </div>
        )}

        {modelsUnknown && (
          <div className="ds-pill ds-pill-err" style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 5, fontSize: 12, display: "block" }}>
            Ollama is unreachable — model editing is disabled until it is reachable again.
          </div>
        )}

        <Field label="Model">
          <select
            value={draftValue}
            onChange={(e) => onDraftChange(e.target.value)}
            disabled={disabled}
            className="ds-input"
            style={{ cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.62 : 1 }}
          >
            {draftValue && !modelsUnknown && !availableModels.includes(draftValue) && (
              <option value={draftValue}>{draftValue} (not installed)</option>
            )}
            {draftValue && modelsUnknown && <option value={draftValue}>{draftValue}</option>}
            {availableModels.map((model) => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
        </Field>
        {!modelsUnknown && (
          <div className="ds-field-hint" style={{ marginTop: -8, marginBottom: 14 }}>
            installed: {availableModels.join(" · ") || "none found"}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Button variant="primary" onClick={onSave} loading={busy} disabled={disabled}>
            Save
          </Button>
          {overridden && (
            <Button onClick={onReset} disabled={busy}>
              Reset to default
            </Button>
          )}
        </div>

        {status.kind !== "idle" && status.text && (
          <div style={{ marginTop: 10, fontSize: 12, color: status.kind === "success" ? "var(--green)" : "var(--red)" }}>
            {status.text}
          </div>
        )}
      </div>
    </div>
  );
}

function ExternalEditor({ config, workspaceSlug }: { config: LlmConfigResponse; workspaceSlug: string }) {
  const overridden = "external_model" in config.overrides;
  return (
    <div className="ds-flow-panel">
      <div className="ds-flow-panel-hd">
        <span style={{ fontWeight: 700, fontSize: 14.5 }}>External answer</span>
        <span className={`ds-pill ${overridden ? "ds-pill-hit" : "ds-pill-neutral"}`}>
          {overridden ? "Overridden" : "Default"}
        </span>
      </div>
      <div className="ds-flow-panel-bd">
        <p style={{ fontSize: 12.5, color: "var(--fg-dim)", lineHeight: 1.6, margin: "0 0 14px" }}>
          The external model is configured on the Settings page, alongside the provider and API key it depends
          on. Model choice lives in exactly one place — edit it there.
        </p>
        <Field label="Current model">
          <div className="ds-input" style={{ fontFamily: "var(--font-mono)", color: "#ffcda1" }}>
            {config.external_model}
          </div>
        </Field>
        <Link href={`/dashboard/settings?workspace=${workspaceSlug}`}>
          <Button variant="primary">Go to Settings</Button>
        </Link>
      </div>
    </div>
  );
}
