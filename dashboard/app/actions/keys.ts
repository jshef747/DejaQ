"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";
import type { ApiKeyCreated, ApiKeyDeleted, ApiKeyItem } from "@/lib/types";
import { responseErrorMessage } from "./errors";

export async function listKeys(orgSlug: string): Promise<ApiKeyItem[]> {
  const res = await apiFetch(`/admin/v1/orgs/${encodeURIComponent(orgSlug)}/keys`);
  if (!res.ok) throw new Error(`Failed to load API keys (${res.status})`);
  return res.json() as Promise<ApiKeyItem[]>;
}

export async function generateKey(
  orgSlug: string,
  force = false,
): Promise<{ ok: true; key: ApiKeyCreated } | { ok: false; error: string; conflict?: true }> {
  let res: Response;
  try {
    const url = `/admin/v1/orgs/${encodeURIComponent(orgSlug)}/keys${force ? "?force=true" : ""}`;
    res = await apiFetch(url, { method: "POST" });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (res.status === 409) {
    return { ok: false, error: "Active key exists — use Rotate to replace it.", conflict: true };
  }

  if (!res.ok) {
    return { ok: false, error: await responseErrorMessage(res, `Generate failed (${res.status})`) };
  }

  const key = (await res.json()) as ApiKeyCreated;
  revalidatePath("/dashboard/keys");
  return { ok: true, key };
}

export async function revokeKey(
  keyId: number,
): Promise<{ ok: true } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`/admin/v1/keys/${keyId}`, { method: "DELETE" });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: await responseErrorMessage(res, `Revoke failed (${res.status})`) };
  }

  revalidatePath("/dashboard/keys");
  return { ok: true };
}

export async function deleteRevokedKey(
  keyId: number,
): Promise<{ ok: true; deleted: ApiKeyDeleted } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`/admin/v1/keys/${keyId}/revoked`, { method: "DELETE" });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: await responseErrorMessage(res, `Delete failed (${res.status})`) };
  }

  const deleted = (await res.json()) as ApiKeyDeleted;
  revalidatePath("/dashboard/keys");
  return { ok: true, deleted };
}
