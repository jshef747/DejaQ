"use server";

import { apiFetch } from "@/lib/api";
import type { AvailableModelsResponse } from "@/lib/types";

export async function getAvailableModels(
  refresh = false,
): Promise<{ ok: true; data: AvailableModelsResponse } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`/admin/v1/available-models${refresh ? "?refresh=true" : ""}`);
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: `Failed to load available models (${res.status})` };
  }

  const data = (await res.json()) as AvailableModelsResponse;
  return { ok: true, data };
}
