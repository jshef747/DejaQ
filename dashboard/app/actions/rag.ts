"use server";

import { revalidatePath } from "next/cache";
import { apiFetch, apiUpload } from "@/lib/api";
import type { RagDocumentItem } from "@/lib/types";
import { responseErrorMessage } from "./errors";

function base(slug: string) {
  return `/admin/v1/workspaces/${encodeURIComponent(slug)}/rag-documents`;
}

export async function listRagDocuments(workspaceSlug: string): Promise<RagDocumentItem[]> {
  const res = await apiFetch(base(workspaceSlug));
  if (!res.ok) throw new Error(`Failed to load knowledge base (${res.status})`);
  return res.json() as Promise<RagDocumentItem[]>;
}

export async function addRagText(
  workspaceSlug: string,
  title: string,
  content: string,
): Promise<{ ok: true; data: RagDocumentItem } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`${base(workspaceSlug)}/text`, {
      method: "POST",
      body: JSON.stringify({ title, content }),
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
  if (!res.ok) return { ok: false, error: await responseErrorMessage(res, `Add failed (${res.status})`) };
  const data = (await res.json()) as RagDocumentItem;
  revalidatePath("/dashboard/rag");
  return { ok: true, data };
}

export async function addRagUrl(
  workspaceSlug: string,
  url: string,
  title?: string,
): Promise<{ ok: true; data: RagDocumentItem } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`${base(workspaceSlug)}/url`, {
      method: "POST",
      body: JSON.stringify({ url, title: title || null }),
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
  if (!res.ok) return { ok: false, error: await responseErrorMessage(res, `Add failed (${res.status})`) };
  const data = (await res.json()) as RagDocumentItem;
  revalidatePath("/dashboard/rag");
  return { ok: true, data };
}

export type RagRepoImportResponse = {
  repo: string;
  ref: string;
  group_key: string;
  documents: RagDocumentItem[];
  indexed_files: number;
  skipped_files: number;
  removed_documents: number;
};

export async function addRagRepo(
  workspaceSlug: string,
  url: string,
  ref?: string,
): Promise<{ ok: true; data: RagRepoImportResponse } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`${base(workspaceSlug)}/repo`, {
      method: "POST",
      body: JSON.stringify({ url, ref: ref || null }),
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
  if (!res.ok) return { ok: false, error: await responseErrorMessage(res, `Import failed (${res.status})`) };
  const data = (await res.json()) as RagRepoImportResponse;
  revalidatePath("/dashboard/rag");
  return { ok: true, data };
}

export async function deleteRagGroup(
  workspaceSlug: string,
  docIds: number[],
): Promise<{ ok: true } | { ok: false; error: string }> {
  // No bulk endpoint: a repository is N ordinary documents, so removing it is
  // N ordinary deletes. Each one already clears its own Chroma chunks and any
  // cache entry grounded in it, which a bulk route would have to redo anyway.
  for (const id of docIds) {
    const res = await deleteRagDocument(workspaceSlug, id);
    if (!res.ok) return res;
  }
  return { ok: true };
}

export async function uploadRagFile(
  workspaceSlug: string,
  formData: FormData,
): Promise<{ ok: true; data: RagDocumentItem } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiUpload(`${base(workspaceSlug)}/upload`, formData);
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
  if (!res.ok) return { ok: false, error: await responseErrorMessage(res, `Upload failed (${res.status})`) };
  const data = (await res.json()) as RagDocumentItem;
  revalidatePath("/dashboard/rag");
  return { ok: true, data };
}

export async function deleteRagDocument(
  workspaceSlug: string,
  docId: number,
): Promise<{ ok: true } | { ok: false; error: string }> {
  let res: Response;
  try {
    res = await apiFetch(`${base(workspaceSlug)}/${docId}`, { method: "DELETE" });
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
  if (!res.ok) return { ok: false, error: await responseErrorMessage(res, `Delete failed (${res.status})`) };
  revalidatePath("/dashboard/rag");
  return { ok: true };
}
