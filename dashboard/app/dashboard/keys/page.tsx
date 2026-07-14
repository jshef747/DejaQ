import { redirect } from "next/navigation";
import Topbar from "@/components/Topbar";
import { listWorkspaces } from "@/app/actions/workspaces";
import { listKeys } from "@/app/actions/keys";
import KeysClient from "./KeysClient";
import type { ApiKeyItem } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function ApiKeysPage({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string }>;
}) {
  const { workspace } = await searchParams;

  let activeSlug = workspace;
  let workspaceList: Awaited<ReturnType<typeof listWorkspaces>> = [];
  let backendOk = true;
  try {
    workspaceList = await listWorkspaces();
  } catch {
    backendOk = false;
  }

  // If the slug from the URL no longer exists (e.g. workspace was deleted), treat as absent.
  if (activeSlug && !workspaceList.some((w) => w.slug === activeSlug)) {
    activeSlug = undefined;
  }

  // Redirect to the first valid workspace when none is selected.
  // IMPORTANT: redirect() throws NEXT_REDIRECT — must NOT be inside a catch block.
  if (backendOk && !activeSlug && workspaceList.length > 0) {
    redirect(`/dashboard/keys?workspace=${workspaceList[0].slug}`);
  }

  if (!activeSlug) {
    return (
      <>
        <Topbar section="API Keys" />
        <div style={{ padding: "24px 28px", flex: 1 }}>
          <div style={{ marginBottom: "20px" }}>
            <h1
              style={{
                fontSize: "18px",
                fontWeight: 600,
                letterSpacing: "-0.02em",
                margin: "0 0 4px",
              }}
            >
              API Keys
            </h1>
          </div>
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
            <span
              style={{ fontFamily: "var(--font-mono)", color: "var(--fg)", fontSize: "11px" }}
            >
              dejaq-admin workspace create
            </span>
            , then come back here.
          </div>
        </div>
      </>
    );
  }

  let keys: ApiKeyItem[] = [];
  let error: string | null = null;

  try {
    keys = await listKeys(activeSlug);
  } catch (e) {
    error = (e as Error).message;
  }

  return (
    <>
      <Topbar section="API Keys" workspaceId={activeSlug} />
      <KeysClient workspaceSlug={activeSlug} keys={keys} error={error} />
    </>
  );
}
