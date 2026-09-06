import { redirect } from "next/navigation";
import Topbar from "@/components/Topbar";
import SectionHeader from "@/components/ui/SectionHeader";
import EmptyState from "@/components/ui/EmptyState";
import { Database } from "lucide-react";
import { listWorkspaces } from "@/app/actions/workspaces";
import { listDepartments } from "@/app/actions/departments";
import { listCacheEntries } from "@/app/actions/cache";
import CacheClient from "./CacheClient";
import type { CacheEntryPage } from "@/lib/types";

export const dynamic = "force-dynamic";

const CACHE_PAGE_SIZE = 50;

export default async function CachePage({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string; department?: string }>;
}) {
  const { workspace, department } = await searchParams;

  let activeSlug = workspace;
  let workspaceList: Awaited<ReturnType<typeof listWorkspaces>> = [];
  let backendOk = true;
  try {
    workspaceList = await listWorkspaces();
  } catch {
    backendOk = false;
  }

  if (activeSlug && !workspaceList.some((w) => w.slug === activeSlug)) {
    activeSlug = undefined;
  }

  // IMPORTANT: redirect() throws NEXT_REDIRECT — must NOT be inside a catch block.
  if (backendOk && !activeSlug && workspaceList.length > 0) {
    redirect(`/dashboard/cache?workspace=${workspaceList[0].slug}`);
  }

  if (!activeSlug) {
    return (
      <>
        <Topbar section="Cache" />
        <div className="ds-page">
          <SectionHeader title="Cache" subtitle="Inspect cached Q&A entries for the selected workspace. Departments are cache partitions." />
          <div className="ds-table-wrap">
            <EmptyState
              icon={Database}
              title="No workspaces found"
              description="Use the onboarding flow or run dejaq-admin workspace create, then come back here."
            />
          </div>
        </div>
      </>
    );
  }

  let depts: Awaited<ReturnType<typeof listDepartments>> = [];
  let deptError: string | null = null;
  try {
    depts = await listDepartments(activeSlug);
  } catch (e) {
    deptError = (e as Error).message;
  }

  let activeDept = department;
  if (activeDept && !depts.some((d) => d.slug === activeDept)) {
    activeDept = undefined;
  }
  if (!deptError && !activeDept && depts.length > 0) {
    redirect(`/dashboard/cache?workspace=${activeSlug}&department=${depts[0].slug}`);
  }

  if (!activeDept) {
    return (
      <>
        <Topbar section="Cache" workspaceId={activeSlug} />
        <div className="ds-page">
          <SectionHeader title="Cache" subtitle="Inspect cached Q&A entries for the selected workspace. Departments are cache partitions." />
          <div className="ds-table-wrap">
            <EmptyState
              icon={Database}
              title={deptError ?? "No departments yet"}
              description={deptError ? undefined : "Create a department first, then come back here."}
            />
          </div>
        </div>
      </>
    );
  }

  let page: CacheEntryPage | null = null;
  let error: string | null = null;
  try {
    page = await listCacheEntries(activeSlug, activeDept, CACHE_PAGE_SIZE, 0);
  } catch (e) {
    error = (e as Error).message;
  }

  return (
    <>
      <Topbar section="Cache" workspaceId={activeSlug} />
      <CacheClient
        key={`${activeSlug}:${activeDept}`}
        workspaceSlug={activeSlug}
        departments={depts}
        initialDept={activeDept}
        initialPage={page}
        initialError={error}
        pageSize={CACHE_PAGE_SIZE}
      />
    </>
  );
}
