"use client";

import { useState } from "react";
import type { AppMessage } from "./ChatMessage";
import { copyText } from "./copy-text";
import { cacheComparison, classifyRoute, formatLatency, formatMultiplier, routeStyle } from "./provenance";
import { RouteIcon } from "./RouteMarker";
import { diffQueries, isLossyHeaderText } from "./word-diff";

// Server-side cache-tier thresholds (DEJAQ_CACHE_TRUST_DISTANCE,
// DEJAQ_CACHE_BAND_MAX_DISTANCE, DEJAQ_CACHE_RESCUE_MAX_DISTANCE, and
// DEJAQ_VALIDATOR_SKIP_DISTANCE — CLAUDE.md, app/config.py). Global
// constants, not per-workspace overridable, so drawing the scale from them
// here is safe: this file has no way to learn a workspace's own values, and
// none exist.
const TRUST_DISTANCE = 0.15;
const BAND_MAX_DISTANCE = 0.2;
const RESCUE_MAX_DISTANCE = 0.6;
const VALIDATOR_SKIP_DISTANCE = 0.05;

// The side panel's width. It overlays the transcript rather than taking room
// from it, so nothing else in the layout is derived from this number.
const DETAIL_PANEL_WIDTH = 384;

interface Props {
  // Null when the panel was opened from the header with no turn selected —
  // the panel still renders, with an explicit empty state, rather than
  // leaving the toggle looking active over nothing.
  message: AppMessage | null;
  // The typed question that produced this answer — needed to diff against
  // the stored one for "why it matched". Looked up by the caller from the
  // preceding user turn.
  typedQuery: string | null;
  deptSlug: string;
  baselineMs: number | null;
  baselineSampleCount: number;
  onClose: () => void;
  asDrawer: boolean;
}

