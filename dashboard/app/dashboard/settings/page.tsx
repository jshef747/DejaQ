import { redirect } from "next/navigation";
import Topbar from "@/components/Topbar";
import { listOrgs } from "@/app/actions/orgs";
import { getLlmConfig } from "@/app/actions/llm-config";
import { listCredentials } from "@/app/actions/credentials";
import SettingsClient from "./SettingsClient";
import type { CredentialItem, LlmConfigResponse, OrgItem } from "@/lib/types";

export const dynamic = "force-dynamic";

function NoOrgsState() {
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
          No organizations found. Create one first with{" "}
          <span style={{ color: "var(--fg)", fontFamily: "var(--font-mono)", fontSize: "11px" }}>
            dejaq-admin org create
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
  searchParams: Promise<{ org?: string }>;
}) {
  const { org } = await searchParams;
  let orgs: OrgItem[] = [];

  try {
    orgs = await listOrgs();
  } catch {
    orgs = [];
  }

  let activeSlug = org;
  if (!activeSlug && orgs.length > 0) {
    redirect(`/dashboard/settings?org=${orgs[0].slug}`);
  }

  if (!activeSlug) {
    return <NoOrgsState />;
  }

  const activeOrg = orgs.find((item) => item.slug === activeSlug);
  let config: LlmConfigResponse | null = null;
  let credentials: CredentialItem[] = [];
  let error: string | null = null;

  try {
    [config, credentials] = await Promise.all([
      getLlmConfig(activeSlug),
      listCredentials(activeSlug),
    ]);
  } catch (e) {
    error = (e as Error).message;
  }

  return (
    <>
      <Topbar section="Settings" orgId={activeSlug} />
      {config ? (
        <SettingsClient
          orgSlug={activeSlug}
          orgName={activeOrg?.name ?? activeSlug}
          initialConfig={config}
          initialCredentials={credentials}
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
