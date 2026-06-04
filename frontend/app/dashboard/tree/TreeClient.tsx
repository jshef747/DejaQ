"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ChevronRight,
  ChevronDown,
  Building2,
  Hash,
  GitBranch,
  ExternalLink,
} from "lucide-react";
import Button from "@/components/ui/Button";
import Pill from "@/components/ui/Pill";
import EmptyState from "@/components/ui/EmptyState";
import SectionHeader from "@/components/ui/SectionHeader";
import type { DepartmentItem, DeptStatsItem, WorkspaceItem } from "@/lib/types";

function fmtNum(n: number) { return n.toLocaleString("en-US"); }
function fmtPct(n: number) { return (n * 100).toFixed(1) + "%"; }

interface Props {
  workspaces: WorkspaceItem[];
  allDepts: DepartmentItem[];
  statsMap: Record<string, DeptStatsItem>;
  error: string | null;
}

export default function TreeClient({ workspaces, allDepts, statsMap, error }: Props) {
  const router = useRouter();
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const deptsByWorkspace: Record<string, DepartmentItem[]> = {};
  for (const d of allDepts) {
    (deptsByWorkspace[d.workspace_slug] ??= []).push(d);
  }

  function toggle(slug: string) {
    setCollapsed((c) => ({ ...c, [slug]: !c[slug] }));
  }

  function expandAll() { setCollapsed({}); }
  function collapseAll() {
    const all: Record<string, boolean> = {};
    workspaces.forEach((w) => { all[w.slug] = true; });
    setCollapsed(all);
  }

  const totalWorkspaces = workspaces.length;
  const totalDepts = allDepts.length;
  const totalHits = allDepts.reduce((a, d) => a + (statsMap[`${d.org_slug}::${d.slug}`]?.hits ?? 0), 0);
  const totalMisses = allDepts.reduce((a, d) => a + (statsMap[`${d.org_slug}::${d.slug}`]?.misses ?? 0), 0);
  const totalReqs = totalHits + totalMisses;
  const overallRate = totalReqs ? totalHits / totalReqs : 0;

  return (
    <div className="ds-page">
      <SectionHeader
        title="Org Tree"
        subtitle="Collapsible view of the full organization → department hierarchy."
        action={
          <div style={{ display: "flex", gap: 8 }}>
            <Button size="sm" onClick={expandAll}>Expand all</Button>
            <Button size="sm" onClick={collapseAll}>Collapse all</Button>
          </div>
        }
      />

      {/* Global summary strip */}
      <div className="ds-metric-grid" style={{ marginBottom: 20 }}>
        {[
          { label: "Workspaces", value: totalWorkspaces.toString() },
          { label: "Departments", value: totalDepts.toString() },
          { label: "Overall hit rate", value: totalReqs ? fmtPct(overallRate) : "—" },
          { label: "Total requests", value: fmtNum(totalReqs) },
        ].map((m) => (
          <div key={m.label} className="ds-metric">
            <div className="ds-metric-label">{m.label}</div>
            <div className="ds-metric-value" style={{ fontFamily: "var(--font-mono)" }}>{m.value}</div>
          </div>
        ))}
      </div>

      {error && (
        <div className="ds-pill ds-pill-err" style={{ marginBottom: 16, padding: "8px 12px", borderRadius: 5, fontSize: 12 }}>
          {error}
        </div>
      )}

      {workspaces.length === 0 && !error ? (
        <div className="ds-table-wrap">
          <EmptyState
            icon={GitBranch}
            title="No workspaces"
            description="Create one with dejaq-admin workspace create"
          />
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {workspaces.map((ws) => {
            const depts = deptsByWorkspace[ws.slug] ?? [];
            const isCollapsed = !!collapsed[ws.slug];
            const wsHits = depts.reduce((a, d) => a + (statsMap[`${ws.slug}::${d.slug}`]?.hits ?? 0), 0);
            const wsMisses = depts.reduce((a, d) => a + (statsMap[`${ws.slug}::${d.slug}`]?.misses ?? 0), 0);
            const wsTotal = wsHits + wsMisses;
            const wsRate = wsTotal ? wsHits / wsTotal : 0;

            return (
              <div
                key={ws.slug}
                style={{ background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" }}
              >
                {/* Workspace row */}
                <div
                  onClick={() => toggle(ws.slug)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "12px 16px",
                    cursor: "pointer",
                    userSelect: "none",
                    background: "var(--bg-2)",
                    borderBottom: isCollapsed ? "none" : "1px solid var(--border)",
                    transition: "background 0.1s",
                  }}
                >
                  {isCollapsed
                    ? <ChevronRight size={14} style={{ color: "var(--fg-dim)", flexShrink: 0 }} />
                    : <ChevronDown size={14} style={{ color: "var(--accent)", flexShrink: 0 }} />
                  }
                  <div style={{
                    width: 24, height: 24, display: "grid", placeItems: "center",
                    background: "var(--accent-bg)", border: "1px solid var(--accent-border)",
                    borderRadius: 5, color: "var(--accent)", fontFamily: "var(--font-mono)",
                    fontSize: 11, fontWeight: 700, flexShrink: 0,
                  }}>
                    {ws.name.slice(0, 1).toUpperCase()}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontWeight: 600, fontSize: 14 }}>{ws.name}</span>
                      <span style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 11 }}>{ws.slug}</span>
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
                    {wsTotal > 0 && (
                      <>
                        <Pill variant="hit">{fmtPct(wsRate)}</Pill>
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--fg-dim)" }}>
                          <span style={{ color: "var(--accent)" }}>{fmtNum(wsHits)}</span>
                          {" / "}
                          <span style={{ color: "var(--amber)" }}>{fmtNum(wsMisses)}</span>
                        </span>
                      </>
                    )}
                    <span style={{ background: "var(--bg-3)", border: "1px solid var(--border-2)", borderRadius: 3, color: "var(--fg-dim)", fontFamily: "var(--font-mono)", fontSize: 10, padding: "2px 7px" }}>
                      {depts.length} dept{depts.length !== 1 ? "s" : ""}
                    </span>
                    <div onClick={(e) => e.stopPropagation()}>
                      <Button size="sm" onClick={() => router.push(`/dashboard/departments?workspace=${ws.slug}`)} style={{ gap: 4 }}>
                        Manage <ExternalLink size={10} />
                      </Button>
                    </div>
                  </div>
                </div>

                {/* Dept children */}
                {!isCollapsed && (
                  <div style={{ background: "var(--bg)" }}>
                    {depts.length === 0 ? (
                      <div style={{ padding: "12px 16px 12px 52px", color: "var(--fg-dimmer)", fontSize: 12, fontFamily: "var(--font-mono)" }}>
                        no departments yet
                      </div>
                    ) : (
                      depts.map((dept, di) => {
                        const stats = statsMap[`${ws.slug}::${dept.slug}`];
                        const hits = stats?.hits ?? 0;
                        const misses = stats?.misses ?? 0;
                        const total = hits + misses;
                        const rate = total ? hits / total : 0;
                        return (
                          <div
                            key={dept.id}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 12,
                              padding: "9px 16px 9px 52px",
                              borderBottom: di < depts.length - 1 ? "1px solid var(--border)" : "none",
                            }}
                          >
                            <span style={{ color: "var(--fg-dimmer)", fontSize: 11 }}>└</span>
                            <Hash size={12} style={{ color: "var(--accent)", flexShrink: 0 }} />
                            <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500, fontSize: 12, flex: 1, minWidth: 0 }}>
                              {dept.slug}
                              {dept.name && dept.name !== dept.slug && (
                                <span style={{ color: "var(--fg-dimmer)", fontWeight: 400, marginLeft: 8 }}>{dept.name}</span>
                              )}
                            </span>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                              {total > 0 ? (
                                <>
                                  <Pill variant="hit">HIT {fmtNum(hits)}</Pill>
                                  <Pill variant="miss">MISS {fmtNum(misses)}</Pill>
                                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, minWidth: 48, color: rate >= 0.7 ? "var(--accent)" : "var(--fg-dim)" }}>
                                    {fmtPct(rate)}
                                  </span>
                                  <div style={{ height: 4, background: "var(--bg-3)", borderRadius: 2, overflow: "hidden", width: 60 }}>
                                    <div style={{ height: "100%", background: "var(--accent)", width: (rate * 100) + "%" }} />
                                  </div>
                                </>
                              ) : (
                                <span style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 11 }}>no traffic</span>
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
