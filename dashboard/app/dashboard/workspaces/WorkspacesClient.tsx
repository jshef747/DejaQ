"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  ChevronRight,
  Hash,
  GripVertical,
  Search,
  Briefcase,
  ExternalLink,
  Plus,
  Pencil,
  Trash2,
} from "lucide-react";
import Modal from "@/components/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Field from "@/components/ui/Field";
import Pill from "@/components/ui/Pill";
import EmptyState from "@/components/ui/EmptyState";
import SectionHeader from "@/components/ui/SectionHeader";
import { createWorkspace, deleteWorkspace, renameWorkspace } from "@/app/actions/workspaces";
import type { DepartmentItem, DeptStatsItem, WorkspaceItem } from "@/lib/types";

const fmtDate = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric" });
function fmtNum(n: number) { return n.toLocaleString("en-US"); }
function fmtPct(n: number) { return (n * 100).toFixed(1) + "%"; }

const COL = "1fr 200px 160px 140px 110px";

interface Props {
  workspaces: WorkspaceItem[];
  allDepts: DepartmentItem[];
  statsMap: Record<string, DeptStatsItem>;
  error: string | null;
}

export default function WorkspacesClient({ workspaces, allDepts, statsMap, error }: Props) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    workspaces.forEach((w, i) => { init[w.slug] = i < 2; });
    return init;
  });
  const [drag, setDrag] = useState<{ kind: "workspace" | "dept"; slug: string; fromWorkspace?: string } | null>(null);
  const [dropTarget, setDropTarget] = useState<{ slug: string; pos: "before" | "after" | "into" } | null>(null);
  const [workspaceOrder, setWorkspaceOrder] = useState(() => workspaces.map((w) => w.slug));

  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);

  const [confirmDeleteSlug, setConfirmDeleteSlug] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  const [renameSlug, setRenameSlug] = useState<string | null>(null);
  const [renameName, setRenameName] = useState("");
  const [renameBusy, setRenameBusy] = useState(false);
  const [renameErr, setRenameErr] = useState<string | null>(null);

  async function handleCreate() {
    const trimmed = createName.trim();
    if (!trimmed) { setCreateErr("Name is required."); return; }
    setCreateBusy(true);
    setCreateErr(null);
    const res = await createWorkspace(trimmed);
    setCreateBusy(false);
    if (!res.ok) { setCreateErr(res.error); return; }
    setCreateOpen(false);
    setCreateName("");
    router.refresh();
  }

  async function handleRename() {
    const trimmed = renameName.trim();
    if (!trimmed) { setRenameErr("Name is required."); return; }
    if (!renameSlug) return;
    setRenameBusy(true);
    setRenameErr(null);
    const res = await renameWorkspace(renameSlug, trimmed);
    setRenameBusy(false);
    if (!res.ok) { setRenameErr(res.error); return; }
    setRenameSlug(null);
    router.refresh();
  }

  async function handleDelete(slug: string) {
    setDeleteBusy(true);
    setDeleteErr(null);
    const res = await deleteWorkspace(slug);
    setDeleteBusy(false);
    if (!res.ok) { setDeleteErr(res.error); return; }
    setConfirmDeleteSlug(null);
    setWorkspaceOrder((o) => o.filter((s) => s !== slug));
    router.refresh();
  }

  const deptsByWorkspace: Record<string, DepartmentItem[]> = {};
  for (const d of allDepts) {
    (deptsByWorkspace[d.workspace_slug] ??= []).push(d);
  }

  const toggle = (slug: string) => setExpanded((e) => ({ ...e, [slug]: !e[slug] }));

  const searchLower = search.toLowerCase();
  const visibleSlugs = search.trim()
    ? workspaceOrder.filter((slug) => {
        const ws = workspaces.find((w) => w.slug === slug);
        if (!ws) return false;
        if (ws.name.toLowerCase().includes(searchLower) || ws.slug.toLowerCase().includes(searchLower)) return true;
        return (deptsByWorkspace[slug] ?? []).some((d) => d.slug.includes(searchLower));
      })
    : workspaceOrder;

  function onWorkspaceDragStart(slug: string) { setDrag({ kind: "workspace", slug }); }
  function onWorkspaceDragOver(e: React.DragEvent, slug: string) {
    if (!drag || drag.kind !== "workspace") return;
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const pos = e.clientY - rect.top < rect.height / 2 ? "before" : "after";
    setDropTarget({ slug, pos });
  }
  function onDeptDragStart(deptSlug: string, fromWorkspace: string) { setDrag({ kind: "dept", slug: deptSlug, fromWorkspace }); }
  function onDeptDragOver(e: React.DragEvent, deptSlug: string) {
    if (!drag || drag.kind !== "dept") return;
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const pos = e.clientY - rect.top < rect.height / 2 ? "before" : "after";
    setDropTarget({ slug: deptSlug, pos });
  }
  function onWorkspaceDropZone(e: React.DragEvent, workspaceSlug: string) {
    if (!drag || drag.kind !== "dept") return;
    e.preventDefault();
    setDropTarget({ slug: workspaceSlug, pos: "into" });
  }
  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    if (!drag || !dropTarget) { setDrag(null); setDropTarget(null); return; }
    if (drag.kind === "workspace" && (dropTarget.pos === "before" || dropTarget.pos === "after")) {
      if (drag.slug !== dropTarget.slug) {
        const next = workspaceOrder.filter((s) => s !== drag.slug);
        const idx = next.indexOf(dropTarget.slug);
        const at = dropTarget.pos === "after" ? idx + 1 : idx;
        next.splice(at, 0, drag.slug);
        setWorkspaceOrder(next);
      }
    }
    setDrag(null);
    setDropTarget(null);
  }

  return (
    <div className="ds-page">
      <SectionHeader
        title="Workspaces"
        subtitle="Drag to reorder. Each workspace owns API keys and provider credentials; each department is a cache partition."
        action={
          <div style={{ display: "flex", gap: 8 }}>
            <Button size="sm" onClick={() => { const all: Record<string, boolean> = {}; workspaces.forEach((w) => (all[w.slug] = true)); setExpanded(all); }}>
              Expand all
            </Button>
            <Button size="sm" onClick={() => setExpanded({})}>Collapse all</Button>
            <Button variant="primary" size="sm" onClick={() => { setCreateName(""); setCreateErr(null); setCreateOpen(true); }}>
              <Plus size={13} /> New workspace
            </Button>
          </div>
        }
      />

      {error && (
        <div className="ds-pill ds-pill-err" style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
          {error}
        </div>
      )}

      <div className="ds-table-wrap">
        {/* Toolbar */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", background: "var(--bg-2)", borderBottom: "1px solid var(--border)" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, maxWidth: 360, minWidth: 220, background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 5, padding: "4px 8px", color: "var(--fg-dim)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
            <Search size={11} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter workspaces and departments…"
              style={{ background: "none", border: "none", color: "var(--fg)", flex: 1, fontFamily: "var(--font-mono)", fontSize: 11, outline: "none" }}
            />
          </label>
          <span style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 11, marginLeft: "auto" }}>
            {visibleSlugs.length} workspace{visibleSlugs.length !== 1 ? "s" : ""} · {allDepts.length} departments
          </span>
        </div>

        {/* Column headers */}
        <div style={{ display: "grid", gridTemplateColumns: COL, gap: 12, padding: "9px 12px", fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--fg-dimmer)", background: "var(--bg-2)", borderBottom: "1px solid var(--border)" }}>
          <div>Name</div>
          <div>Cache stats</div>
          <div>Hit rate</div>
          <div>Created</div>
          <div style={{ textAlign: "right" }}>Actions</div>
        </div>

        {visibleSlugs.length === 0 ? (
          <EmptyState
            icon={Briefcase}
            title="No workspaces"
            description={search ? `No results for "${search}"` : "Create your first workspace to start routing traffic."}
            action={!search ? <Button variant="primary" onClick={() => { setCreateName(""); setCreateErr(null); setCreateOpen(true); }}><Plus size={13} /> New workspace</Button> : undefined}
          />
        ) : (
          <div onDrop={onDrop} onDragEnd={() => { setDrag(null); setDropTarget(null); }}>
            {visibleSlugs.map((slug, wi) => {
              const ws = workspaces.find((w) => w.slug === slug);
              if (!ws) return null;
              const rows = deptsByWorkspace[slug] ?? [];
              const isOpen = !!expanded[slug];
              const wsHits = rows.reduce((a, d) => a + (statsMap[`${slug}::${d.slug}`]?.hits ?? 0), 0);
              const wsMisses = rows.reduce((a, d) => a + (statsMap[`${slug}::${d.slug}`]?.misses ?? 0), 0);
              const wsTotal = wsHits + wsMisses;
              const wsRate = wsTotal ? wsHits / wsTotal : 0;
              const isDragging = drag?.kind === "workspace" && drag.slug === slug;
              const dropBefore = dropTarget?.slug === slug && dropTarget.pos === "before";
              const dropAfter = dropTarget?.slug === slug && dropTarget.pos === "after";
              const dropInto = dropTarget?.slug === slug && dropTarget.pos === "into";

              return (
                <div key={slug}>
                  {dropBefore && <div style={{ height: 2, background: "var(--accent)", margin: "0 12px" }} />}
                  <div
                    draggable
                    onDragStart={() => onWorkspaceDragStart(slug)}
                    onDragOver={(e) => {
                      if (drag?.kind === "dept") { onWorkspaceDropZone(e, slug); return; }
                      onWorkspaceDragOver(e, slug);
                    }}
                    onDragLeave={() => setDropTarget(null)}
                    onClick={() => toggle(slug)}
                    style={{
                      display: "grid",
                      gridTemplateColumns: COL,
                      gap: 12,
                      padding: "10px 12px",
                      alignItems: "center",
                      borderBottom: isOpen || wi < visibleSlugs.length - 1 ? "1px solid var(--border)" : "none",
                      background: dropInto ? "var(--accent-bg)" : isDragging ? "var(--bg-3)" : "transparent",
                      opacity: isDragging ? 0.5 : 1,
                      cursor: "grab",
                      borderLeft: dropInto ? "2px solid var(--accent)" : "2px solid transparent",
                      userSelect: "none",
                      transition: "background 0.1s",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <GripVertical size={12} style={{ color: "var(--fg-dimmer)", flexShrink: 0 }} />
                      <ChevronRight
                        size={11}
                        style={{
                          color: "var(--fg-dim)",
                          transition: "transform 0.12s",
                          transform: isOpen ? "rotate(90deg)" : "none",
                          flexShrink: 0,
                        }}
                      />
                      <span style={{
                        width: 20, height: 20, display: "grid", placeItems: "center",
                        background: "var(--accent-bg)", border: "1px solid var(--accent-border)",
                        borderRadius: 4, color: "var(--accent)", fontFamily: "var(--font-mono)",
                        fontSize: 10, fontWeight: 700, flexShrink: 0,
                      }}>
                        {ws.name.slice(0, 1).toUpperCase()}
                      </span>
                      <span style={{ fontWeight: 500 }}>{ws.name}</span>
                      <span style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 11 }}>{ws.slug}</span>
                      <span style={{ background: "var(--bg-3)", border: "1px solid var(--border-2)", borderRadius: 3, color: "var(--fg-dim)", fontFamily: "var(--font-mono)", fontSize: 10, padding: "1px 6px" }}>
                        {rows.length} dept{rows.length !== 1 ? "s" : ""}
                      </span>
                    </div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-dim)" }}>
                      {rows.length ? (
                        <>
                          <span style={{ color: "var(--accent)" }}>{fmtNum(wsHits)}</span>
                          {" / "}
                          <span style={{ color: "var(--amber)" }}>{fmtNum(wsMisses)}</span>
                        </>
                      ) : (
                        <span style={{ color: "var(--fg-dimmer)" }}>—</span>
                      )}
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, minWidth: 48, color: wsRate >= 0.7 ? "var(--accent)" : "var(--fg)" }}>
                        {wsTotal ? fmtPct(wsRate) : "—"}
                      </span>
                      <div style={{ height: 4, background: "var(--bg-3)", borderRadius: 2, overflow: "hidden", width: 70, flexShrink: 0 }}>
                        <div style={{ height: "100%", background: "var(--accent)", width: (wsRate * 100) + "%" }} />
                      </div>
                    </div>
                    <div className="ds-dim" style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
                      {fmtDate.format(new Date(ws.created_at))}
                    </div>
                    <div style={{ display: "flex", gap: 4, justifyContent: "flex-end" }} onClick={(e) => e.stopPropagation()}>
                      <Button
                        size="sm"
                        onClick={() => router.push(`/dashboard/departments?workspace=${ws.slug}`)}
                        style={{ gap: 4 }}
                      >
                        Open <ExternalLink size={10} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => { setRenameErr(null); setRenameName(ws.name); setRenameSlug(ws.slug); }}
                        aria-label={`Rename workspace ${ws.slug}`}
                      >
                        <Pencil size={12} />
                      </Button>
                      <Button
                        variant="ghost-danger"
                        size="sm"
                        onClick={() => { setDeleteErr(null); setConfirmDeleteSlug(ws.slug); }}
                        aria-label={`Delete workspace ${ws.slug}`}
                      >
                        <Trash2 size={12} />
                      </Button>
                    </div>
                  </div>
                  {dropAfter && !isOpen && <div style={{ height: 2, background: "var(--accent)", margin: "0 12px" }} />}

                  {isOpen && (
                    <div style={{ background: "var(--bg)", borderBottom: wi < visibleSlugs.length - 1 ? "1px solid var(--border)" : "none" }}>
                      {rows.length === 0 && (
                        <div style={{ padding: "14px 12px 14px 58px", color: "var(--fg-dimmer)", fontSize: 12, fontFamily: "var(--font-mono)" }}>
                          no departments yet
                        </div>
                      )}
                      {rows.map((d, di) => {
                        const stats = statsMap[`${slug}::${d.slug}`];
                        const hits = stats?.hits ?? 0;
                        const misses = stats?.misses ?? 0;
                        const total = hits + misses;
                        const rate = total ? hits / total : 0;
                        const deptDragging = drag?.kind === "dept" && drag.slug === d.slug;
                        const deptBefore = dropTarget?.slug === d.slug && dropTarget.pos === "before";
                        const deptAfter = dropTarget?.slug === d.slug && dropTarget.pos === "after";
                        return (
                          <div key={d.id}>
                            {deptBefore && <div style={{ height: 2, background: "var(--accent)", marginLeft: 58, marginRight: 12 }} />}
                            <div
                              draggable
                              onDragStart={() => onDeptDragStart(d.slug, slug)}
                              onDragOver={(e) => onDeptDragOver(e, d.slug)}
                              style={{
                                display: "grid",
                                gridTemplateColumns: COL,
                                gap: 12,
                                padding: "8px 12px",
                                alignItems: "center",
                                borderBottom: di < rows.length - 1 ? "1px solid var(--border)" : "none",
                                opacity: deptDragging ? 0.5 : 1,
                                background: deptDragging ? "var(--bg-3)" : "transparent",
                                cursor: "grab",
                              }}
                            >
                              <div style={{ display: "flex", alignItems: "center", gap: 8, paddingLeft: 44 }}>
                                <GripVertical size={10} style={{ color: "var(--fg-dimmer)" }} />
                                <span style={{ color: "var(--fg-dimmer)" }}>└</span>
                                <Hash size={12} style={{ color: "var(--accent)", flexShrink: 0 }} />
                                <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, fontSize: 12 }}>{d.slug}</span>
                              </div>
                              <div style={{ display: "flex", gap: 4 }}>
                                <Pill variant="hit">HIT {fmtNum(hits)}</Pill>
                                <Pill variant="miss">MISS {fmtNum(misses)}</Pill>
                              </div>
                              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, minWidth: 48, color: rate >= 0.7 ? "var(--accent)" : "var(--fg)" }}>
                                  {total ? fmtPct(rate) : "—"}
                                </span>
                                <div style={{ height: 4, background: "var(--bg-3)", borderRadius: 2, overflow: "hidden", width: 70 }}>
                                  <div style={{ height: "100%", background: "var(--accent)", width: (rate * 100) + "%" }} />
                                </div>
                              </div>
                              <div className="ds-dim" style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
                                {fmtDate.format(new Date(d.created_at))}
                              </div>
                              <div style={{ display: "flex", gap: 4, justifyContent: "flex-end" }}>
                                <Button
                                  size="sm"
                                  onClick={() => router.push(`/dashboard/departments?workspace=${slug}`)}
                                  style={{ gap: 4 }}
                                >
                                  Open <ExternalLink size={10} />
                                </Button>
                              </div>
                            </div>
                            {deptAfter && <div style={{ height: 2, background: "var(--accent)", marginLeft: 58, marginRight: 12 }} />}
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {dropAfter && isOpen && <div style={{ height: 2, background: "var(--accent)", margin: "0 12px" }} />}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div style={{ marginTop: 12, fontSize: 11, color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", display: "flex", gap: 16 }}>
        <span>↕ drag rows to reorder</span>
        <span>↓ click a row to expand</span>
      </div>

      {/* Create workspace modal */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create workspace"
        subtitle="A workspace holds API keys, provider credentials, and departments."
        footer={
          <>
            <Button onClick={() => setCreateOpen(false)} disabled={createBusy}>Cancel</Button>
            <Button variant="primary" onClick={handleCreate} loading={createBusy}>Create workspace</Button>
          </>
        }
      >
        <Field label="Name" required hint="Visible in logs and the dashboard." error={createErr ?? undefined}>
          <Input
            value={createName}
            onChange={(e) => setCreateName(e.target.value)}
            placeholder="e.g. Acme Inc"
            disabled={createBusy}
            autoFocus
          />
        </Field>
      </Modal>

      {/* Rename workspace modal */}
      <Modal
        open={!!renameSlug}
        onClose={() => setRenameSlug(null)}
        title="Rename workspace"
        subtitle={`Slug stays the same (${renameSlug ?? ""}). Only the display name changes.`}
        footer={
          <>
            <Button onClick={() => setRenameSlug(null)} disabled={renameBusy}>Cancel</Button>
            <Button variant="primary" onClick={handleRename} loading={renameBusy}>Save</Button>
          </>
        }
      >
        <Field label="New name" required error={renameErr ?? undefined}>
          <Input
            value={renameName}
            onChange={(e) => setRenameName(e.target.value)}
            disabled={renameBusy}
            autoFocus
          />
        </Field>
      </Modal>

      <ConfirmDialog
        open={!!confirmDeleteSlug}
        title="Delete workspace"
        message={`Delete workspace "${workspaces.find((w) => w.slug === confirmDeleteSlug)?.name ?? confirmDeleteSlug}"? All departments and API keys inside will be permanently removed. This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        busy={deleteBusy}
        onCancel={() => setConfirmDeleteSlug(null)}
        onConfirm={() => confirmDeleteSlug && handleDelete(confirmDeleteSlug)}
      />
      {deleteErr && (
        <div className="ds-pill ds-pill-err" style={{ marginTop: 8, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
          {deleteErr}
        </div>
      )}
    </div>
  );
}
