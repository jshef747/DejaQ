"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { GripVertical, Hash, Search, Trash2, Plus, Users } from "lucide-react";
import Modal from "@/components/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Field from "@/components/ui/Field";
import Pill from "@/components/ui/Pill";
import EmptyState from "@/components/ui/EmptyState";
import SectionHeader from "@/components/ui/SectionHeader";
import { createDepartment, deleteDepartment } from "@/app/actions/departments";
import type { DepartmentItem, DeptStatsItem, OrgItem } from "@/lib/types";

const fmtDate = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric" });
function fmtNum(n: number) { return n.toLocaleString("en-US"); }
function fmtPct(n: number) { return (n * 100).toFixed(1) + "%"; }

const COL = "1fr 220px 180px 140px 60px";

interface Props {
  orgSlug: string;
  orgs: OrgItem[];
  depts: DepartmentItem[];
  statsItems: DeptStatsItem[];
  error: string | null;
}

export default function DepartmentsClient({ orgSlug, orgs, depts, statsItems, error }: Props) {
  const router = useRouter();

  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);

  const [confirmDeleteSlug, setConfirmDeleteSlug] = useState<string | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteErr, setDeleteErr] = useState<string | null>(null);

  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [drag, setDrag] = useState<{ slug: string } | null>(null);
  const [dropTarget, setDropTarget] = useState<{ slug: string; pos: "before" | "after" } | null>(null);
  const [order, setOrder] = useState(() => depts.map((d) => d.slug));

  const rows = order
    .map((slug) => depts.find((d) => d.slug === slug))
    .filter(Boolean) as DepartmentItem[];
  for (const d of depts) {
    if (!order.includes(d.slug)) rows.push(d);
  }

  const statsMap: Record<string, DeptStatsItem> = {};
  for (const s of statsItems) { statsMap[s.department] = s; }

  const orgHits = statsItems.reduce((a, s) => a + s.hits, 0);
  const orgMisses = statsItems.reduce((a, s) => a + s.misses, 0);
  const orgTotal = orgHits + orgMisses;
  const orgRate = orgTotal ? orgHits / orgTotal : 0;

  async function handleCreate() {
    const trimmed = createName.trim();
    if (!trimmed) { setCreateErr("Name is required."); return; }
    setCreateBusy(true);
    setCreateErr(null);
    const res = await createDepartment(orgSlug, trimmed);
    setCreateBusy(false);
    if (!res.ok) { setCreateErr(res.error); return; }
    setCreateOpen(false);
    setCreateName("");
    router.refresh();
  }

  async function handleDelete(deptSlug: string) {
    setDeleteBusy(true);
    setDeleteErr(null);
    const res = await deleteDepartment(orgSlug, deptSlug);
    setDeleteBusy(false);
    if (!res.ok) { setDeleteErr(res.error); return; }
    setConfirmDeleteSlug(null);
    setOrder((o) => o.filter((s) => s !== deptSlug));
    router.refresh();
  }

  function toggle(slug: string) { setExpanded((e) => ({ ...e, [slug]: !e[slug] })); }

  function onDragStart(slug: string) { setDrag({ slug }); }
  function onDragOver(e: React.DragEvent, slug: string) {
    if (!drag) return;
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const pos = e.clientY - rect.top < rect.height / 2 ? "before" : "after";
    setDropTarget({ slug, pos });
  }
  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    if (!drag || !dropTarget || drag.slug === dropTarget.slug) { setDrag(null); setDropTarget(null); return; }
    const arr = rows.map((d) => d.slug).filter((s) => s !== drag.slug);
    const idx = arr.indexOf(dropTarget.slug);
    const at = dropTarget.pos === "after" ? idx + 1 : idx;
    arr.splice(at, 0, drag.slug);
    setOrder(arr);
    setDrag(null);
    setDropTarget(null);
  }

  const currentOrg = orgs.find((o) => o.slug === orgSlug);

  return (
    <div className="ds-page">
      <SectionHeader
        title="Departments"
        subtitle="Cache partitions inside a single organization. Drag rows to reorder; click a row to inspect its configuration."
        action={
          <Button variant="primary" onClick={() => { setCreateName(""); setCreateErr(null); setCreateOpen(true); }}>
            <Plus size={13} /> New department
          </Button>
        }
      />

      {/* Org scope selector + summary strip */}
      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", border: "1px solid var(--border)", borderRadius: 6, marginBottom: 16, background: "var(--bg-2)", overflow: "hidden" }}>
        <div style={{ padding: "14px 16px", borderRight: "1px solid var(--border)" }}>
          <div style={{ fontSize: 10.5, color: "var(--fg-dimmer)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
            Scoped to organization
          </div>
          <select
            value={orgSlug}
            onChange={(e) => router.push(`/dashboard/departments?org=${e.target.value}`)}
            style={{ width: "100%", background: "var(--bg)", border: "1px solid var(--border-2)", color: "var(--fg)", padding: "7px 10px", borderRadius: 5, outline: "none", fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 500, cursor: "pointer" }}
          >
            {orgs.map((o) => (
              <option key={o.slug} value={o.slug}>{o.name}</option>
            ))}
          </select>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-dimmer)", marginTop: 6 }}>{orgSlug}</div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", alignItems: "center" }}>
          {[
            { label: "Departments", value: rows.length.toString() },
            { label: "Hit rate", value: orgTotal ? fmtPct(orgRate) : "—", accent: true },
            { label: "Requests", value: fmtNum(orgTotal) },
          ].map((m) => (
            <div key={m.label} style={{ padding: "14px 16px", borderRight: "1px solid var(--border)" }}>
              <div style={{ fontSize: 10.5, color: "var(--fg-dimmer)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>{m.label}</div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 18, fontWeight: 600, color: m.accent ? "var(--accent)" : "var(--fg)" }}>{m.value}</div>
            </div>
          ))}
          <div style={{ padding: "14px 16px" }}>
            <div style={{ fontSize: 10.5, color: "var(--fg-dimmer)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>Hits / Misses</div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}>
              <span style={{ color: "var(--accent)" }}>{fmtNum(orgHits)}</span>
              <span style={{ color: "var(--fg-dimmer)" }}> / </span>
              <span style={{ color: "var(--amber)" }}>{fmtNum(orgMisses)}</span>
            </div>
          </div>
        </div>
      </div>

      {(error || deleteErr) && (
        <div className="ds-pill ds-pill-err" style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
          {error ?? deleteErr}
        </div>
      )}

      <div className="ds-table-wrap">
        {/* Toolbar */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", background: "var(--bg-2)", borderBottom: "1px solid var(--border)" }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, maxWidth: 360, minWidth: 220, background: "var(--bg)", border: "1px solid var(--border)", borderRadius: 5, padding: "4px 8px", color: "var(--fg-dim)", fontSize: 11, fontFamily: "var(--font-mono)" }}>
            <Search size={11} />
            <input
              placeholder={`Filter departments in ${currentOrg?.name ?? orgSlug}…`}
              style={{ background: "none", border: "none", color: "var(--fg)", flex: 1, fontFamily: "var(--font-mono)", fontSize: 11, outline: "none" }}
            />
          </label>
          <span style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 11, marginLeft: "auto" }}>
            {rows.length} department{rows.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Column headers */}
        <div style={{ display: "grid", gridTemplateColumns: COL, gap: 12, padding: "9px 12px", fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--fg-dimmer)", background: "var(--bg-2)", borderBottom: "1px solid var(--border)" }}>
          <div>Name</div>
          <div>Cache stats</div>
          <div>Hit rate</div>
          <div>Created</div>
          <div />
        </div>

        {rows.length === 0 && !error ? (
          <EmptyState
            icon={Users}
            title="No departments yet"
            description={`Create a department to start partitioning traffic in ${currentOrg?.name ?? orgSlug}.`}
            action={<Button variant="primary" onClick={() => { setCreateName(""); setCreateErr(null); setCreateOpen(true); }}><Plus size={13} /> New department</Button>}
          />
        ) : (
          <div onDrop={onDrop} onDragEnd={() => { setDrag(null); setDropTarget(null); }}>
            {rows.map((dept, di) => {
              const stats = statsMap[dept.slug];
              const hits = stats?.hits ?? 0;
              const misses = stats?.misses ?? 0;
              const total = hits + misses;
              const rate = total ? hits / total : 0;
              const isOpen = !!expanded[dept.slug];
              const isDragging = drag?.slug === dept.slug;
              const dropBefore = dropTarget?.slug === dept.slug && dropTarget.pos === "before";
              const dropAfter = dropTarget?.slug === dept.slug && dropTarget.pos === "after";
              return (
                <div key={dept.id}>
                  {dropBefore && <div style={{ height: 2, background: "var(--accent)", margin: "0 12px" }} />}
                  <div
                    draggable
                    onDragStart={() => onDragStart(dept.slug)}
                    onDragOver={(e) => onDragOver(e, dept.slug)}
                    onClick={() => toggle(dept.slug)}
                    style={{
                      display: "grid",
                      gridTemplateColumns: COL,
                      gap: 12,
                      padding: "10px 12px",
                      alignItems: "center",
                      borderBottom: isOpen || di < rows.length - 1 ? "1px solid var(--border)" : "none",
                      opacity: isDragging ? 0.5 : 1,
                      background: isDragging ? "var(--bg-3)" : "transparent",
                      cursor: "grab",
                      userSelect: "none",
                      transition: "background 0.1s",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <GripVertical size={12} style={{ color: "var(--fg-dimmer)", flexShrink: 0 }} />
                      <Hash size={12} style={{ color: "var(--accent)", flexShrink: 0 }} />
                      <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, fontSize: 12 }}>{dept.slug}</span>
                      <span style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>{dept.name}</span>
                    </div>
                    <div style={{ display: "flex", gap: 4 }}>
                      <Pill variant="hit">HIT {fmtNum(hits)}</Pill>
                      <Pill variant="miss">MISS {fmtNum(misses)}</Pill>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, minWidth: 48, color: rate >= 0.7 ? "var(--accent)" : "var(--fg)" }}>
                        {total ? fmtPct(rate) : "—"}
                      </span>
                      <div style={{ height: 4, background: "var(--bg-3)", borderRadius: 2, overflow: "hidden", width: 80 }}>
                        <div style={{ height: "100%", background: "var(--accent)", width: (rate * 100) + "%" }} />
                      </div>
                    </div>
                    <div className="ds-dim" style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
                      {fmtDate.format(new Date(dept.created_at))}
                    </div>
                    <div style={{ display: "flex", justifyContent: "flex-end" }} onClick={(e) => e.stopPropagation()}>
                      <Button
                        variant="ghost-danger"
                        size="sm"
                        onClick={() => { setDeleteErr(null); setConfirmDeleteSlug(dept.slug); }}
                        aria-label={`Delete department ${dept.slug}`}
                      >
                        <Trash2 size={12} />
                      </Button>
                    </div>
                  </div>

                  {/* Expanded detail panel */}
                  {isOpen && (
                    <div style={{ background: "var(--bg)", borderBottom: di < rows.length - 1 ? "1px solid var(--border)" : "none", padding: "16px 12px 16px 56px" }}>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
                        <div>
                          <div style={{ fontSize: 10.5, color: "var(--fg-dimmer)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Cache</div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>
                              <span style={{ color: "var(--fg-dimmer)" }}>namespace → </span>{dept.cache_namespace}
                            </div>
                            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>
                              <span style={{ color: "var(--fg-dimmer)" }}>entries → </span>{fmtNum(total)}
                            </div>
                          </div>
                        </div>
                        <div>
                          <div style={{ fontSize: 10.5, color: "var(--fg-dimmer)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Stats</div>
                          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>
                              <span style={{ color: "var(--fg-dimmer)" }}>hit rate → </span>
                              <span style={{ color: total ? (rate >= 0.7 ? "var(--accent)" : "var(--fg)") : "var(--fg-dimmer)" }}>
                                {total ? fmtPct(rate) : "—"}
                              </span>
                            </div>
                            {stats?.avg_latency_ms != null && (
                              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>
                                <span style={{ color: "var(--fg-dimmer)" }}>avg latency → </span>{stats.avg_latency_ms.toFixed(0)} ms
                              </div>
                            )}
                            {stats && (
                              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5 }}>
                                <span style={{ color: "var(--fg-dimmer)" }}>tokens saved → </span>{fmtNum(stats.est_tokens_saved)}
                              </div>
                            )}
                          </div>
                        </div>
                        <div>
                          <div style={{ fontSize: 10.5, color: "var(--fg-dimmer)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>Endpoint</div>
                          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, padding: "6px 8px", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: 4, lineHeight: 1.4, wordBreak: "break-all" }}>
                            POST /v1/chat/completions
                            <span style={{ color: "var(--fg-dimmer)" }}> · X-DejaQ-Department: </span>
                            <span style={{ color: "var(--accent)" }}>{dept.slug}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                  {dropAfter && <div style={{ height: 2, background: "var(--accent)", margin: "0 12px" }} />}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div style={{ marginTop: 12, fontSize: 11, color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", display: "flex", gap: 16 }}>
        <span>↕ drag to reorder · order affects routing priority</span>
        <span>↓ click row to view cache config</span>
      </div>

      {/* Create modal */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Create department"
        subtitle={`New partition inside ${currentOrg?.name ?? orgSlug}`}
        footer={
          <>
            <Button onClick={() => setCreateOpen(false)} disabled={createBusy}>Cancel</Button>
            <Button variant="primary" onClick={handleCreate} loading={createBusy}>Create department</Button>
          </>
        }
      >
        <Field label="Name" required hint="lowercase, hyphen-separated. Visible to end users in logs." error={createErr ?? undefined}>
          <Input
            value={createName}
            onChange={(e) => setCreateName(e.target.value)}
            placeholder="e.g. customer-support"
            disabled={createBusy}
            autoFocus
            mono
          />
        </Field>
      </Modal>

      <ConfirmDialog
        open={!!confirmDeleteSlug}
        title="Delete department"
        message={`Delete "${depts.find((d) => d.slug === confirmDeleteSlug)?.name ?? confirmDeleteSlug}"? This cannot be undone.`}
        confirmLabel="Delete"
        destructive
        busy={deleteBusy}
        onCancel={() => setConfirmDeleteSlug(null)}
        onConfirm={() => confirmDeleteSlug && handleDelete(confirmDeleteSlug)}
      />
    </div>
  );
}
