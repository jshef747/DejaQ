"use server";

import { apiFetch } from "@/lib/api";
import type { CatalogProviderModelsResponse, CatalogProvidersListResponse } from "@/lib/types";

export async function getCatalogProviders(): Promise<
  { ok: true; data: CatalogProvidersListResponse } | { ok: false; error: string }
> {
  let res: Response;
  try {
    res = await apiFetch("/admin/v1/model-catalog/providers");
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: `Failed to load providers (${res.status})` };
  }

  const data = (await res.json()) as CatalogProvidersListResponse;
  return { ok: true, data };
}

// Never call this for every provider up front - one provider's models at a
// time, on demand (plan section 2.11: the full catalog is 349 KB).
export async function getCatalogProviderModels(
  provider: string,
): Promise<{ ok: true; data: CatalogProviderModelsResponse } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`/admin/v1/model-catalog/providers/${encodeURIComponent(provider)}/models`);
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return { ok: false, error: `Failed to load models for '${provider}' (${res.status})` };
  }

  const data = (await res.json()) as CatalogProviderModelsResponse;
  return { ok: true, data };
}
