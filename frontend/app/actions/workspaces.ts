"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";
import type { DepartmentItem, WorkspaceItem } from "@/lib/types";
import { responseErrorMessage } from "./errors";

export async function listWorkspaces(): Promise<WorkspaceItem[]> {
  const res = await apiFetch("/admin/v1/workspaces");
  if (!res.ok) throw new Error(`Failed to load workspaces (${res.status})`);
  return res.json() as Promise<WorkspaceItem[]>;
}

export async function listAllDepartments(): Promise<DepartmentItem[]> {
  const res = await apiFetch("/admin/v1/departments");
  if (!res.ok) throw new Error(`Failed to load departments (${res.status})`);
  return res.json() as Promise<DepartmentItem[]>;
}

export async function createWorkspace(
  name: string,
): Promise<{ ok: true; workspace: WorkspaceItem } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch("/admin/v1/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (res.status === 409) {
    return { ok: false, error: "A workspace with that name already exists." };
  }

  if (!res.ok) {
    return { ok: false, error: await responseErrorMessage(res, `Create failed (${res.status})`) };
  }

  const workspace = (await res.json()) as WorkspaceItem;
  revalidatePath("/dashboard/workspaces");
  return { ok: true, workspace };
}

export async function deleteWorkspace(
  slug: string,
): Promise<{ ok: true } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`/admin/v1/workspaces/${encodeURIComponent(slug)}`, {
      method: "DELETE",
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: await responseErrorMessage(res, `Delete failed (${res.status})`) };
  }

  revalidatePath("/dashboard/workspaces");
  return { ok: true };
}
