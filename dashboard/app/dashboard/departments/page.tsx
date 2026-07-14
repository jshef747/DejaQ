import { redirect } from "next/navigation";
import Topbar from "@/components/Topbar";
import { listOrgs } from "@/app/actions/orgs";
import { listDepartments, listDeptStats } from "@/app/actions/departments";
import DepartmentsClient from "./DepartmentsClient";
import type { DepartmentItem, DeptStatsItem } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function DepartmentsPage({
  searchParams,
}: {
  searchParams: Promise<{ org?: string }>;
}) {
  const { org } = await searchParams;

  let orgs: Awaited<ReturnType<typeof listOrgs>> = [];
  let activeSlug = org;

  try {
    orgs = await listOrgs();
  } catch {
    // Fall through — show no-orgs state below
  }

  if (!activeSlug && orgs.length > 0) {
    redirect(`/dashboard/departments?org=${orgs[0].slug}`);
  }

  if (!activeSlug) {
    return (
      <>
        <Topbar section="Departments" />
        <div style={{ padding: "24px 28px", flex: 1 }}>
          <h1 style={{ fontSize: "22px", fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 20px" }}>Departments</h1>
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "6px", color: "var(--fg-dim)", fontSize: "12px", padding: "20px 18px" }}>
            No organizations found. Create one first with{" "}
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--fg)", fontSize: "11px" }}>dejaq-admin org create</span>
            , then come back here.
          </div>
        </div>
      </>
    );
  }

  let depts: DepartmentItem[] = [];
  let statsItems: DeptStatsItem[] = [];
  let error: string | null = null;

  const [deptsResult, statsResult] = await Promise.allSettled([
    listDepartments(activeSlug),
    listDeptStats(activeSlug),
  ]);

  if (deptsResult.status === "fulfilled") {
    depts = deptsResult.value;
  } else {
    error = (deptsResult.reason as Error).message;
  }
  if (statsResult.status === "fulfilled") {
    statsItems = statsResult.value.items;
  }

  return (
    <>
      <Topbar section="Departments" orgId={activeSlug} />
      <DepartmentsClient
        orgSlug={activeSlug}
        orgs={orgs}
        depts={depts}
        statsItems={statsItems}
        error={error}
      />
    </>
  );
}
