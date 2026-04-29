"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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

function HashIcon() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      style={{ flexShrink: 0, color: "var(--fg-dimmer)" }}
    >
      <line x1="2" y1="4" x2="10" y2="4" />
      <line x1="2" y1="8" x2="10" y2="8" />
      <line x1="4.5" y1="1.5" x2="3.5" y2="10.5" />
      <line x1="8.5" y1="1.5" x2="7.5" y2="10.5" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9.5 2A5 5 0 1 0 10 5.5" />
      <polyline points="7 0 9.5 2 7.5 4.5" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="5.5" y1="1" x2="5.5" y2="8" />
      <polyline points="2.5 5.5 5.5 8 8.5 5.5" />
      <line x1="1" y1="10" x2="10" y2="10" />
    </svg>
  );
}

function LineChart({
  data1,
  data2,
  labels,
}: {
  data1: number[];
  data2: number[];
  labels: string[];
}) {
  if (data1.length === 0) return null;

  const W = 900,
    H = 240,
    P = { t: 16, r: 16, b: 28, l: 40 };
  const max = Math.max(...data1) * 1.1 || 1;
  const xStep = (W - P.l - P.r) / Math.max(data1.length - 1, 1);
  const y = (v: number) => H - P.b - (v / max) * (H - P.t - P.b);
  const path = (data: number[]) =>
    data.map((v, i) => `${i === 0 ? "M" : "L"} ${P.l + i * xStep} ${y(v)}`).join(" ");
  const area = (data: number[]) =>
    `${path(data)} L ${P.l + (data.length - 1) * xStep} ${H - P.b} L ${P.l} ${H - P.b} Z`;

  const yTicks = 4;

  return (
    <div>
      <svg
        style={{ display: "block", width: "100%", height: "auto" }}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id="reqGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f97316" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#f97316" stopOpacity="0" />
          </linearGradient>
        </defs>
        {Array.from({ length: yTicks + 1 }).map((_, i) => {
          const yy = P.t + (i * (H - P.t - P.b)) / yTicks;
          const val = Math.round(max - (i * max) / yTicks);
          return (
            <g key={i}>
              <line
                x1={P.l}
                x2={W - P.r}
                y1={yy}
                y2={yy}
                stroke="#262626"
                strokeDasharray="2 3"
              />
              <text
                x={P.l - 8}
                y={yy + 3}
                fill="#6e6e6e"
                fontSize="10"
                fontFamily="JetBrains Mono, monospace"
                textAnchor="end"
              >
                {val >= 1000 ? (val / 1000).toFixed(1) + "k" : val}
              </text>
            </g>
          );
        })}
        {labels.map(
          (l, i) =>
            (i % Math.max(Math.ceil(labels.length / 6), 1) === 0 ||
              i === labels.length - 1) && (
              <text
                key={i}
                x={P.l + i * xStep}
                y={H - 8}
                fill="#6e6e6e"
                fontSize="10"
                fontFamily="JetBrains Mono, monospace"
                textAnchor="middle"
              >
                {l.length > 10 ? l.slice(0, 9) + "…" : l}
              </text>
            ),
        )}
        <path d={area(data1)} fill="url(#reqGrad)" />
        <path d={path(data1)} fill="none" stroke="#f97316" strokeWidth="1.6" />
        <path
          d={path(data2)}
          fill="none"
          stroke="#f59e0b"
          strokeWidth="1.2"
          strokeDasharray="3 3"
          opacity="0.7"
        />
        <circle
          cx={P.l + (data1.length - 1) * xStep}
          cy={y(data1[data1.length - 1])}
          r="3.5"
          fill="#f97316"
          stroke="#1c1c1c"
          strokeWidth="2"
        />
      </svg>
      <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 11, color: "var(--fg-dim)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 10, height: 2, background: "#f97316", display: "inline-block" }} />
          <span>Total requests</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              width: 10,
              height: 2,
              background: "repeating-linear-gradient(90deg, #f59e0b 0 3px, transparent 3px 6px)",
              display: "inline-block",
            }}
          />
          <span>Cache hits</span>
        </div>
      </div>
    </div>
  );
}

type SortCol = "requests" | "hit_rate" | "hits" | "misses";
type SortDir = "asc" | "desc";