export default function ResponseDetail({
  message,
  typedQuery,
  deptSlug,
  baselineMs,
  baselineSampleCount,
  onClose,
  asDrawer,
}: Props) {
  const route = message ? classifyRoute(message.tier, message.modelUsed) : null;
  const style = routeStyle(route);

  const panelStyle: React.CSSProperties = asDrawer
    ? {
        background: "var(--bg-2)",
        borderTop: "1px solid var(--border-2)",
        bottom: 0,
        boxShadow: "var(--shadow-up)",
        display: "flex",
        flexDirection: "column",
        left: 0,
        maxHeight: "60vh",
        position: "fixed",
        right: 0,
        zIndex: 40,
      }
    : {
        background: "var(--bg-2)",
        borderLeft: "1px solid var(--border-2)",
        bottom: 0,
        boxShadow: "var(--shadow)",
        display: "flex",
        flexDirection: "column",
        position: "absolute",
        right: 0,
        top: 0,
        width: `${DETAIL_PANEL_WIDTH}px`,
        zIndex: 30,
      };

  return (
    <aside style={panelStyle}>
      <div
        style={{
          alignItems: "center",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          flexShrink: 0,
          height: "52px",
          padding: "0 10px 0 20px",
        }}
      >
        <span style={{ flex: 1, fontSize: "13.5px", fontWeight: 600 }}>Response detail</span>
        <button
          onClick={onClose}
          title="Close"
          aria-label="Close response detail"
          style={{
            alignItems: "center",
            background: "transparent",
            border: "none",
            borderRadius: "5px",
            color: "var(--fg-dimmer)",
            cursor: "pointer",
            display: "flex",
            padding: "6px",
          }}
        >
          <CloseIcon />
        </button>
      </div>

      {!message ? (
        <div
          style={{
            alignItems: "center",
            display: "flex",
            flex: 1,
            justifyContent: "center",
            minHeight: 0,
            padding: "24px",
          }}
        >
          <p
            style={{
              color: "var(--fg-dimmer)",
              fontSize: "12.5px",
              lineHeight: "19px",
              margin: 0,
              maxWidth: "250px",
              textAlign: "center",
            }}
          >
            No answer selected. Pick one — &ldquo;Why this matched&rdquo; on a cache hit, or the detail
            control under any other answer — to see where it came from.
          </p>
        </div>
      ) : (
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "20px" }}>
        {/* Verdict */}
        <div style={{ alignItems: "center", display: "flex", gap: "13px" }}>
          <div
            style={{
              alignItems: "center",
              background: style.bg,
              border: `1.5px solid ${style.solid}`,
              borderRadius: "50%",
              color: style.ink,
              display: "flex",
              flexShrink: 0,
              height: "40px",
              justifyContent: "center",
              width: "40px",
            }}
          >
            {/* display:flex keeps the svg out of an inline line box; as an inline
                child it would sit on the text baseline and the descender gap
                below it would push the glyph visibly high inside the circle. */}
            <span style={{ display: "flex", transform: "scale(1.35)" }}>
              {route !== null && <RouteIcon route={route} />}
            </span>
          </div>
          <div>
            <div style={{ fontSize: "19px", fontWeight: 600, letterSpacing: "-0.018em", lineHeight: "24px" }}>
              {route === "cache"
                ? "Cache hit"
                : route === "local"
                  ? "Answered locally"
                  : route === "cloud"
                    ? "Answered by cloud"
                    : "Still answering"}
            </div>
            {deptSlug && (
              <div style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: "11.5px", marginTop: "2px" }}>
                {deptSlug}
              </div>
            )}
          </div>
        </div>

        <Divider />

        {/* Speed */}
        <Section title="Speed">
          {route === "cache" ? (
            <CacheSpeed latencyMs={message.latencyMs} baselineMs={baselineMs} sampleCount={baselineSampleCount} />
          ) : (
            <div style={{ alignItems: "center", display: "flex", gap: "10px" }}>
              <span style={{ color: "var(--fg)", fontSize: "12.5px" }}>This answer</span>
              <div style={{ flex: 1 }} />
              <span style={{ color: style.ink, fontFamily: "var(--font-mono)", fontSize: "11.5px", fontWeight: 500 }}>
                {message.latencyMs !== undefined ? formatLatency(message.latencyMs) : "-"}
              </span>
            </div>
          )}
        </Section>

        {route === "cache" && (
          <>
            <Divider />
            <WhyItMatched typedQuery={typedQuery} message={message} />
          </>
        )}

        <Divider />

        {/* Routing */}
        <Section title="Routing">
          <Row label="Difficulty">
            {route === "cache" ? (
              <MonoValue note="cache hits skip the difficulty classifier">not applicable</MonoValue>
            ) : (
              <MonoValue>{message.promptDifficulty ?? "-"}</MonoValue>
            )}
          </Row>
          <Row label="Model">
            {route === "cache" ? (
              <MonoValue note="served from store">none</MonoValue>
            ) : (
              <MonoValue>{message.modelUsed ?? "-"}</MonoValue>
            )}
          </Row>
          {deptSlug && (
            <Row label="Department">
              <MonoValue>{deptSlug}</MonoValue>
            </Row>
          )}
          {message?.ragDocumentTitle && (
            // The only remaining grounding source: an explicit `@`-reference,
            // or a suggestion the user accepted (which sets the exact same
            // state) — never a silent distance guess, so this is shown even
            // on a cache hit. `ragChunks` alone (no title) can no longer
            // happen now that automatic, unreferenced grounding is gone.
            <Row label="Knowledge base">
              <MonoValue note="explicitly referenced">grounded in {message.ragDocumentTitle}</MonoValue>
            </Row>
          )}
        </Section>

        <Divider />

        {/* Identity */}
        <Section title="Identity">
          {message.responseId && <CopyRow value={message.responseId} />}
          {message.interactionId && <CopyRow value={message.interactionId} />}
          {!message.responseId && !message.interactionId && (
            <span style={{ color: "var(--fg-dimmer)", fontSize: "12px" }}>No identifiers for this response.</span>
          )}
        </Section>
      </div>
      )}

      {route === "cache" && (
        <div
          style={{
            borderTop: "1px solid var(--border)",
            color: "var(--fg-dimmer)",
            flexShrink: 0,
            fontSize: "11.5px",
            lineHeight: "17px",
            padding: "14px 20px",
          }}
        >
          A thumbs-down deletes this cached answer, so the next person asking gets a fresh one.
        </div>
      )}
    </aside>
  );
}

