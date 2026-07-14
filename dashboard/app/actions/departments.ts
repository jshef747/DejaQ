"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";
import type { DepartmentItem, DeptStatsReport } from "@/lib/types";
import { responseErrorMessage } from "./errors";

export async function listDepartments(orgSlug: string): Promise<DepartmentItem[]> {
  const res = await apiFetch(`/admin/v1/departments?org=${encodeURIComponent(orgSlug)}`);
  if (!res.ok) throw new Error(`Failed to load departments (${res.status})`);
  return res.json() as Promise<DepartmentItem[]>;
}

export async function listDeptStats(orgSlug: string): Promise<DeptStatsReport> {
  const res = await apiFetch(`/admin/v1/stats/orgs/${encodeURIComponent(orgSlug)}/departments`);
  if (!res.ok) throw new Error(`Failed to load department stats (${res.status})`);
  return res.json() as Promise<DeptStatsReport>;
}

export async function createDepartment(
  orgSlug: string,
  name: string,
): Promise<{ ok: true; dept: DepartmentItem } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`/admin/v1/orgs/${encodeURIComponent(orgSlug)}/departments`, {
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

export async function deleteDepartment(
  orgSlug: string,
  deptSlug: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(
      `/admin/v1/orgs/${encodeURIComponent(orgSlug)}/departments/${encodeURIComponent(deptSlug)}`,
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
