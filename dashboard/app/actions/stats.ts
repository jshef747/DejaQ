"use server";

import { apiFetch } from "@/lib/api";
import type { DeptStatsReport } from "@/lib/types";

export async function listDeptStatsRange(
  orgSlug: string,
  from?: string,
  to?: string,
): Promise<DeptStatsReport> {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const qs = params.size ? `?${params}` : "";
  const res = await apiFetch(
    `/admin/v1/stats/orgs/${encodeURIComponent(orgSlug)}/departments${qs}`,
  );
  if (!res.ok) throw new Error(`Failed to load stats (${res.status})`);
  return res.json() as Promise<DeptStatsReport>;
}
