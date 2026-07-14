import { redirect } from "next/navigation";
import Topbar from "@/components/Topbar";
import { listOrgs } from "@/app/actions/orgs";
import { listKeys } from "@/app/actions/keys";
import KeysClient from "./KeysClient";
import type { ApiKeyItem } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function ApiKeysPage({
  searchParams,
}: {
  searchParams: Promise<{ org?: string }>;
}) {
  const { org } = await searchParams;

  let activeSlug = org;
  if (!activeSlug) {
    try {
      const orgs = await listOrgs();
      if (orgs.length > 0) {
        redirect(`/dashboard/keys?org=${orgs[0].slug}`);
      }
    } catch {
      // Fall through — show no-orgs state below
    }
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
            No organizations found. Create one first with{" "}
            <span
              style={{ fontFamily: "var(--font-mono)", color: "var(--fg)", fontSize: "11px" }}
            >
              dejaq-admin org create
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
      <Topbar section="API Keys" orgId={activeSlug} />
      <KeysClient orgSlug={activeSlug} keys={keys} error={error} />
    </>
  );
}
