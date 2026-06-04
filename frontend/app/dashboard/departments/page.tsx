import { redirect } from "next/navigation";
import Topbar from "@/components/Topbar";
import { listWorkspaces } from "@/app/actions/workspaces";
import { listDepartments, listDeptStats } from "@/app/actions/departments";
import DepartmentsClient from "./DepartmentsClient";
import type { DepartmentItem, DeptStatsItem, WorkspaceItem } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function DepartmentsPage({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string }>;
}) {
  const { workspace } = await searchParams;

  let workspaces: WorkspaceItem[] = [];
  let activeSlug = workspace;
  let backendOk = true;

  try {
    workspaces = await listWorkspaces();
  } catch {
    backendOk = false;
  }

  // If the slug from the URL no longer exists (e.g. workspace was deleted), treat as absent.
  if (activeSlug && !workspaces.some((w) => w.slug === activeSlug)) {
    activeSlug = undefined;
  }

  // Redirect to the first valid workspace when none is selected.
  // IMPORTANT: redirect() throws NEXT_REDIRECT — must NOT be inside a catch block.
  if (backendOk && !activeSlug && workspaces.length > 0) {
    redirect(`/dashboard/departments?workspace=${workspaces[0].slug}`);
  }

  if (!activeSlug) {
    return (
      <>
        <Topbar section="Departments" />
        <div style={{ padding: "24px 28px", flex: 1 }}>
          <h1 style={{ fontSize: "22px", fontWeight: 600, letterSpacing: "-0.02em", margin: "0 0 20px" }}>Departments</h1>
          <div style={{ background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "6px", color: "var(--fg-dim)", fontSize: "12px", padding: "20px 18px" }}>
            No workspaces found. Use the onboarding flow or run{" "}
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--fg)", fontSize: "11px" }}>dejaq-admin workspace create --name &quot;My Workspace&quot;</span>
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
      <Topbar section="Departments" workspaceId={activeSlug} />
      <DepartmentsClient
        workspaceSlug={activeSlug}
        workspaces={workspaces}
        depts={depts}
        statsItems={statsItems}
        error={error}
      />
    </>
  );
}
