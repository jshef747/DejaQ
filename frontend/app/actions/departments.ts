"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";
import type { DepartmentItem, DeptStatsReport } from "@/lib/types";
import { responseErrorMessage } from "./errors";

export async function listDepartments(workspaceSlug: string): Promise<DepartmentItem[]> {
  const res = await apiFetch(`/admin/v1/departments?workspace=${encodeURIComponent(workspaceSlug)}`);
  if (!res.ok) throw new Error(`Failed to load departments (${res.status})`);
  return res.json() as Promise<DepartmentItem[]>;
}

export async function listDeptStats(workspaceSlug: string): Promise<DeptStatsReport> {
  const res = await apiFetch(`/admin/v1/stats/workspaces/${encodeURIComponent(workspaceSlug)}/departments`);
  if (!res.ok) throw new Error(`Failed to load department stats (${res.status})`);
  return res.json() as Promise<DeptStatsReport>;
}

export async function createDepartment(
  workspaceSlug: string,
  name: string,
): Promise<{ ok: true; dept: DepartmentItem } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`/admin/v1/workspaces/${encodeURIComponent(workspaceSlug)}/departments`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: await responseErrorMessage(res, `Create failed (${res.status})`) };
  }

  const dept = (await res.json()) as DepartmentItem;
  revalidatePath("/dashboard/departments");
  return { ok: true, dept };
}

export async function renameDepartment(
  workspaceSlug: string,
  deptSlug: string,
  name: string,
): Promise<{ ok: true; dept: DepartmentItem } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(
      `/admin/v1/workspaces/${encodeURIComponent(workspaceSlug)}/departments/${encodeURIComponent(deptSlug)}`,
      { method: "PATCH", body: JSON.stringify({ name }) },
    );
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: await responseErrorMessage(res, `Rename failed (${res.status})`) };
  }

  const dept = (await res.json()) as DepartmentItem;
  revalidatePath("/dashboard/departments");
  return { ok: true, dept };
}

export async function deleteDepartment(
  workspaceSlug: string,
  deptSlug: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(
      `/admin/v1/workspaces/${encodeURIComponent(workspaceSlug)}/departments/${encodeURIComponent(deptSlug)}`,
      { method: "DELETE" },
    );
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: await responseErrorMessage(res, `Delete failed (${res.status})`) };
  }

  revalidatePath("/dashboard/departments");
  return { ok: true };
}
