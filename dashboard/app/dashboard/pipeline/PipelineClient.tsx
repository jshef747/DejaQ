"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Button from "@/components/ui/Button";
import Field from "@/components/ui/Field";
import SectionHeader from "@/components/ui/SectionHeader";
import { updateLlmConfig } from "@/app/actions/llm-config";
import { getAvailableModels } from "@/app/actions/available-models";
import type {
  AvailableModelsResponse,
  LlmConfigResponse,
  LlmConfigUpdate,
  PipelineRole,
  PromptField,
  TokenBudgetField,
} from "@/lib/types";

interface Props {
  workspaceSlug: string;
  initialConfig: LlmConfigResponse;
  initialAvailableModels: AvailableModelsResponse;
  loadError: string | null;
}

interface PromptMeta {
  key: PromptField;
  label: string;
}

interface BudgetMeta {
  key: TokenBudgetField;
  label: string;
  hint: string;
}

interface StageMeta {
  key: PipelineRole;
  label: string;
  sub: string;
  calibrated?: boolean;
  prompts: PromptMeta[];
  budgets?: BudgetMeta[];
}

// The three per-workspace token budgets, each mirroring a global default in
// server/app/config.py. Shared metadata so the label/hint reads identically
// everywhere the field is attached (a stage can govern more than one).
const BUDGET_META: Record<TokenBudgetField, BudgetMeta> = {
  default_max_tokens: {
    key: "default_max_tokens",
    label: "Answer generation budget",
    hint: "Answer length when the caller sends no limit of its own.",
  },
  rewrite_max_tokens: {
    key: "rewrite_max_tokens",
    label: "Rewrite budget",
    hint: "Output budget for generalize (store) and adjust (serve) - must stay comfortably above the answer budget.",
  },
  ollama_num_ctx: {
    key: "ollama_num_ctx",
    label: "Context window",
    hint: "Must hold the generation above plus the prompt carrying it - must stay comfortably above the rewrite budget.",
  },
};

// Order matches the flow, top to bottom.
const STAGES: StageMeta[] = [
  {
    key: "enricher_model",
    label: "Context Enricher",
    sub: "makes a follow-up standalone",
    prompts: [{ key: "enricher_system_prompt", label: "System prompt" }],
    budgets: [BUDGET_META.ollama_num_ctx],
  },
  {
    key: "normalizer_model",
    label: "Normalizer",
    sub: "builds the cache key",
    prompts: [{ key: "normalizer_system_prompt", label: "System prompt" }],
    budgets: [BUDGET_META.ollama_num_ctx],
  },
  {
    key: "validator_model",
    label: "Cache Validator",
    sub: "2 prompts: text & files",
    prompts: [
      { key: "validator_system_prompt", label: "Text-question prompt" },
      { key: "validator_image_system_prompt", label: "Image & file-attachment prompt" },
    ],
    budgets: [BUDGET_META.ollama_num_ctx],
  },
  {
    key: "adjuster_model",
    label: "Context Adjuster",
    sub: "rewrites to match phrasing",
    calibrated: true,
    prompts: [{ key: "adjuster_system_prompt", label: "System prompt" }],
    budgets: [BUDGET_META.rewrite_max_tokens, BUDGET_META.ollama_num_ctx],
  },
  {
    key: "local_model",
    label: "Local answer",
    sub: "easy questions",
    prompts: [{ key: "local_model_system_prompt", label: "System prompt (used only when the caller sends none)" }],
    budgets: [BUDGET_META.default_max_tokens],
  },
  {
    key: "generalizer_model",
    label: "Generalizer",
    sub: "strips tone before storing",
    calibrated: true,
    prompts: [{ key: "generalizer_system_prompt", label: "System prompt" }],
    budgets: [BUDGET_META.rewrite_max_tokens, BUDGET_META.ollama_num_ctx],
  },
];
const STAGE_BY_KEY = Object.fromEntries(STAGES.map((s) => [s.key, s])) as Record<PipelineRole, StageMeta>;