function CacheSpeed({
  latencyMs,
  baselineMs,
  sampleCount,
}: {
  latencyMs: number | undefined;
  baselineMs: number | null;
  sampleCount: number;
}) {
  if (latencyMs === undefined) return <span style={{ color: "var(--fg-dimmer)", fontSize: "12px" }}>No latency recorded.</span>;

  const comparison = cacheComparison(latencyMs, baselineMs, sampleCount);

  if (baselineMs === null || comparison.kind === "no-baseline") {
    return (
      <>
        <SpeedBar label="This answer" ms={latencyMs} widthPct={100} tone="var(--accent-solid)" valueColor="var(--accent)" />
        <p style={{ color: "var(--fg-dimmer)", fontSize: "12px", lineHeight: 1.5, margin: "11px 0 0" }}>
          No comparison yet — this session has no locally- or cloud-generated answer to compare against.
        </p>
      </>
    );
  }

  // Both bars scale against the slower of the two, so a cache hit that cost
  // more than the session's average generation draws visibly longer instead
  // of being clamped to the same length as the bar it lost to.
  const longestMs = Math.max(latencyMs, baselineMs);
  const thisPct = Math.max(2, (latencyMs / longestMs) * 100);
  const baselinePct = Math.max(2, (baselineMs / longestMs) * 100);

  return (
    <>
      <SpeedBar label="This answer" ms={latencyMs} widthPct={thisPct} tone="var(--accent-solid)" valueColor="var(--accent)" />
      <div style={{ marginTop: "9px" }}>
        <SpeedBar label="If generated" ms={baselineMs} widthPct={baselinePct} tone="var(--border-2)" valueColor="var(--fg-dim)" />
      </div>
      <p style={{ color: "var(--fg-dim)", fontSize: "12px", lineHeight: 1.5, margin: "11px 0 0" }}>
        {comparison.kind === "faster" ? (
          <>
            <span style={{ color: "var(--accent)", fontWeight: 600 }}>{formatMultiplier(comparison.multiplier)} faster</span>{" "}
            than this session&rsquo;s average generated answer.{" "}
          </>
        ) : (
          <>
            Served in {formatLatency(latencyMs)}, against a {formatLatency(baselineMs)} average for this
            session&rsquo;s generated answers.{" "}
          </>
        )}
        {sampleCount < 3 && (
          <span style={{ color: "var(--fg-dimmer)" }}>
            (based on {sampleCount} generated answer{sampleCount === 1 ? "" : "s"} this session)
          </span>
        )}
      </p>
    </>
  );
}

function SpeedBar({
  label,
  ms,
  widthPct,
  tone,
  valueColor,
}: {
  label: string;
  ms: number;
  widthPct: number;
  tone: string;
  valueColor: string;
}) {
  return (
    <div style={{ alignItems: "center", display: "flex", gap: "10px" }}>
      <div style={{ color: "var(--fg)", fontSize: "12.5px", width: "88px" }}>{label}</div>
      <div style={{ background: "var(--bg-3)", borderRadius: "4px", flex: 1, height: "7px", overflow: "hidden" }}>
        <div style={{ background: tone, borderRadius: "4px", height: "7px", width: `${widthPct}%` }} />
      </div>
      <div style={{ color: valueColor, fontFamily: "var(--font-mono)", fontSize: "11.5px", textAlign: "right", width: "52px" }}>
        {formatLatency(ms)}
      </div>
    </div>
  );
}

