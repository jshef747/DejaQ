"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Hash, RefreshCw, Download, Inbox } from "lucide-react";
import Button from "@/components/ui/Button";
import SectionHeader from "@/components/ui/SectionHeader";
import EmptyState from "@/components/ui/EmptyState";
import type { DeptStatsReport, DeptStatsItem } from "@/lib/types";

interface AnalyticsClientProps {
  orgSlug: string;
  range: string;
  deptStats: DeptStatsReport;
  error: string | null;
}

const fmtNum = (n: number) => n.toLocaleString();
const fmtPct = (n: number) => (n * 100).toFixed(1) + "%";

const RANGES = ["24h", "7d", "30d"] as const;
const RANGE_LABELS: Record<string, string> = {
  "24h": "last 24 hours",
  "7d": "last 7 days",
  "30d": "last 30 days",
};

function LineChart({ data1, data2, labels }: { data1: number[]; data2: number[]; labels: string[] }) {
  if (data1.length === 0) return null;

  const W = 900, H = 240, P = { t: 16, r: 16, b: 28, l: 40 };
  const max = Math.max(...data1) * 1.1 || 1;
  const xStep = (W - P.l - P.r) / Math.max(data1.length - 1, 1);
  const y = (v: number) => H - P.b - (v / max) * (H - P.t - P.b);
  const path = (data: number[]) => data.map((v, i) => `${i === 0 ? "M" : "L"} ${P.l + i * xStep} ${y(v)}`).join(" ");
  const area = (data: number[]) =>
    `${path(data)} L ${P.l + (data.length - 1) * xStep} ${H - P.b} L ${P.l} ${H - P.b} Z`;

  const [tooltip, setTooltip] = useState<{ i: number; x: number; y: number } | null>(null);

  return (
    <div style={{ position: "relative" }}>
      <svg
        aria-label={`Request counts by department over ${labels.length} data points`}
        role="img"
        style={{ display: "block", width: "100%", height: "auto" }}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        onMouseLeave={() => setTooltip(null)}
      >
        <defs>
          <linearGradient id="reqGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f97316" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#f97316" stopOpacity="0" />
          </linearGradient>
        </defs>
        {Array.from({ length: 5 }).map((_, i) => {
          const yy = P.t + (i * (H - P.t - P.b)) / 4;
          const val = Math.round(max - (i * max) / 4);
          return (
            <g key={i}>
              <line x1={P.l} x2={W - P.r} y1={yy} y2={yy} stroke="#262626" strokeDasharray="2 3" />
              <text x={P.l - 8} y={yy + 3} fill="#6e6e6e" fontSize="10" fontFamily="JetBrains Mono, monospace" textAnchor="end">
                {val >= 1000 ? (val / 1000).toFixed(1) + "k" : val}
              </text>
            </g>
          );
        })}
        {labels.map((l, i) =>
          (i % Math.max(Math.ceil(labels.length / 6), 1) === 0 || i === labels.length - 1) && (
            <text key={i} x={P.l + i * xStep} y={H - 8} fill="#6e6e6e" fontSize="10" fontFamily="JetBrains Mono, monospace" textAnchor="middle">
              {l.length > 10 ? l.slice(0, 9) + "…" : l}
            </text>
          )
        )}
        <path d={area(data1)} fill="url(#reqGrad)" />
        <path d={path(data1)} fill="none" stroke="#f97316" strokeWidth="1.6" />
        <path d={path(data2)} fill="none" stroke="#f59e0b" strokeWidth="1.2" strokeDasharray="3 3" opacity="0.7" />
        {/* Interactive hit-targets */}
        {data1.map((v, i) => (
          <circle
            key={i}
            cx={P.l + i * xStep}
            cy={y(v)}
            r={tooltip?.i === i ? 5 : 8}
            fill="transparent"
            onMouseEnter={() => setTooltip({ i, x: P.l + i * xStep, y: y(v) })}
          />
        ))}
        {tooltip !== null && (
          <circle cx={P.l + tooltip.i * xStep} cy={y(data1[tooltip.i])} r={3.5} fill="#f97316" stroke="#1c1c1c" strokeWidth="2" />
        )}
      </svg>

      {/* Tooltip */}
      {tooltip !== null && (
        <div style={{
          position: "absolute",
          top: 0, left: 0, pointerEvents: "none",
          transform: `translate(${(tooltip.x / W) * 100}%, 16px)`,
          background: "#1e1e1e", border: "1px solid var(--border-2)",
          borderRadius: 4, padding: "5px 8px", fontSize: 11,
          fontFamily: "var(--font-mono)", color: "var(--fg)",
          boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
          whiteSpace: "nowrap",
        }}>
          <div style={{ color: "var(--fg-dimmer)", marginBottom: 2 }}>{labels[tooltip.i]}</div>
          <div><span style={{ color: "var(--accent)" }}>{fmtNum(data1[tooltip.i])}</span> req · <span style={{ color: "var(--amber)" }}>{fmtNum(data2[tooltip.i])}</span> hits</div>
        </div>
      )}

      <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 11, color: "var(--fg-dim)" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 10, height: 2, background: "#f97316", display: "inline-block" }} />
          Total requests
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 10, height: 2, background: "repeating-linear-gradient(90deg, #f59e0b 0 3px, transparent 3px 6px)", display: "inline-block" }} />
          Cache hits
        </span>
      </div>
    </div>
  );
}

