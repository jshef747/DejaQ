export const dynamic = "force-dynamic";

import Topbar from "@/components/Topbar";
import { listAllDepartments, listOrgs } from "@/app/actions/orgs";
import { listDeptStats } from "@/app/actions/departments";
import TreeClient from "./TreeClient";
import type { DeptStatsItem } from "@/lib/types";

export default async function TreePage() {
  let orgs: Awaited<ReturnType<typeof listOrgs>> = [];
  let allDepts: Awaited<ReturnType<typeof listAllDepartments>> = [];
  let error: string | null = null;

  try {
    [orgs, allDepts] = await Promise.all([listOrgs(), listAllDepartments()]);
  } catch (e) {
    error = (e as Error).message;
  }

  const statsMap: Record<string, DeptStatsItem> = {};
  if (orgs.length > 0) {
    const results = await Promise.allSettled(orgs.map((o) => listDeptStats(o.slug)));
    for (let i = 0; i < results.length; i++) {
      const r = results[i];
      if (r.status === "fulfilled") {
        for (const item of r.value.items) {
          statsMap[`${item.org}::${item.department}`] = item;
        }
      }
    }
  }

  return (
    <>
      <Topbar section="Org Tree" />
      <TreeClient orgs={orgs} allDepts={allDepts} statsMap={statsMap} error={error} />
    </>
  );
}
