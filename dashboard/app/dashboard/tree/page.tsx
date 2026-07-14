export const dynamic = "force-dynamic";

import Topbar from "@/components/Topbar";
import { listAllDepartments, listWorkspaces } from "@/app/actions/workspaces";
import { listDeptStats } from "@/app/actions/departments";
import TreeClient from "./TreeClient";
import type { DeptStatsItem } from "@/lib/types";

export default async function TreePage() {
  let workspaces: Awaited<ReturnType<typeof listWorkspaces>> = [];
  let allDepts: Awaited<ReturnType<typeof listAllDepartments>> = [];
  let error: string | null = null;

  try {
    [workspaces, allDepts] = await Promise.all([listWorkspaces(), listAllDepartments()]);
  } catch (e) {
    error = (e as Error).message;
  }

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
      <Topbar section="Workspace Tree" />
      <TreeClient workspaces={workspaces} allDepts={allDepts} statsMap={statsMap} error={error} />
    </>
  );
}
