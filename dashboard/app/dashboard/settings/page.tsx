import { redirect } from "next/navigation";
import Topbar from "@/components/Topbar";
import { listWorkspaces } from "@/app/actions/workspaces";
import { getLlmConfig } from "@/app/actions/llm-config";
import { listCredentials } from "@/app/actions/credentials";
import { getCatalogProviderModels, getCatalogProviders } from "@/app/actions/model-catalog";
import SettingsClient from "./SettingsClient";
import type { CatalogModel, CatalogProviderItem, CredentialItem, LlmConfigResponse, WorkspaceItem } from "@/lib/types";

export const dynamic = "force-dynamic";

function NoWorkspacesState() {
  return (
    <>
      <Topbar section="Settings" />
      <div style={{ flex: 1, padding: "24px 28px" }}>
        <h1 style={{ fontSize: "18px", fontWeight: 600, letterSpacing: 0, margin: "0 0 16px" }}>
          Settings
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

export default async function SettingsPage({
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
  if (!activeSlug && workspaces.length > 0) {
    redirect(`/dashboard/settings?workspace=${workspaces[0].slug}`);
  }

  if (!activeSlug) {
    return <NoWorkspacesState />;
  }

  const activeWorkspace = workspaces.find((item) => item.slug === activeSlug);
  let config: LlmConfigResponse | null = null;
  let credentials: CredentialItem[] = [];
  let catalogProviders: CatalogProviderItem[] = [];
  let initialModelsByProvider: Record<string, CatalogModel[]> = {};
  let error: string | null = null;

  try {
    const [configRes, credentialsList, providersRes] = await Promise.all([
      getLlmConfig(activeSlug),
      listCredentials(activeSlug),
      getCatalogProviders(),
    ]);
    config = configRes;
    credentials = credentialsList;
    if (providersRes.ok) {
      catalogProviders = providersRes.data.providers;
    } else {
      error = providersRes.error;
    }

    // Preload models for providers this workspace already holds a credential
    // for (usually one or two) so the picker opens with the right provider
    // and model already selected. Every other provider's models are fetched
    // on demand when chosen - the full catalog is never loaded at once.
    const credentialedKeys = [...new Set(credentials.map((item) => item.provider))].filter((key) =>
      catalogProviders.some((p) => p.key === key),
    );
    const modelLists = await Promise.all(credentialedKeys.map((key) => getCatalogProviderModels(key)));
    modelLists.forEach((res, i) => {
      if (res.ok) initialModelsByProvider[credentialedKeys[i]] = res.data.models;
    });
  } catch (e) {
    error = (e as Error).message;
  }

  return (
    <>
      <Topbar section="Settings" workspaceId={activeSlug} />
      {config ? (
        <SettingsClient
          workspaceSlug={activeSlug}
          workspaceName={activeWorkspace?.name ?? activeSlug}
          initialConfig={config}
          initialCredentials={credentials}
          catalogProviders={catalogProviders}
          initialModelsByProvider={initialModelsByProvider}
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
            {error ?? "Unable to load settings."}
          </div>
        </div>
      )}
    </>
  );
}
