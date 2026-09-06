"use server";

import { apiFetch } from "@/lib/api";
import type { CacheEntryDeleteResult, CacheEntryEditResult, CacheEntryPage } from "@/lib/types";
import { responseErrorMessage } from "./errors";

function base(workspaceSlug: string, entryId?: string) {
  const path = `/admin/v1/workspaces/${encodeURIComponent(workspaceSlug)}/cache-entries`;
  return entryId ? `${path}/${encodeURIComponent(entryId)}` : path;
}

export async function listCacheEntries(
  workspaceSlug: string,
  department: string,
  limit: number,
  offset: number,
): Promise<CacheEntryPage> {
  const params = new URLSearchParams({
    department,
    limit: String(limit),
    offset: String(offset),
  });
  const res = await apiFetch(`${base(workspaceSlug)}?${params}`);
  if (!res.ok) throw new Error(await responseErrorMessage(res, `Failed to load cache entries (${res.status})`));
  return res.json() as Promise<CacheEntryPage>;
}

export async function editCacheEntryAnswer(
  workspaceSlug: string,
  department: string,
  entryId: string,
  answer: string,
): Promise<{ ok: true; data: CacheEntryEditResult } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`${base(workspaceSlug, entryId)}?${new URLSearchParams({ department })}`, {
      method: "PUT",
      body: JSON.stringify({ answer }),
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
  if (!res.ok) return { ok: false, error: await responseErrorMessage(res, `Save failed (${res.status})`) };
  const data = (await res.json()) as CacheEntryEditResult;
  return { ok: true, data };
}

export async function deleteCacheEntry(
  workspaceSlug: string,
  department: string,
  entryId: string,
): Promise<{ ok: true; data: CacheEntryDeleteResult } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`${base(workspaceSlug, entryId)}?${new URLSearchParams({ department })}`, {
      method: "DELETE",
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
  if (!res.ok) return { ok: false, error: await responseErrorMessage(res, `Delete failed (${res.status})`) };
  const data = (await res.json()) as CacheEntryDeleteResult;
  return { ok: true, data };
}