// Budgets governing more than one stage. A per-stage "Reset to default" must
// leave these alone: clearing one from the Normalizer panel would silently
// shrink the window the Enricher, Validator and Adjuster run on too. Clear a
// shared budget by emptying its field and saving, or with "Reset all stages".
// default_max_tokens counts as shared even though only one STAGES entry lists
// it - the External answer panel consumes it as well.
const SHARED_BUDGET_KEYS = new Set<TokenBudgetField>([
  "default_max_tokens",
  ...STAGES.flatMap((s) => (s.budgets ?? []).map((b) => b.key)).filter(
    (key, _i, all) => all.filter((k) => k === key).length > 1,
  ),
]);

function stageOverridden(stage: StageMeta, config: LlmConfigResponse): boolean {
  return (
    stage.key in config.overrides ||
    stage.prompts.some((p) => p.key in config.overrides) ||
    (stage.budgets ?? []).some((b) => b.key in config.overrides)
  );
}

type SelectedStage = PipelineRole | "external_model" | null;
type StatusState = { kind: "idle" | "success" | "error"; text: string };

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
  const [draftPrompts, setDraftPrompts] = useState<Record<string, string>>({});
  // Empty string = "no override, use the default" - never the number 0. Seeded
  // from config.overrides below, never from the resolved value shown as each
  // field's placeholder.
  const [draftBudgets, setDraftBudgets] = useState<Record<string, string>>({});

  const [availableModels, setAvailableModels] = useState(initialAvailableModels);
  const [modelsRefreshing, setModelsRefreshing] = useState(false);

  const [saveBusy, setSaveBusy] = useState(false);
  const [resetAllBusy, setResetAllBusy] = useState(false);
  const [status, setStatus] = useState<StatusState>({ kind: "idle", text: "" });
  const [resetAllStatus, setResetAllStatus] = useState<StatusState>({ kind: "idle", text: "" });

  const configKey = JSON.stringify(initialConfig);
  useEffect(() => {
    setConfig(initialConfig);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configKey]);

  useEffect(() => {
    if (!selected || selected === "external_model") return;
    const stage = STAGE_BY_KEY[selected];
    setDraftValue(config[selected] ?? "");
    const prompts: Record<string, string> = {};
    for (const p of stage.prompts) prompts[p.key] = config[p.key] ?? "";
    setDraftPrompts(prompts);
    const budgets: Record<string, string> = {};
    for (const b of stage.budgets ?? []) {
      budgets[b.key] = b.key in config.overrides ? String(config[b.key]) : "";
    }
    setDraftBudgets(budgets);
  }, [selected, config]);

  // Separate from the draft seeding above on purpose: every successful save
  // replaces `config`, so clearing the status alongside the draft would wipe
  // the "Saved." confirmation on the very next commit. Only switching stages
  // clears it.
  useEffect(() => {
    setStatus({ kind: "idle", text: "" });
  }, [selected]);

  async function handleRefreshModels() {
    setModelsRefreshing(true);
    const res = await getAvailableModels(true);
    setModelsRefreshing(false);
    setAvailableModels(res.ok ? res.data : { models: [], error: res.error });
  }

  function buildStagePatch(stage: StageMeta): LlmConfigUpdate {
    const patch: Record<string, string | number | null> = {};
    if (draftValue !== (config[stage.key] ?? "")) patch[stage.key] = draftValue;
    for (const p of stage.prompts) {
      if (draftPrompts[p.key] !== (config[p.key] ?? "")) patch[p.key] = draftPrompts[p.key];
    }
    for (const b of stage.budgets ?? []) {
      const currentOverride = b.key in config.overrides ? String(config[b.key]) : "";
      const draft = (draftBudgets[b.key] ?? "").trim();
      if (draft !== currentOverride) patch[b.key] = draft === "" ? null : Number(draft);
    }
    return patch as LlmConfigUpdate;
  }

  async function handleSaveStage() {
    if (!selected || selected === "external_model") return;
    const stage = STAGE_BY_KEY[selected];
    const patch = buildStagePatch(stage);
    if (Object.keys(patch).length === 0) {
      setStatus({ kind: "idle", text: "No changes to save." });
      return;
    }
    setSaveBusy(true);
    setStatus({ kind: "idle", text: "" });
    const res = await updateLlmConfig(workspaceSlug, patch);
    setSaveBusy(false);
    if (!res.ok) {
      setStatus({ kind: "error", text: res.error });
      return;
    }
    setConfig(res.data);
    setStatus({ kind: "success", text: "Saved." });
    router.refresh();
  }

  async function handleResetStage(stage: StageMeta) {
    setSaveBusy(true);
    setStatus({ kind: "idle", text: "" });
    const patch: Record<string, null> = { [stage.key]: null };
    for (const p of stage.prompts) patch[p.key] = null;
    for (const b of stage.budgets ?? []) {
      if (!SHARED_BUDGET_KEYS.has(b.key)) patch[b.key] = null;
    }
    const res = await updateLlmConfig(workspaceSlug, patch as LlmConfigUpdate);
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
    setResetAllStatus({ kind: "idle", text: "" });
    setStatus({ kind: "idle", text: "" });
    const patch: Record<string, null> = {};
    for (const stage of STAGES) {
      patch[stage.key] = null;
      for (const p of stage.prompts) patch[p.key] = null;
      for (const b of stage.budgets ?? []) patch[b.key] = null;
    }
    const res = await updateLlmConfig(workspaceSlug, patch as LlmConfigUpdate);
    setResetAllBusy(false);
    if (!res.ok) {
      setResetAllStatus({ kind: "error", text: res.error });
      return;
    }
    setConfig(res.data);
    setResetAllStatus({ kind: "success", text: "All stages reset to default." });
    router.refresh();
  }

  const overriddenCount = STAGES.filter((s) => stageOverridden(s, config)).length;
  const modelsUnknown = !!availableModels.error;

  return (
    <div className="ds-page">
      <SectionHeader
        title="Pipeline"
        subtitle="Choose the model and system prompt for each stage of the request pipeline. Only models installed on this server are selectable."
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
        <StatusText status={resetAllStatus} />
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
          <FanConnector direction="out" />

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
              <div className="ds-flow-col-spacer" />
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
              <div className="ds-flow-col-spacer" />
            </div>
          </div>

          <FanConnector direction="in" />
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
          <div className="ds-flow-empty">Click a stage in the flow to view or change its model and prompt.</div>
        ) : selected === "external_model" ? (
          <ExternalEditor
            config={config}
            workspaceSlug={workspaceSlug}
            onConfigUpdate={(next) => {
              setConfig(next);
              router.refresh();
            }}
          />
        ) : (
          <StageEditor
            stage={STAGE_BY_KEY[selected]}
            overridden={stageOverridden(STAGE_BY_KEY[selected], config)}
            draftValue={draftValue}
            onDraftChange={setDraftValue}
            draftPrompts={draftPrompts}
            onDraftPromptChange={(key, value) => setDraftPrompts((prev) => ({ ...prev, [key]: value }))}
            draftBudgets={draftBudgets}
            onDraftBudgetChange={(key, value) => setDraftBudgets((prev) => ({ ...prev, [key]: value }))}
            config={config}
            availableModels={availableModels.models}
            modelsUnknown={modelsUnknown}
            busy={saveBusy}
            status={status}
            onSave={handleSaveStage}
            onReset={() => handleResetStage(STAGE_BY_KEY[selected])}
          />
        )}
      </div>
    </div>
  );
}