export default function AnalyticsClient({
  orgSlug,
  range,
  deptStats,
  error,
}: AnalyticsClientProps) {
  const router = useRouter();
  const [sortCol, setSortCol] = useState<SortCol>("requests");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [selectedDept, setSelectedDept] = useState<string | null>(null);

  const items: DeptStatsItem[] = deptStats.items;
  const rangeLabel = RANGE_LABELS[range] ?? "last 7 days";

  const activeDept = selectedDept ? items.find((d) => d.department === selectedDept) ?? null : null;
  const total: DeptStatsItem = activeDept ?? deptStats.total;

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

  const btnBase: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 12px",
    borderRadius: 5,
    border: "1px solid var(--border-2)",
    background: "var(--bg-2)",
    color: "var(--fg)",
    fontSize: 12,
    fontWeight: 500,
    cursor: "pointer",
    fontFamily: "inherit",
    whiteSpace: "nowrap",
  };

  const btnXs: React.CSSProperties = { ...btnBase, padding: "3px 8px", fontSize: 11 };

  const cardStyle: React.CSSProperties = {
    background: "var(--bg-2)",
    border: "1px solid var(--border)",
    borderRadius: 6,
    overflow: "hidden",
  };

  const cardHeaderStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "12px 16px",
    borderBottom: "1px solid var(--border)",
  };

  const hbarContainer: React.CSSProperties = {
    height: 4,
    background: "var(--bg-3)",
    borderRadius: 2,
    overflow: "hidden",
    width: 100,
  };

  function hbarFill(pct: number, color = "var(--accent)"): React.CSSProperties {
    return { height: "100%", width: `${Math.min(pct * 100, 100)}%`, background: color, transition: "width 0.3s" };
  }

  function hitRateColor(rate: number) {
    if (rate >= 0.8) return "var(--accent)";
    if (rate >= 0.6) return "var(--fg)";
    return "var(--amber)";
  }

  function sortIndicator(col: SortCol) {
    if (sortCol !== col) return null;
    return <span style={{ marginLeft: 4, color: "var(--accent)" }}>{sortDir === "desc" ? "↓" : "↑"}</span>;
  }

  const thStyle: React.CSSProperties = {
    textAlign: "left",
    fontWeight: 500,
    fontSize: 10.5,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    color: "var(--fg-dimmer)",
    padding: "9px 12px",
    background: "#1d1d1d",
    borderBottom: "1px solid var(--border)",
    whiteSpace: "nowrap",
    cursor: "pointer",
    userSelect: "none",
  };

  const COL = "1fr 180px 100px 100px 100px 160px";

  const easyTotal = total.easy_count + total.hard_count;
  const easyPct = easyTotal > 0 ? total.easy_count / easyTotal : 0;
  const hardPct = easyTotal > 0 ? total.hard_count / easyTotal : 0;

  const tokensSavedM = (total.est_tokens_saved / 1e6).toFixed(2);
  const estCost = (total.est_tokens_saved * 0.000003).toFixed(2);

  return (
    <div style={{ padding: "24px 28px", flex: 1, overflowY: "auto" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          marginBottom: 20,
          gap: 16,
        }}
      >
        <div>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 600,
              letterSpacing: "-0.02em",
              margin: "0 0 4px",
            }}
          >
            Analytics
          </h1>
          <p style={{ fontSize: 13, color: "var(--fg-dim)", margin: 0 }}>
            Cache performance for{" "}
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--fg)", fontSize: 12 }}>
              {orgSlug}
            </span>{" "}
            · {rangeLabel}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          {/* Range picker */}
          <div style={{ display: "flex", gap: 4 }}>
            {RANGES.map((r) => (
              <button
                key={r}
                style={{
                  ...btnXs,
                  background: range === r ? "var(--bg-3)" : "var(--bg-2)",
                  color: range === r ? "var(--fg)" : "var(--fg-dim)",
                  borderColor: range === r ? "var(--border-2)" : "var(--border)",
                }}
                onClick={() =>
                  router.push(`/dashboard/analytics?org=${orgSlug}&range=${r}`)
                }
              >
                {r}
              </button>
            ))}
          </div>
          <button
            style={btnBase}
            onClick={() =>
              router.push(`/dashboard/analytics?org=${orgSlug}&range=${range}`)
            }
          >
            <RefreshIcon />
            Refresh
          </button>
          <button style={btnBase}>
            <DownloadIcon />
            Export CSV
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            background: "var(--red-bg)",
            border: "1px solid var(--red-border)",
            borderRadius: 6,
            color: "var(--red)",
            fontSize: 12,
            marginBottom: 16,
            padding: "10px 14px",
          }}
        >
          {error}
        </div>
      )}

      {selectedDept && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginBottom: 16,
            padding: "8px 12px",
            background: "var(--accent-bg)",
            border: "1px solid var(--accent-border)",
            borderRadius: 6,
            fontSize: 12,
          }}
        >
          <span style={{ color: "var(--fg-dim)" }}>Filtered to department:</span>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--accent)", fontWeight: 500 }}>
            {selectedDept}
          </span>
          <button
            onClick={() => setSelectedDept(null)}
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              color: "var(--fg-dim)",
              cursor: "pointer",
              fontSize: 11,
              padding: "2px 6px",
              borderRadius: 4,
              fontFamily: "inherit",
            }}
          >
            ✕ clear filter
          </button>
        </div>
      )}

      {/* Metric cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
          marginBottom: 20,
        }}
      >
        {/* Total requests */}
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: 6, padding: "14px 16px" }}>
          <div style={{ fontSize: 11, color: "var(--fg-dim)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Total requests
          </div>
          <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.03em", fontFamily: "var(--font-mono)", marginBottom: 6 }}>
            {fmtNum(total.requests)}
          </div>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--fg-dim)" }}>
            {rangeLabel}
          </div>
        </div>

        {/* Cache hit rate */}
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: 6, padding: "14px 16px" }}>
          <div style={{ fontSize: 11, color: "var(--fg-dim)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "var(--accent)", display: "inline-block" }} />
            Cache hit rate
          </div>
          <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.03em", fontFamily: "var(--font-mono)", marginBottom: 6, color: "var(--accent)" }}>
            {fmtPct(total.hit_rate)}
          </div>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--green)" }}>
            {total.hits} hits · {total.misses} misses
          </div>
        </div>

        {/* Avg latency */}
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: 6, padding: "14px 16px" }}>
          <div style={{ fontSize: 11, color: "var(--fg-dim)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Avg latency
          </div>
          <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.03em", fontFamily: "var(--font-mono)", marginBottom: 6 }}>
            {total.avg_latency_ms != null ? total.avg_latency_ms.toFixed(0) : "—"}
            <span style={{ fontSize: 14, color: "var(--fg-dim)", fontWeight: 400, marginLeft: 4 }}>ms</span>
          </div>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--fg-dim)" }}>
            all requests
          </div>
        </div>

        {/* Tokens saved */}
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: 6, padding: "14px 16px" }}>
          <div style={{ fontSize: 11, color: "var(--fg-dim)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>
            Tokens saved (est.)
          </div>
          <div style={{ fontSize: 26, fontWeight: 600, letterSpacing: "-0.03em", fontFamily: "var(--font-mono)", marginBottom: 6 }}>
            {tokensSavedM}M
          </div>
          <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--green)" }}>
            ≈ ${estCost} in provider cost
          </div>
        </div>
      </div>

      {/* Two-col: chart + routing */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "2fr 1fr",
          gap: 12,
          marginBottom: 20,
        }}
      >
        {/* Chart card */}
        <div style={cardStyle}>
          <div style={cardHeaderStyle}>
            <div>
              <h3 style={{ fontSize: 13, fontWeight: 500, margin: 0 }}>
                Requests by department
              </h3>
              <div style={{ fontSize: 11, color: "var(--fg-dim)", marginTop: 2 }}>
                One point per department · {rangeLabel}
              </div>
            </div>
          </div>
          <div style={{ padding: 16 }}>
            {items.length > 0 ? (
              <LineChart
                data1={(activeDept ? [activeDept] : items).map((d) => d.requests)}
                data2={(activeDept ? [activeDept] : items).map((d) => d.hits)}
                labels={(activeDept ? [activeDept] : items).map((d) => d.department)}
              />
            ) : (
              <div
                style={{
                  height: 240,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--fg-dimmer)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                }}
              >
                No data yet
              </div>
            )}
          </div>
        </div>

        {/* Model routing card */}
        <div style={cardStyle}>
          <div style={cardHeaderStyle}>
            <div>
              <h3 style={{ fontSize: 13, fontWeight: 500, margin: 0 }}>
                Query routing
              </h3>
              <div style={{ fontSize: 11, color: "var(--fg-dim)", marginTop: 2 }}>
                Easy (local) vs hard (external)
              </div>
            </div>
          </div>
          <div style={{ padding: 0 }}>
            {easyTotal === 0 ? (
              <div
                style={{
                  padding: "20px 16px",
                  color: "var(--fg-dimmer)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 12,
                  textAlign: "center",
                }}
              >
                No routing data yet
              </div>
            ) : (
              [
                { label: "local · easy", count: total.easy_count, pct: easyPct, color: "var(--accent)" },
                { label: "external · hard", count: total.hard_count, pct: hardPct, color: "var(--amber)" },
              ].map((row, i, arr) => (
                <div
                  key={row.label}
                  style={{
                    padding: "11px 16px",
                    borderBottom: i < arr.length - 1 ? "1px solid var(--border)" : "none",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      marginBottom: 5,
                      fontSize: 12,
                    }}
                  >
                    <span style={{ fontFamily: "var(--font-mono)" }}>{row.label}</span>
                    <span style={{ fontFamily: "var(--font-mono)", color: "var(--fg-dim)" }}>
                      {(row.pct * 100).toFixed(0)}% · {fmtNum(row.count)}
                    </span>
                  </div>
                  <div style={{ height: 4, background: "var(--bg-3)", borderRadius: 2, overflow: "hidden" }}>
                    <div style={hbarFill(row.pct, row.color)} />
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Department breakdown table */}
      <div style={cardStyle}>
        <div style={cardHeaderStyle}>
          <div>
            <h3 style={{ fontSize: 13, fontWeight: 500, margin: 0 }}>
              Department breakdown
            </h3>
            <div style={{ fontSize: 11, color: "var(--fg-dim)", marginTop: 2 }}>
              Per-department cache performance for{" "}
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{orgSlug}</span>
            </div>
          </div>
          <button style={btnXs}>
            <DownloadIcon />
            CSV
          </button>
        </div>

        {items.length === 0 ? (
          <div
            style={{
              padding: "40px 24px",
              textAlign: "center",
              color: "var(--fg-dim)",
              fontSize: 13,
            }}
          >
            <div style={{ marginBottom: 12, fontSize: 24 }}>📭</div>
            <div style={{ marginBottom: 8 }}>
              No data yet — send a request through the API to see analytics here.
            </div>
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            {/* Header row */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: COL,
                gap: 12,
              }}
            >
              <div style={thStyle}>Department</div>
              <div style={{ ...thStyle, cursor: "pointer" }} onClick={() => toggleSort("hit_rate")}>
                Hit rate {sortIndicator("hit_rate")}
              </div>
              <div style={{ ...thStyle, cursor: "pointer" }} onClick={() => toggleSort("hits")}>
                Hits {sortIndicator("hits")}
              </div>
              <div style={{ ...thStyle, cursor: "pointer" }} onClick={() => toggleSort("misses")}>
                Misses {sortIndicator("misses")}
              </div>
              <div style={{ ...thStyle, cursor: "pointer" }} onClick={() => toggleSort("requests")}>
                Requests {sortIndicator("requests")}
              </div>
              <div style={thStyle}>Share of traffic</div>
            </div>

            {/* Body rows */}
            {sortedItems.map((d, i) => {
              const share = totalReqs > 0 ? d.requests / totalReqs : 0;
              return (
                <div
                  key={d.department}
                  style={{
                    display: "grid",
                    gridTemplateColumns: COL,
                    gap: 12,
                    padding: "10px 12px",
                    borderBottom: i < sortedItems.length - 1 ? "1px solid var(--border)" : "none",
                    cursor: "pointer",
                    transition: "background 0.1s",
                    background: selectedDept === d.department ? "var(--accent-bg)" : undefined,
                    borderLeft: selectedDept === d.department ? "2px solid var(--accent)" : "2px solid transparent",
                  }}
                  onMouseEnter={(e) => {
                    if (selectedDept !== d.department)
                      (e.currentTarget as HTMLDivElement).style.background = "#202020";
                  }}
                  onMouseLeave={(e) => {
                    if (selectedDept !== d.department)
                      (e.currentTarget as HTMLDivElement).style.background = "";
                  }}
                  onClick={() =>
                    setSelectedDept((prev) => (prev === d.department ? null : d.department))
                  }
                >
                  {/* Department */}
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <HashIcon />
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
                      {d.department}
                    </span>
                  </div>

                  {/* Hit rate */}
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 12,
                        minWidth: 48,
                        color: hitRateColor(d.hit_rate),
                      }}
                    >
                      {fmtPct(d.hit_rate)}
                    </span>
                    <div style={hbarContainer}>
                      <div style={hbarFill(d.hit_rate)} />
                    </div>
                  </div>

                  {/* Hits */}
                  <div
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      color: "var(--accent)",
                      display: "flex",
                      alignItems: "center",
                    }}
                  >
                    {fmtNum(d.hits)}
                  </div>

                  {/* Misses */}
                  <div
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      color: "var(--amber)",
                      display: "flex",
                      alignItems: "center",
                    }}
                  >
                    {fmtNum(d.misses)}
                  </div>

                  {/* Requests */}
                  <div
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      display: "flex",
                      alignItems: "center",
                    }}
                  >
                    {fmtNum(d.requests)}
                  </div>

                  {/* Share of traffic */}
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span
                      style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: 12,
                        color: "var(--fg-dim)",
                        minWidth: 48,
                      }}
                    >
                      {fmtPct(share)}
                    </span>
                    <div style={hbarContainer}>
                      <div style={hbarFill(share, "var(--fg-dimmer)")} />
                    </div>
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