function WhyItMatched({ typedQuery, message }: { typedQuery: string | null; message: AppMessage }) {
  const stored = message.cacheMatchedQuery ?? null;
  const distance = message.cacheDistance ?? null;
  // Absent (not empty, not a repeat of "You asked") whenever the follow-up
  // was already standalone - see the server's own rule in context_enricher.py.
  const enriched = message.cacheEnrichedQuery ?? null;

  if (!stored || distance === null) {
    return (
      <Section title="Why it matched">
        <span style={{ color: "var(--fg-dimmer)", fontSize: "12px" }}>
          Not available for this response.
        </span>
      </Section>
    );
  }

  const lossy = isLossyHeaderText(stored, typedQuery);
  const diff = typedQuery && !lossy ? diffQueries(typedQuery, stored) : null;
  const tier = distance <= TRUST_DISTANCE ? "Trusted" : distance <= BAND_MAX_DISTANCE ? "Band" : "Rescue";
  const validatorNeeded = distance > VALIDATOR_SKIP_DISTANCE;

  // Scale drawn against the rescue ceiling — trusted/band/rescue proportion
  // exactly like the server's own thresholds (0.15 / 0.20 / 0.60 of 0.60).
  const trustPct = (TRUST_DISTANCE / RESCUE_MAX_DISTANCE) * 100;
  const bandPct = ((BAND_MAX_DISTANCE - TRUST_DISTANCE) / RESCUE_MAX_DISTANCE) * 100;
  const dotPct = Math.max(0, Math.min(100, (distance / RESCUE_MAX_DISTANCE) * 100));

  return (
    <Section title="Why it matched">
      {diff && (
        <>
          <div style={{ color: "var(--fg-dimmer)", fontSize: "11.5px" }}>You asked</div>
          <div style={{ color: "var(--fg-dim)", fontFamily: "var(--font-serif)", fontSize: "14px", lineHeight: "21px", marginTop: "3px" }}>
            &ldquo;
            {diff.typed.map((w, i) => (
              <span key={i}>
                {i > 0 && " "}
                <span style={w.changed ? { borderBottom: "1.5px solid var(--accent-border)", color: "var(--accent)" } : undefined}>
                  {w.text}
                </span>
              </span>
            ))}
            &rdquo;
          </div>
          {enriched && <SearchedAsRow enriched={enriched} />}
          <div style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", marginTop: "11px" }}>Stored answer for</div>
          <div style={{ color: "var(--fg)", fontFamily: "var(--font-serif)", fontSize: "14px", lineHeight: "21px", marginTop: "3px" }}>
            &ldquo;
            {diff.stored.map((w, i) => (
              <span key={i}>
                {i > 0 && " "}
                <span style={w.changed ? { color: "var(--green)" } : undefined}>{w.text}</span>
              </span>
            ))}
            &rdquo;
          </div>
        </>
      )}
      {!diff && (
        <>
          {enriched && <SearchedAsRow enriched={enriched} topMargin={0} />}
          <div style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", marginTop: enriched ? "11px" : 0 }}>
            Stored answer for
          </div>
          <div style={{ color: "var(--fg)", fontFamily: "var(--font-serif)", fontSize: "14px", lineHeight: "21px", marginTop: "3px" }}>
            &ldquo;{stored}&rdquo;
          </div>
          {lossy && (
            <div style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", lineHeight: "17px", marginTop: "7px" }}>
              Shown as the server reported it. This diagnostic value may be shortened, or carry
              replacements for characters the header cannot hold, so it is not compared word by
              word.
            </div>
          )}
        </>
      )}

      <div style={{ marginTop: "16px" }}>
        <div style={{ display: "flex", height: "6px", overflow: "hidden", position: "relative" }}>
          <div style={{ background: "var(--accent-solid)", opacity: 0.75, width: `${trustPct}%` }} />
          <div style={{ background: "var(--accent-solid)", opacity: 0.32, width: `${bandPct}%` }} />
          <div style={{ background: "var(--bg-3)", flex: 1 }} />
        </div>
        <div style={{ height: 0, position: "relative" }}>
          <div
            style={{
              background: "var(--bg-2)",
              border: "2.5px solid var(--accent-solid)",
              borderRadius: "999px",
              height: "10px",
              left: `${dotPct}%`,
              position: "absolute",
              top: "-11px",
              width: "10px",
            }}
          />
        </div>
        <div style={{ display: "flex", marginTop: "10px" }}>
          <div style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: "10.5px", width: `${trustPct}%` }}>
            trusted
          </div>
          <div style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: "10.5px", width: `${bandPct}%` }}>
            band
          </div>
          <div style={{ color: "var(--fg-dimmer)", flex: 1, fontFamily: "var(--font-mono)", fontSize: "10.5px", textAlign: "right" }}>
            rescue · {RESCUE_MAX_DISTANCE.toFixed(2)}
          </div>
        </div>
      </div>

      <div style={{ alignItems: "center", display: "flex", gap: "8px", marginTop: "13px" }}>
        <span style={{ color: "var(--fg)", fontFamily: "var(--font-mono)", fontSize: "11.5px" }}>
          distance {distance.toFixed(3)}
        </span>
        <span
          style={{
            background: "var(--accent-bg)",
            borderRadius: "999px",
            color: "var(--accent)",
            fontSize: "10.5px",
            fontWeight: 600,
            letterSpacing: "0.04em",
            padding: "2px 8px",
            textTransform: "uppercase",
          }}
        >
          {tier}
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ alignItems: "center", color: "var(--fg-dimmer)", display: "flex", fontSize: "11.5px", gap: "5px" }}>
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="var(--green)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3.2 8.4 6.4 11.6 12.8 5" />
          </svg>
          {validatorNeeded ? "validator confirmed the match" : "no validator needed"}
        </span>
      </div>
    </Section>
  );
}

