import Topbar from "@/components/Topbar";
import { listAllDepartments, listWorkspaces } from "@/app/actions/workspaces";
import { listDeptStats } from "@/app/actions/departments";
import WorkspacesClient from "./WorkspacesClient";
import type { DeptStatsItem } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function WorkspacesPage({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string }>;
}) {
  const { workspace: activeWorkspaceSlug } = await searchParams;

  let workspaces: Awaited<ReturnType<typeof listWorkspaces>> = [];
  let allDepts: Awaited<ReturnType<typeof listAllDepartments>> = [];
  let error: string | null = null;

  try {
    [workspaces, allDepts] = await Promise.all([listWorkspaces(), listAllDepartments()]);
  } catch (e) {
    error = (e as Error).message;
  }

  // Fetch stats for each workspace in parallel; failures are non-fatal
  const statsMap: Record<string, DeptStatsItem> = {};
  if (workspaces.length > 0) {
    const results = await Promise.allSettled(workspaces.map((w) => listDeptStats(w.slug)));
    for (let i = 0; i < results.length; i++) {
      const r = results[i];
      if (r.status === "fulfilled") {
        for (const item of r.value.items) {
          statsMap[`${item.workspace}::${item.department}`] = item;
        }
      }
    }
  }

  return (
    <>
      <Topbar section="Workspaces" workspaceId={activeWorkspaceSlug} />
      <WorkspacesClient
        workspaces={workspaces}
        allDepts={allDepts}
        statsMap={statsMap}
        error={error}
      />
    </>
  );
}
