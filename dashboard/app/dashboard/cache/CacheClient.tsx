"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, Database, Pencil, Trash2 } from "lucide-react";
import Button from "@/components/ui/Button";
import Pill from "@/components/ui/Pill";
import EmptyState from "@/components/ui/EmptyState";
import SectionHeader from "@/components/ui/SectionHeader";
import Modal from "@/components/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";
import { listCacheEntries, getCacheEntryDetail, editCacheEntryAnswer, deleteCacheEntry } from "@/app/actions/cache";
import type { CacheEntryItem, CacheEntryPage, DepartmentItem } from "@/lib/types";

const fmt = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

const KIND_PILL: Record<string, { label: string; variant: "neutral" | "blue" | "purple" | "green" | "amber" }> = {
  text: { label: "text", variant: "neutral" },
  alias: { label: "alias", variant: "blue" },
  human: { label: "human", variant: "green" },
  image: { label: "image", variant: "purple" },
  file: { label: "file", variant: "purple" },
  rag: { label: "rag", variant: "amber" },
};

function formatStoredAt(value: string): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : fmt.format(d);
}

interface Props {
  workspaceSlug: string;
  departments: DepartmentItem[];
  initialDept: string;
  initialPage: CacheEntryPage | null;
  initialError: string | null;
  pageSize: number;
}