// The standalone question the context enricher rewrote a follow-up into
// before searching the cache - the step between the user's raw words and the
// stored question they matched. No word-diff here: it is not being compared
// against anything, just shown as the extra step, in the same quoted-question
// typography as "You asked"/"Stored answer for" so it reads as a peer of both.
function SearchedAsRow({ enriched, topMargin = 11 }: { enriched: string; topMargin?: number }) {
  return (
    <>
      <div style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", marginTop: `${topMargin}px` }}>
        Searched as
      </div>
      <div style={{ color: "var(--fg-dim)", fontFamily: "var(--font-serif)", fontSize: "14px", lineHeight: "21px", marginTop: "3px" }}>
        &ldquo;{enriched}&rdquo;
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <SectionLabel>{title}</SectionLabel>
      <div style={{ marginTop: "11px" }}>{children}</div>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        color: "var(--fg-dimmer)",
        fontSize: "10.5px",
        fontWeight: 600,
        letterSpacing: "0.1em",
        textTransform: "uppercase",
      }}
    >
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ alignItems: "flex-start", display: "flex", marginTop: "7px" }}>
      <span style={{ color: "var(--fg-dim)", flexShrink: 0, fontSize: "12.5px", width: "88px" }}>{label}</span>
      {children}
    </div>
  );
}

function MonoValue({ note, children }: { note?: string; children: React.ReactNode }) {
  return (
    <div>
      <span style={{ color: "var(--fg)", fontFamily: "var(--font-mono)", fontSize: "11.5px" }}>{children}</span>
      {note && (
        <div style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", marginTop: "2px" }}>{note}</div>
      )}
    </div>
  );
}

function CopyRow({ value }: { value: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  return (
    <div style={{ alignItems: "center", display: "flex", gap: "8px", marginTop: "7px" }}>
      <span
        style={{
          color: "var(--fg-dim)",
          flex: 1,
          fontFamily: "var(--font-mono)",
          fontSize: "11px",
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={value}
      >
        {value}
      </span>
      <button
        onClick={() =>
          copyText(value).then((ok) => {
            setState(ok ? "copied" : "failed");
            setTimeout(() => setState("idle"), 1500);
          })
        }
        title={state === "copied" ? "Copied" : "Copy"}
        aria-label="Copy"
        style={{
          alignItems: "center",
          background: "transparent",
          border: "none",
          color: state === "copied" ? "var(--green)" : state === "failed" ? "var(--red)" : "var(--fg-dimmer)",
          cursor: "pointer",
          display: "flex",
          flexShrink: 0,
          padding: "2px",
        }}
      >
        <CopyIcon />
      </button>
    </div>
  );
}

function Divider() {
  return <div style={{ background: "var(--border)", height: "1px", margin: "20px 0" }} />;
}

function CloseIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
      <path d="M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8" />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round">
      <rect x="5.6" y="5.6" width="8.1" height="8.1" rx="1.5" />
      <path d="M10.6 5.6V3.4a1 1 0 0 0-1-1H3.3a1 1 0 0 0-1 1v6.3a1 1 0 0 0 1 1h2.3" />
    </svg>
  );
}
