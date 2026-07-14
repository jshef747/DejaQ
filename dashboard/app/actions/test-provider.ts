"use server";

import { responseErrorMessage as errorMessage } from "@/app/actions/errors";
import { apiFetch } from "@/lib/api";
import type { TestProviderResponse } from "@/lib/types";

export async function testProvider(
  orgSlug: string,
  model: string,
): Promise<{ ok: true; data: TestProviderResponse } | { ok: false; error: string; status?: number }> {
  let res: Response;
  try {
    res = await apiFetch(`/admin/v1/orgs/${encodeURIComponent(orgSlug)}/test-provider`, {
      method: "POST",
      body: JSON.stringify({ model }),
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }

  if (!res.ok) {
    return {
      ok: false,
      error: await errorMessage(res, `Provider test failed (${res.status})`),
      status: res.status,
    };
  }

  return { ok: true, data: (await res.json()) as TestProviderResponse };
}