export default function CacheClient({
  workspaceSlug,
  departments,
  initialDept,
  initialPage,
  initialError,
  pageSize,
}: Props) {
  const [activeDept, setActiveDept] = useState(initialDept);
  const [page, setPage] = useState<CacheEntryPage | null>(initialPage);
  const [error, setError] = useState<string | null>(initialError);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const [editEntry, setEditEntry] = useState<CacheEntryItem | null>(null);
  const [editAnswer, setEditAnswer] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [editErr, setEditErr] = useState<string | null>(null);

  const [deleteEntry, setDeleteEntry] = useState<CacheEntryItem | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  async function loadPage(deptSlug: string, offset: number) {
    setLoading(true);
    setError(null);
    try {
      const next = await listCacheEntries(workspaceSlug, deptSlug, pageSize, offset);
      setPage(next);
      setExpandedId(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function selectDept(deptSlug: string) {
    if (deptSlug === activeDept) return;
    setActiveDept(deptSlug);
    loadPage(deptSlug, 0);
  }

  async function openEdit(entry: CacheEntryItem) {
    setEditErr(null);
    setEditAnswer("");
    setEditEntry(entry);
    setEditBusy(true);
    const res = await getCacheEntryDetail(workspaceSlug, activeDept, entry.id);
    setEditBusy(false);
    if (!res.ok) {
      setEditErr(res.error);
      return;
    }
    setEditAnswer(res.data.answer);
  }

  async function handleSaveEdit() {
    if (!editEntry) return;
    setEditBusy(true);
    setEditErr(null);
    const res = await editCacheEntryAnswer(workspaceSlug, activeDept, editEntry.id, editAnswer);
    setEditBusy(false);
    if (!res.ok) {
      setEditErr(res.error);
      return;
    }
    setEditEntry(null);
    setSuccessMsg(res.data.redirected ? "Answer updated on the root entry and its aliases." : "Answer updated.");
    setTimeout(() => setSuccessMsg(null), 4000);
    await loadPage(activeDept, page?.offset ?? 0);
  }

  async function handleConfirmDelete() {
    if (!deleteEntry) return;
    setDeleteBusy(true);
    setDeleteErr(null);
    const res = await deleteCacheEntry(workspaceSlug, activeDept, deleteEntry.id);
    setDeleteBusy(false);
    if (!res.ok) {
      setDeleteErr(res.error);
      return;
    }
    setDeleteEntry(null);
    setSuccessMsg("Cache entry deleted.");
    setTimeout(() => setSuccessMsg(null), 4000);
    const currentOffset = page?.offset ?? 0;
    const remainingOnPage = (page?.items.length ?? 1) - 1;
    const nextOffset = remainingOnPage <= 0 && currentOffset > 0 ? Math.max(0, currentOffset - pageSize) : currentOffset;
    await loadPage(activeDept, nextOffset);
  }

  const total = page?.total ?? 0;
  const offset = page?.offset ?? 0;
  const items = page?.items ?? [];
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + items.length, total);

  return (
    <div className="ds-page">
      <SectionHeader
        title="Cache"
        subtitle="Inspect cached Q&A entries for the selected workspace. Departments are cache partitions."
      />

      {departments.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
          {departments.map((dept) => (
            <button
              key={dept.slug}
              onClick={() => selectDept(dept.slug)}
              className={`ds-nav-item${dept.slug === activeDept ? " active" : ""}`}
              style={{ display: "inline-flex", width: "auto", padding: "6px 12px" }}
            >
              {dept.name}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="ds-pill ds-pill-err" style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
          {error}
        </div>
      )}
      {successMsg && (
        <div className="ds-pill ds-pill-green" style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
          {successMsg}
        </div>
      )}

      {!error && items.length === 0 ? (
        <div className="ds-table-wrap">
          <EmptyState
            icon={Database}
            title="Empty"
            description="This department has no cached entries yet."
          />
        </div>
      ) : !error ? (
        <div className="ds-table-wrap">
          {/* ds-table-wrap itself clips (overflow: hidden) rather than scrolls, so
              this table — wider than most, with 7 columns — needs its own
              horizontal scroll at narrow widths instead of silently losing columns. */}
          <div style={{ overflowX: "auto" }}>
          <table className="ds-table">
            <thead>
              <tr>
                <th style={{ width: 28 }} />
                <th>Prompt</th>
                <th>Cached answer</th>
                <th>Kind</th>
                <th>Score / hits</th>
                <th>Stored</th>
                <th style={{ width: 70 }} />
              </tr>
            </thead>
            <tbody>
              {items.map((entry) => {
                const expanded = expandedId === entry.id;
                const pill = KIND_PILL[entry.kind] ?? KIND_PILL.text;
                const promptText = entry.original_query_preview || entry.normalized_query_preview;
                return (
                  <Fragment key={entry.id}>
                    <tr style={{ cursor: "pointer" }} onClick={() => setExpandedId(expanded ? null : entry.id)}>
                      <td>
                        {expanded ? <ChevronDown size={14} style={{ color: "var(--fg-dimmer)" }} /> : <ChevronRight size={14} style={{ color: "var(--fg-dimmer)" }} />}
                      </td>
                      <td style={{ maxWidth: 260 }}>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={promptText}>
                          {promptText}
                        </div>
                        <div className="ds-dim ds-mono" style={{ fontSize: 11, marginTop: 2 }}>{entry.id}</div>
                      </td>
                      <td style={{ maxWidth: 360 }}>
                        <div
                          style={{
                            display: "-webkit-box",
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: "vertical",
                            overflow: "hidden",
                            fontSize: 12,
                            color: "var(--fg-dim)",
                          }}
                        >
                          {entry.answer_preview}
                        </div>
                      </td>
                      <td>
                        <Pill variant={pill.variant}>{pill.label}</Pill>
                      </td>
                      <td className="ds-dim" style={{ fontSize: 12 }}>
                        {entry.score.toFixed(1)} / {entry.hit_count}
                      </td>
                      <td className="ds-dim" style={{ fontSize: 12 }}>{formatStoredAt(entry.stored_at)}</td>
                      <td onClick={(e) => e.stopPropagation()} style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        <Button variant="ghost" size="sm" onClick={() => openEdit(entry)} aria-label={`Edit answer for ${entry.id}`} title="Edit answer">
                          <Pencil size={12} />
                        </Button>
                        <Button
                          variant="ghost-danger"
                          size="sm"
                          onClick={() => { setDeleteErr(null); setDeleteEntry(entry); }}
                          aria-label={`Delete entry ${entry.id}`}
                          title="Delete entry"
                        >
                          <Trash2 size={12} />
                        </Button>
                      </td>
                    </tr>
                    {expanded && (
                      <tr>
                        <td />
                        <td colSpan={6}>
                          <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "8px 0 16px" }}>
                            <div>
                              <div className="ds-dim" style={{ fontSize: 11, marginBottom: 4 }}>Normalized query</div>
                              <div style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}>{entry.normalized_query_preview}</div>
                            </div>
                            <div>
                              <div className="ds-dim" style={{ fontSize: 11, marginBottom: 4 }}>Cached answer{entry.text_truncated ? " (truncated)" : ""}</div>
                              <div
                                style={{
                                  fontSize: 12,
                                  whiteSpace: "pre-wrap",
                                  maxHeight: 240,
                                  overflowY: "auto",
                                  background: "var(--bg-2)",
                                  border: "1px solid var(--border)",
                                  borderRadius: 5,
                                  padding: 10,
                                }}
                              >
                                {entry.answer_preview}
                              </div>
                            </div>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 18px", fontSize: 11 }} className="ds-dim">
                              <span>department: {activeDept}</span>
                              <span>namespace: {page?.cache_namespace}</span>
                              <span>score: {entry.score.toFixed(1)}</span>
                              <span>hits: {entry.hit_count}</span>
                              <span>negatives: {entry.negative_count}</span>
                              {entry.alias_of && <span>alias of: {entry.alias_of}</span>}
                              {entry.authored && <span>authored: {entry.authored}</span>}
                              {entry.attachment_kind && <span>attachment: {entry.attachment_kind}</span>}
                              {entry.file_kind && <span>file kind: {entry.file_kind}</span>}
                              {entry.rag_document_ids.length > 0 && <span>rag docs: {entry.rag_document_ids.join(", ")}</span>}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          </div>

          {/* Extra bottom clearance: `next dev`'s own floating dev-tools button is
              pinned bottom-right (see dashboard/AGENTS.md) and would otherwise sit
              directly on top of "Next" when the page is scrolled all the way down. */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 4px 40px", fontSize: 12 }}>
            <span className="ds-dim">
              {total === 0 ? "No entries" : `Showing ${rangeStart}-${rangeEnd} of ${total}`}
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              <Button
                size="sm"
                disabled={loading || offset <= 0}
                onClick={() => loadPage(activeDept, Math.max(0, offset - pageSize))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                disabled={loading || offset + items.length >= total}
                onClick={() => loadPage(activeDept, offset + pageSize)}
              >
                Next
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Edit answer modal */}
      <Modal
        open={!!editEntry}
        onClose={() => setEditEntry(null)}
        title="Edit cached answer"
        subtitle="Only the answer changes. The normalized query and its embedding stay unchanged."
        widthPx={560}
        footer={
          <>
            <Button onClick={() => setEditEntry(null)} disabled={editBusy}>Cancel</Button>
            <Button variant="primary" onClick={handleSaveEdit} loading={editBusy} disabled={!editAnswer.trim()}>
              Save
            </Button>
          </>
        }
      >
        {editErr && (
          <div className="ds-pill ds-pill-err" style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
            {editErr}
          </div>
        )}
        <textarea
          className="ds-input ds-input-sans"
          value={editAnswer}
          onChange={(e) => setEditAnswer(e.target.value)}
          rows={10}
          style={{ resize: "vertical", minHeight: 160, fontFamily: "inherit", width: "100%" }}
        />
      </Modal>

      {/* Delete confirm */}
      <ConfirmDialog
        open={!!deleteEntry}
        title="Delete cache entry"
        message={`Delete cache entry "${deleteEntry?.id ?? ""}"? Its aliases are removed too. This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        busy={deleteBusy}
        error={deleteErr}
        onCancel={() => setDeleteEntry(null)}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}