type SortCol = "requests" | "hit_rate" | "hits" | "misses";
type SortDir = "asc" | "desc";

function hbarFill(pct: number, color = "var(--accent)"): React.CSSProperties {
  return { height: "100%", width: `${Math.min(pct * 100, 100)}%`, background: color, transition: "width 0.3s" };
}

function hitRateColor(rate: number) {
  if (rate >= 0.8) return "var(--accent)";
  if (rate >= 0.6) return "var(--fg)";
  return "var(--amber)";
}

export default function AnalyticsClient({ orgSlug, range, deptStats, error }: AnalyticsClientProps) {
  const router = useRouter();
  const [sortCol, setSortCol] = useState<SortCol>("requests");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [selectedDept, setSelectedDept] = useState<string | null>(null);

  const items: DeptStatsItem[] = deptStats.items;
  const rangeLabel = RANGE_LABELS[range] ?? "last 7 days";
  const activeDept = selectedDept ? items.find((d) => d.department === selectedDept) ?? null : null;
  const total = activeDept ?? deptStats.total;
  const totalReqs = items.reduce((a, d) => a + d.requests, 0);

  const sortedItems = [...items].sort((a, b) => {
    const va = a[sortCol] as number;
    const vb = b[sortCol] as number;
    return sortDir === "desc" ? vb - va : va - vb;
  });

  function toggleSort(col: SortCol) {
    if (sortCol === col) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortCol(col); setSortDir("desc"); }
  }

  function sortIndicator(col: SortCol) {
    if (sortCol !== col) return null;
    return <span style={{ marginLeft: 4, color: "var(--accent)" }}>{sortDir === "desc" ? "↓" : "↑"}</span>;
  }

  const easyTotal = total.easy_count + total.hard_count;
  const easyPct = easyTotal > 0 ? total.easy_count / easyTotal : 0;
  const hardPct = easyTotal > 0 ? total.hard_count / easyTotal : 0;
  const tokensSavedM = (total.est_tokens_saved / 1e6).toFixed(2);
  const estCost = (total.est_tokens_saved * 0.000003).toFixed(2);

  const thStyle: React.CSSProperties = {
    textAlign: "left", fontWeight: 500, fontSize: 10.5,
    textTransform: "uppercase", letterSpacing: "0.06em",
    color: "var(--fg-dimmer)", padding: "9px 12px",
    background: "#1d1d1d", borderBottom: "1px solid var(--border)",
    whiteSpace: "nowrap", cursor: "pointer", userSelect: "none",
  };
  const COL = "1fr 180px 100px 100px 100px 160px";

  function exportCSV() {
    const rows = [
      ["department", "requests", "hits", "misses", "hit_rate", "avg_latency_ms"],
      ...sortedItems.map((d) => [d.department, d.requests, d.hits, d.misses, (d.hit_rate * 100).toFixed(1) + "%", d.avg_latency_ms?.toFixed(0) ?? ""]),
    ];
    const csv = rows.map((r) => r.join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `dejaq-analytics-${orgSlug}-${range}.csv`;
    a.click();
  }

  return (
    <div className="ds-page" style={{ overflowY: "auto" }}>
      <SectionHeader
        title="Analytics"
        subtitle={`Cache performance for ${orgSlug} · ${rangeLabel}`}
        action={
          <>
            <div style={{ display: "flex", gap: 4 }}>
              {RANGES.map((r) => (
                <Button key={r} size="sm"
                  style={{ background: range === r ? "var(--bg-3)" : "var(--bg-2)", color: range === r ? "var(--fg)" : "var(--fg-dim)", borderColor: range === r ? "var(--border-2)" : "var(--border)" }}
                  onClick={() => router.push(`/dashboard/analytics?org=${orgSlug}&range=${r}`)}>
                  {r}
                </Button>
              ))}
            </div>
            <Button onClick={() => router.push(`/dashboard/analytics?org=${orgSlug}&range=${range}`)}>
              <RefreshCw size={11} />Refresh
            </Button>
            <Button onClick={exportCSV}>
              <Download size={11} />CSV
            </Button>
          </>
        }
      />

      {error && (
        <div style={{ background: "var(--red-bg)", border: "1px solid var(--red-border)", borderRadius: 6, color: "var(--red)", fontSize: 12, marginBottom: 16, padding: "10px 14px" }}>
          {error}
        </div>
      )}

      {selectedDept && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16, padding: "8px 12px", background: "var(--accent-bg)", border: "1px solid var(--accent-border)", borderRadius: 6, fontSize: 12 }}>
          <span className="ds-dim">Filtered to:</span>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--accent)", fontWeight: 500 }}>{selectedDept}</span>
          <button onClick={() => setSelectedDept(null)} style={{ marginLeft: "auto", background: "none", border: "none", color: "var(--fg-dim)", cursor: "pointer", fontSize: 11, padding: "2px 6px", borderRadius: 4, fontFamily: "inherit" }}>
            ✕ clear
          </button>
        </div>
      )}

      {/* KPI metric grid */}
      <div className="ds-metric-grid">
        <div className="ds-metric">
          <div className="ds-metric-label">Total requests</div>
          <div className="ds-metric-value" style={{ fontFamily: "var(--font-mono)" }}>{fmtNum(total.requests)}</div>
          <div className="ds-metric-delta">{rangeLabel}</div>
        </div>
        <div className="ds-metric">
          <div className="ds-metric-label"><span className="ds-pill-dot" style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--accent)", display: "inline-block", marginRight: 6 }} />Cache hit rate</div>
          <div className="ds-metric-value" style={{ fontFamily: "var(--font-mono)", color: "var(--accent)" }}>{fmtPct(total.hit_rate)}</div>
          <div className="ds-metric-delta" style={{ color: "var(--green)" }}>{total.hits} hits · {total.misses} misses</div>
        </div>
        <div className="ds-metric">
          <div className="ds-metric-label">Avg latency</div>
          <div className="ds-metric-value" style={{ fontFamily: "var(--font-mono)" }}>
            {total.avg_latency_ms != null ? total.avg_latency_ms.toFixed(0) : "—"}
            <span style={{ fontSize: 14, color: "var(--fg-dim)", fontWeight: 400, marginLeft: 4 }}>ms</span>
          </div>
          <div className="ds-metric-delta">all requests</div>
        </div>
        <div className="ds-metric">
          <div className="ds-metric-label">Tokens saved (est.)</div>
          <div className="ds-metric-value" style={{ fontFamily: "var(--font-mono)" }}>{tokensSavedM}M</div>
          <div className="ds-metric-delta up">≈ ${estCost} in provider cost</div>
        </div>
      </div>

      {/* Chart + routing */}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12, marginBottom: 20 }}>
        <div className="ds-card">
          <div className="ds-card-header">
            <div>
              <p className="ds-card-title">Requests by department</p>
              <p className="ds-card-sub">One point per department · {rangeLabel}</p>
            </div>
          </div>
          <div className="ds-card-body">
            {items.length > 0 ? (
              <LineChart
                data1={(activeDept ? [activeDept] : items).map((d) => d.requests)}
                data2={(activeDept ? [activeDept] : items).map((d) => d.hits)}
                labels={(activeDept ? [activeDept] : items).map((d) => d.department)}
              />
            ) : (
              <div style={{ height: 240, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                No data yet
              </div>
            )}
          </div>
        </div>

        <div className="ds-card">
          <div className="ds-card-header">
            <p className="ds-card-title">Query routing</p>
          </div>
          <div>
            {easyTotal === 0 ? (
              <div style={{ padding: "20px 16px", color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: 12, textAlign: "center" }}>No routing data yet</div>
            ) : (
              [
                { label: "local · easy",    count: total.easy_count, pct: easyPct, color: "var(--accent)" },
                { label: "external · hard", count: total.hard_count, pct: hardPct, color: "var(--amber)" },
              ].map((row, i, arr) => (
                <div key={row.label} style={{ padding: "11px 16px", borderBottom: i < arr.length - 1 ? "1px solid var(--border)" : "none" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 12 }}>
                    <span style={{ fontFamily: "var(--font-mono)" }}>{row.label}</span>
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--fg-dim)" }}>{(row.pct * 100).toFixed(0)}% · {fmtNum(row.count)}</span>
                  </div>
                  <div className="ds-hbar"><div style={hbarFill(row.pct, row.color)} /></div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Department table */}
      <div className="ds-card">
        <div className="ds-card-header">
          <div>
            <p className="ds-card-title">Department breakdown</p>
            <p className="ds-card-sub">Per-department cache performance</p>
          </div>
          <Button size="sm" onClick={exportCSV}><Download size={11} />CSV</Button>
        </div>

        {items.length === 0 ? (
          <EmptyState icon={Inbox} title="No data yet" description="Send a request through the API to see analytics here." />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <div style={{ display: "grid", gridTemplateColumns: COL }}>
              {["Department", "Hit rate", "Hits", "Misses", "Requests", "Share"].map((col, i) => (
                <div key={col} style={thStyle}
                  onClick={() => ["hit_rate", "hits", "misses", "requests"].includes(["hit_rate", "hits", "misses", "requests"][i - 1]) ? toggleSort(["hit_rate", "hits", "misses", "requests"][i - 1] as SortCol) : undefined}
                >
                  {col}{i > 0 && sortIndicator(["hit_rate", "hits", "misses", "requests", "requests"][i - 1] as SortCol)}
                </div>
              ))}
            </div>

            {sortedItems.map((d, i) => {
              const share = totalReqs > 0 ? d.requests / totalReqs : 0;
              return (
                <div key={d.department}
                  style={{
                    display: "grid", gridTemplateColumns: COL, gap: 0,
                    padding: "10px 12px",
                    borderBottom: i < sortedItems.length - 1 ? "1px solid var(--border)" : "none",
                    cursor: "pointer", transition: "background var(--t-fast)",
                    background: selectedDept === d.department ? "var(--accent-bg)" : undefined,
                    borderLeft: selectedDept === d.department ? "2px solid var(--accent)" : "2px solid transparent",
                  }}
                  onMouseEnter={(e) => { if (selectedDept !== d.department) (e.currentTarget as HTMLDivElement).style.background = "#202020"; }}
                  onMouseLeave={(e) => { if (selectedDept !== d.department) (e.currentTarget as HTMLDivElement).style.background = ""; }}
                  onClick={() => setSelectedDept((prev) => prev === d.department ? null : d.department)}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Hash size={12} style={{ color: "var(--fg-dimmer)", flexShrink: 0 }} />
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{d.department}</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, minWidth: 48, color: hitRateColor(d.hit_rate) }}>{fmtPct(d.hit_rate)}</span>
                    <div className="ds-hbar" style={{ width: 80 }}><div style={hbarFill(d.hit_rate)} /></div>
                  </div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent)", display: "flex", alignItems: "center" }}>{fmtNum(d.hits)}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--amber)", display: "flex", alignItems: "center" }}>{fmtNum(d.misses)}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, display: "flex", alignItems: "center" }}>{fmtNum(d.requests)}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--fg-dim)", minWidth: 48 }}>{fmtPct(share)}</span>
                    <div className="ds-hbar" style={{ width: 80 }}><div style={hbarFill(share, "var(--fg-dimmer)")} /></div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
