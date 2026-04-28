"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api";
import type { LlmConfigResponse, LlmConfigUpdate } from "@/lib/types";

async function errorMessage(res: Response, fallback: string) {
  let msg = fallback;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") msg = body.detail;
    else if (typeof body?.message === "string") msg = body.message;
  } catch {}
  return msg;
}

export async function getLlmConfig(orgSlug: string): Promise<LlmConfigResponse> {
  const res = await apiFetch(`/admin/v1/orgs/${encodeURIComponent(orgSlug)}/llm-config`);
  if (!res.ok) throw new Error(`Failed to load LLM configuration (${res.status})`);
  return res.json() as Promise<LlmConfigResponse>;
}

export async function updateLlmConfig(
  orgSlug: string,
  patch: LlmConfigUpdate,
): Promise<{ ok: true; data: LlmConfigResponse } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`/admin/v1/orgs/${encodeURIComponent(orgSlug)}/llm-config`, {
      method: "PUT",
      body: JSON.stringify(patch),
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: await errorMessage(res, `Save failed (${res.status})`) };
  }

  const data = (await res.json()) as LlmConfigResponse;
  revalidatePath("/dashboard/settings");
  return { ok: true, data };
}
