"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  ChevronRight,
  Hash,
  GripVertical,
  Search,
  Building2,
  ExternalLink,
} from "lucide-react";
import Button from "@/components/ui/Button";
import Pill from "@/components/ui/Pill";
import EmptyState from "@/components/ui/EmptyState";
import SectionHeader from "@/components/ui/SectionHeader";
import type { DepartmentItem, DeptStatsItem, OrgItem } from "@/lib/types";

const fmtDate = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric" });
function fmtNum(n: number) { return n.toLocaleString("en-US"); }
function fmtPct(n: number) { return (n * 100).toFixed(1) + "%"; }

const COL = "1fr 200px 160px 140px 110px";

interface Props {
  orgs: OrgItem[];
  allDepts: DepartmentItem[];
  statsMap: Record<string, DeptStatsItem>;
  error: string | null;
}

export default function OrganizationsClient({ orgs, allDepts, statsMap, error }: Props) {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    orgs.forEach((o, i) => { init[o.slug] = i < 2; });
    return init;
  });
  const [drag, setDrag] = useState<{ kind: "org" | "dept"; slug: string; fromOrg?: string } | null>(null);
  const [dropTarget, setDropTarget] = useState<{ slug: string; pos: "before" | "after" | "into" } | null>(null);
  const [orgOrder, setOrgOrder] = useState(() => orgs.map((o) => o.slug));

  const deptsByOrg: Record<string, DepartmentItem[]> = {};
  for (const d of allDepts) {
    (deptsByOrg[d.org_slug] ??= []).push(d);
  }

  const toggle = (slug: string) => setExpanded((e) => ({ ...e, [slug]: !e[slug] }));

  const searchLower = search.toLowerCase();
  const visibleSlugs = search.trim()
    ? orgOrder.filter((slug) => {
        const org = orgs.find((o) => o.slug === slug);
        if (!org) return false;
        if (org.name.toLowerCase().includes(searchLower) || org.slug.toLowerCase().includes(searchLower)) return true;
        return (deptsByOrg[slug] ?? []).some((d) => d.slug.includes(searchLower));
      })
    : orgOrder;

  function onOrgDragStart(slug: string) { setDrag({ kind: "org", slug }); }
  function onOrgDragOver(e: React.DragEvent, slug: string) {
    if (!drag || drag.kind !== "org") return;
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const pos = e.clientY - rect.top < rect.height / 2 ? "before" : "after";
    setDropTarget({ slug, pos });
  }
  function onDeptDragStart(deptSlug: string, fromOrg: string) { setDrag({ kind: "dept", slug: deptSlug, fromOrg }); }
  function onDeptDragOver(e: React.DragEvent, deptSlug: string) {
    if (!drag || drag.kind !== "dept") return;
    e.preventDefault();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const pos = e.clientY - rect.top < rect.height / 2 ? "before" : "after";
    setDropTarget({ slug: deptSlug, pos });
  }
  function onOrgDropZone(e: React.DragEvent, orgSlug: string) {
    if (!drag || drag.kind !== "dept") return;
    e.preventDefault();
    setDropTarget({ slug: orgSlug, pos: "into" });
  }
  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    if (!drag || !dropTarget) { setDrag(null); setDropTarget(null); return; }
    if (drag.kind === "org" && (dropTarget.pos === "before" || dropTarget.pos === "after")) {
      if (drag.slug !== dropTarget.slug) {
        const next = orgOrder.filter((s) => s !== drag.slug);
        const idx = next.indexOf(dropTarget.slug);
        const at = dropTarget.pos === "after" ? idx + 1 : idx;
        next.splice(at, 0, drag.slug);
        setOrgOrder(next);
      }
    }
    setDrag(null);
    setDropTarget(null);
  }

  return (
    <div className="ds-page">
      <SectionHeader
        title="Organizations"
        subtitle="Drag to reorder. Each org owns a cache namespace; each department is a partition inside that namespace."
        action={
          <div style={{ display: "flex", gap: 8 }}>
            <Button size="sm" onClick={() => { const all: Record<string, boolean> = {}; orgs.forEach((o) => (all[o.slug] = true)); setExpanded(all); }}>
              Expand all
            </Button>
            <Button size="sm" onClick={() => setExpanded({})}>Collapse all</Button>
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
              placeholder="Filter organizations and departments…"
              style={{ background: "none", border: "none", color: "var(--fg)", flex: 1, fontFamily: "var(--font-mono)", fontSize: 11, outline: "none" }}
            />
          </label>
          <span style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 11, marginLeft: "auto" }}>
            {visibleSlugs.length} org{visibleSlugs.length !== 1 ? "s" : ""} · {allDepts.length} departments
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
            icon={Building2}
            title="No organizations"
            description={search ? `No results for "${search}"` : "Create one with dejaq-admin org create"}
          />
        ) : (
          <div onDrop={onDrop} onDragEnd={() => { setDrag(null); setDropTarget(null); }}>
            {visibleSlugs.map((slug, oi) => {
              const org = orgs.find((o) => o.slug === slug);
              if (!org) return null;
              const rows = deptsByOrg[slug] ?? [];
              const isOpen = !!expanded[slug];
              const orgHits = rows.reduce((a, d) => a + (statsMap[`${slug}::${d.slug}`]?.hits ?? 0), 0);
              const orgMisses = rows.reduce((a, d) => a + (statsMap[`${slug}::${d.slug}`]?.misses ?? 0), 0);
              const orgTotal = orgHits + orgMisses;
              const orgRate = orgTotal ? orgHits / orgTotal : 0;
              const isDragging = drag?.kind === "org" && drag.slug === slug;
              const dropBefore = dropTarget?.slug === slug && dropTarget.pos === "before";
              const dropAfter = dropTarget?.slug === slug && dropTarget.pos === "after";
              const dropInto = dropTarget?.slug === slug && dropTarget.pos === "into";

              return (
                <div key={slug}>
                  {dropBefore && <div style={{ height: 2, background: "var(--accent)", margin: "0 12px" }} />}
                  <div
                    draggable
                    onDragStart={() => onOrgDragStart(slug)}
                    onDragOver={(e) => {
                      if (drag?.kind === "dept") { onOrgDropZone(e, slug); return; }
                      onOrgDragOver(e, slug);
                    }}
                    onDragLeave={() => setDropTarget(null)}
                    onClick={() => toggle(slug)}
                    style={{
                      display: "grid",
                      gridTemplateColumns: COL,
                      gap: 12,
                      padding: "10px 12px",
                      alignItems: "center",
                      borderBottom: isOpen || oi < visibleSlugs.length - 1 ? "1px solid var(--border)" : "none",
                      background: dropInto ? "var(--accent-bg)" : isDragging ? "var(--bg-3)" : "transparent",
                      opacity: isDragging ? 0.5 : 1,
                      cursor: "grab",
                      borderLeft: dropInto ? "2px solid var(--accent)" : "2px solid transparent",
                      userSelect: "none",
                      transition: "background 0.1s",
                    }}
                  >
                    {/* Name col */}
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
                        {org.name.slice(0, 1).toUpperCase()}
                      </span>
                      <span style={{ fontWeight: 500 }}>{org.name}</span>
                      <span style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 11 }}>{org.slug}</span>
                      <span style={{ background: "var(--bg-3)", border: "1px solid var(--border-2)", borderRadius: 3, color: "var(--fg-dim)", fontFamily: "var(--font-mono)", fontSize: 10, padding: "1px 6px" }}>
                        {rows.length} dept{rows.length !== 1 ? "s" : ""}
                      </span>
                    </div>
                    {/* Cache stats */}
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-dim)" }}>
                      {rows.length ? (
                        <>
                          <span style={{ color: "var(--accent)" }}>{fmtNum(orgHits)}</span>
                          {" / "}
                          <span style={{ color: "var(--amber)" }}>{fmtNum(orgMisses)}</span>
                        </>
                      ) : (
                        <span style={{ color: "var(--fg-dimmer)" }}>—</span>
                      )}
                    </div>
                    {/* Hit rate */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, minWidth: 48, color: orgRate >= 0.7 ? "var(--accent)" : "var(--fg)" }}>
                        {orgTotal ? fmtPct(orgRate) : "—"}
                      </span>
                      <div style={{ height: 4, background: "var(--bg-3)", borderRadius: 2, overflow: "hidden", width: 70, flexShrink: 0 }}>
                        <div style={{ height: "100%", background: "var(--accent)", width: (orgRate * 100) + "%" }} />
                      </div>
                    </div>
                    {/* Created */}
                    <div className="ds-dim" style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
                      {fmtDate.format(new Date(org.created_at))}
                    </div>
                    {/* Actions */}
                    <div style={{ display: "flex", gap: 4, justifyContent: "flex-end" }} onClick={(e) => e.stopPropagation()}>
                      <Button
                        size="sm"
                        onClick={() => router.push(`/dashboard/departments?org=${org.slug}`)}
                        style={{ gap: 4 }}
                      >
                        Open <ExternalLink size={10} />
                      </Button>
                    </div>
                  </div>
                  {dropAfter && !isOpen && <div style={{ height: 2, background: "var(--accent)", margin: "0 12px" }} />}

                  {/* Dept sub-rows */}
                  {isOpen && (
                    <div style={{ background: "var(--bg)", borderBottom: oi < visibleSlugs.length - 1 ? "1px solid var(--border)" : "none" }}>
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
                                  onClick={() => router.push(`/dashboard/departments?org=${slug}`)}
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
    </div>
  );
}
