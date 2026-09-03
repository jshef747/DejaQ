import { redirect } from "next/navigation";
import Topbar from "@/components/Topbar";
import { listWorkspaces } from "@/app/actions/workspaces";
import { getLlmConfig } from "@/app/actions/llm-config";
import { getAvailableModels } from "@/app/actions/available-models";
import PipelineClient from "./PipelineClient";
import type { AvailableModelsResponse, LlmConfigResponse, WorkspaceItem } from "@/lib/types";

export const dynamic = "force-dynamic";

function NoWorkspacesState() {
  return (
    <>
      <Topbar section="Pipeline" />
      <div style={{ flex: 1, padding: "24px 28px" }}>
        <h1 style={{ fontSize: "18px", fontWeight: 600, letterSpacing: 0, margin: "0 0 16px" }}>
          Pipeline
        </h1>
        <div
          style={{
            background: "var(--bg-2)",
            border: "1px solid var(--border)",
            borderRadius: "6px",
            color: "var(--fg-dim)",
            fontSize: "12px",
            padding: "20px 18px",
          }}
        >
          No workspaces found. Use the onboarding flow or run{" "}
          <span style={{ color: "var(--fg)", fontFamily: "var(--font-mono)", fontSize: "11px" }}>
            dejaq-admin workspace create
          </span>
          , then come back here.
        </div>
      </div>
    </>
  );
}

export default async function PipelinePage({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string }>;
}) {
  const { workspace } = await searchParams;
  let workspaces: WorkspaceItem[] = [];

  try {
    workspaces = await listWorkspaces();
  } catch {
    workspaces = [];
  }

  let activeSlug = workspace;

  // If the slug from the URL no longer exists (e.g. workspace was deleted), treat as absent.
  if (activeSlug && !workspaces.some((w) => w.slug === activeSlug)) {
    activeSlug = undefined;
  }

  if (!activeSlug && workspaces.length > 0) {
    redirect(`/dashboard/pipeline?workspace=${workspaces[0].slug}`);
  }

  if (!activeSlug) {
    return <NoWorkspacesState />;
  }

  let config: LlmConfigResponse | null = null;
  let error: string | null = null;

  try {
    config = await getLlmConfig(activeSlug);
  } catch (e) {
    error = (e as Error).message;
  }

  // Best-effort: an unreachable Ollama must not take down the whole page -
  // it disables editing of the model pickers, with the reason shown
  // (PipelineClient renders availableModels.error).
  let availableModels: AvailableModelsResponse = { models: [], error: null };
  const modelsRes = await getAvailableModels();
  if (modelsRes.ok) {
    availableModels = modelsRes.data;
  } else {
    availableModels = { models: [], error: modelsRes.error };
  }

  return (
    <>
      <Topbar section="Pipeline" workspaceId={activeSlug} />
      {config ? (
        <PipelineClient
          workspaceSlug={activeSlug}
          initialConfig={config}
          initialAvailableModels={availableModels}
          loadError={error}
        />
      ) : (
        <div style={{ flex: 1, padding: "24px 28px" }}>
          <div
            style={{
              background: "var(--red-bg)",
              border: "1px solid var(--red-border)",
              borderRadius: "6px",
              color: "var(--red)",
              fontSize: "12px",
              padding: "10px 14px",
            }}
          >
            {error ?? "Unable to load the pipeline configuration."}
          </div>
        </div>
      )}
    </>
  );
}
