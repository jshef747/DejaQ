"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";
import type { CredentialItem, Provider } from "@/lib/types";

async function errorMessage(res: Response, fallback: string) {
  let msg = fallback;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") msg = body.detail;
    else if (typeof body?.message === "string") msg = body.message;
  } catch {}
  return msg;
}

export async function listCredentials(orgSlug: string): Promise<CredentialItem[]> {
  const res = await apiFetch(`/admin/v1/orgs/${encodeURIComponent(orgSlug)}/credentials`);
  if (!res.ok) throw new Error(`Failed to load credentials (${res.status})`);
  return res.json() as Promise<CredentialItem[]>;
}

export async function upsertCredential(
  orgSlug: string,
  provider: Provider,
  apiKey: string,
): Promise<{ ok: true; data: CredentialItem } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(
      `/admin/v1/orgs/${encodeURIComponent(orgSlug)}/credentials/${encodeURIComponent(provider)}`,
      {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey }),
      },
    );
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: await errorMessage(res, `Credential save failed (${res.status})`) };
  }

  const data = (await res.json()) as CredentialItem;
  revalidatePath("/dashboard/settings");
  return { ok: true, data };
}

export async function deleteCredential(
  orgSlug: string,
  provider: Provider,
): Promise<{ ok: true } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(
      `/admin/v1/orgs/${encodeURIComponent(orgSlug)}/credentials/${encodeURIComponent(provider)}`,
      { method: "DELETE" },
    );
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: await errorMessage(res, `Credential removal failed (${res.status})`) };
  }

  revalidatePath("/dashboard/settings");
  return { ok: true };
}