function StatusText({ status, style }: { status: StatusState; style?: React.CSSProperties }) {
  if (status.kind === "idle" || !status.text) return null;
  return (
    <span
      style={{
        fontSize: 12,
        color: status.kind === "success" ? "var(--green)" : "var(--red)",
        ...style,
      }}
    >
      {status.text}
    </span>
  );
}

// Real elbowed connectors between the trunk and both branch columns:
// "out" fans one incoming line into two (down, over, down) reaching the
// HIT/MISS column heads; "in" mirrors it, merging both column tails back
// into one line. Sized to match .ds-flow-branch (max-width 640px) so
// x=25/50/75 line up with the branch's left-column/center/right-column
// positions - the two straight .ds-flow-conn lines this replaces sat in the
// 14px gutter between the columns and visibly connected to nothing.
function FanConnector({ direction }: { direction: "out" | "in" }) {
  const paths =
    direction === "out"
      ? ["M50,0 L50,12 L25,12 L25,30", "M50,0 L50,12 L75,12 L75,30"]
      : ["M25,0 L25,18 L50,18 L50,30", "M75,0 L75,18 L50,18 L50,30"];
  return (
    <svg className="ds-flow-fan" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
      {paths.map((d) => (
        <path key={d} d={d} vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
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
  const overridden = stageOverridden(stage, config);
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
  draftPrompts,
  onDraftPromptChange,
  draftBudgets,
  onDraftBudgetChange,
  config,
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
  draftPrompts: Record<string, string>;
  onDraftPromptChange: (key: string, value: string) => void;
  draftBudgets: Record<string, string>;
  onDraftBudgetChange: (key: string, value: string) => void;
  config: LlmConfigResponse;
  availableModels: string[];
  modelsUnknown: boolean;
  busy: boolean;
  status: StatusState;
  onSave: () => void;
  onReset: () => void;
}) {
  // Ollama reachability only gates the MODEL picker - a system prompt has no
  // relationship to what's installed, so Save must stay usable for a
  // prompt-only edit even while Ollama is down (the model select just holds
  // at its last-known value and won't be part of the patch unless changed).
  const modelPickerDisabled = busy || (modelsUnknown && availableModels.length === 0);
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
            name={`${stage.key}-model`}
            value={draftValue}
            onChange={(e) => onDraftChange(e.target.value)}
            disabled={modelPickerDisabled}
            className="ds-input"
            style={{ cursor: modelPickerDisabled ? "not-allowed" : "pointer", opacity: modelPickerDisabled ? 0.62 : 1 }}
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

        {(stage.budgets ?? []).some((b) => b.key === "ollama_num_ctx") && (
          <div className="ds-field-hint" style={{ marginTop: -8, marginBottom: 14 }}>
            Changing the model can change what context window is safe - check the Context window setting below still fits it.
          </div>
        )}

        {stage.prompts.map((p) => (
          <Field key={p.key} label={p.label}>
            <textarea
              name={p.key}
              value={draftPrompts[p.key] ?? ""}
              onChange={(e) => onDraftPromptChange(p.key, e.target.value)}
              disabled={busy}
              className="ds-textarea"
              rows={7}
              style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, lineHeight: 1.6, opacity: busy ? 0.62 : 1 }}
            />
          </Field>
        ))}

        {(stage.budgets ?? []).map((b) => (
          <Field
            key={b.key}
            label={b.label}
            hint={[
              b.hint,
              SHARED_BUDGET_KEYS.has(b.key)
                ? "Shared with every other stage that uses it, so “Reset to default” below leaves it untouched - empty this field and save to clear it."
                : "",
              `Empty uses the default shown as the placeholder (${config.token_budget_defaults[b.key]} tokens).`,
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <input
              name={b.key}
              type="number"
              min={1}
              inputMode="numeric"
              value={draftBudgets[b.key] ?? ""}
              onChange={(e) => onDraftBudgetChange(b.key, e.target.value)}
              disabled={busy}
              placeholder={String(config.token_budget_defaults[b.key])}
              className="ds-input"
              style={{ fontFamily: "var(--font-mono)", opacity: busy ? 0.62 : 1 }}
            />
          </Field>
        ))}

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Button variant="primary" onClick={onSave} loading={busy} disabled={busy}>
            Save
          </Button>
          {overridden && (
            <Button onClick={onReset} disabled={busy}>
              Reset to default
            </Button>
          )}
        </div>

        <StatusText status={status} style={{ display: "block", marginTop: 10 }} />
      </div>
    </div>
  );
}

function ExternalEditor({
  config,
  workspaceSlug,
  onConfigUpdate,
}: {
  config: LlmConfigResponse;
  workspaceSlug: string;
  onConfigUpdate: (next: LlmConfigResponse) => void;
}) {
  // The model itself lives on Settings (tied to the provider credential), but
  // the answer generation budget governs BOTH the local and external routes
  // (see BUDGET_META.default_max_tokens / decision.md) - the external panel
  // owns its own tiny save flow for that one field rather than routing
  // through the flow-node selection state the model/prompt stages use.
  const budgetKey: TokenBudgetField = "default_max_tokens";
  const modelOverridden = "external_model" in config.overrides;
  const budgetOverridden = budgetKey in config.overrides;

  const [draftBudget, setDraftBudget] = useState(budgetKey in config.overrides ? String(config[budgetKey]) : "");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<StatusState>({ kind: "idle", text: "" });

  useEffect(() => {
    setDraftBudget(budgetKey in config.overrides ? String(config[budgetKey]) : "");
    setStatus({ kind: "idle", text: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  async function handleSave() {
    const current = budgetOverridden ? String(config[budgetKey]) : "";
    const draft = draftBudget.trim();
    if (draft === current) {
      setStatus({ kind: "idle", text: "No changes to save." });
      return;
    }
    setBusy(true);
    setStatus({ kind: "idle", text: "" });
    const res = await updateLlmConfig(workspaceSlug, { [budgetKey]: draft === "" ? null : Number(draft) });
    setBusy(false);
    if (!res.ok) {
      setStatus({ kind: "error", text: res.error });
      return;
    }
    onConfigUpdate(res.data);
    setStatus({ kind: "success", text: "Saved." });
  }

  async function handleReset() {
    setBusy(true);
    setStatus({ kind: "idle", text: "" });
    const res = await updateLlmConfig(workspaceSlug, { [budgetKey]: null });
    setBusy(false);
    if (!res.ok) {
      setStatus({ kind: "error", text: res.error });
      return;
    }
    onConfigUpdate(res.data);
    setStatus({ kind: "success", text: "Reset to default." });
  }

  return (
    <div className="ds-flow-panel">
      <div className="ds-flow-panel-hd">
        <span style={{ fontWeight: 700, fontSize: 14.5 }}>External answer</span>
        <span className={`ds-pill ${modelOverridden ? "ds-pill-hit" : "ds-pill-neutral"}`}>
          {modelOverridden ? "Overridden" : "Default"}
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

        <div style={{ height: 1, background: "var(--border)", margin: "18px 0" }} />

        <Field
          label={BUDGET_META[budgetKey].label}
          hint={`${BUDGET_META[budgetKey].hint} Shared with Local answer, below. Empty uses the default shown as the placeholder (${config.token_budget_defaults[budgetKey]} tokens).`}
        >
          <input
            name={budgetKey}
            type="number"
            min={1}
            inputMode="numeric"
            value={draftBudget}
            onChange={(e) => setDraftBudget(e.target.value)}
            disabled={busy}
            placeholder={String(config.token_budget_defaults[budgetKey])}
            className="ds-input"
            style={{ fontFamily: "var(--font-mono)", opacity: busy ? 0.62 : 1 }}
          />
        </Field>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Button variant="primary" onClick={handleSave} loading={busy} disabled={busy}>
            Save
          </Button>
          {budgetOverridden && (
            <Button onClick={handleReset} disabled={busy}>
              Reset to default
            </Button>
          )}
        </div>
        <StatusText status={status} style={{ display: "block", marginTop: 10 }} />
      </div>
    </div>
  );
}
