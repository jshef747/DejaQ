"use server";

import { apiFetch } from "@/lib/api";
import type { DepartmentItem, OrgItem } from "@/lib/types";

export async function listOrgs(): Promise<OrgItem[]> {
  const res = await apiFetch("/admin/v1/orgs");
  if (!res.ok) throw new Error(`Failed to load organizations (${res.status})`);
  return res.json() as Promise<OrgItem[]>;
}

export async function listAllDepartments(): Promise<DepartmentItem[]> {
  const res = await apiFetch("/admin/v1/departments");
  if (!res.ok) throw new Error(`Failed to load departments (${res.status})`);
  return res.json() as Promise<DepartmentItem[]>;
}
