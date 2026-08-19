"use server";

import { apiFetch } from "@/lib/api";
import type { ProvidersListResponse } from "@/lib/types";

export async function getProviders(): Promise<
  { ok: true; data: ProvidersListResponse } | { ok: false; error: string }
> {
  let res: Response;
  try {
    res = await apiFetch("/admin/v1/providers");
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: `Failed to load providers (${res.status})` };
  }

  const data = (await res.json()) as ProvidersListResponse;
  return { ok: true, data };
}
