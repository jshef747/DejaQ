"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import CodeBlock from "./CodeBlock";
import TurnShell from "./ReadingColumn";
import { RouteRing, WaitRing } from "./RouteMarker";
import {
  cacheComparison,
  classifyRoute,
  formatLatency,
  formatMultiplier,
  ROUTE_STYLE,
  type CacheComparison,
  type Route,
} from "./provenance";
import type { FeedbackRating } from "./chat-api";

// The full feedback lifecycle for a single assistant message.
// "idle"/"error" are re-enabled states; "submitting" is in-flight; the rest are terminal.
export type FeedbackPhase = "idle" | "submitting" | "positive" | "negative" | "error";

export interface AppMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  ts: number;
  sourceLabel?: string;
  // Data URL of an image the user attached to this message (user messages only).
  imageUrl?: string | null;
  // A non-image attachment (PDF/Markdown) has nothing to preview, so the card
  // shows a named chip instead.
  fileName?: string | null;
  // True when the attachment was carried over from an earlier turn rather than
  // picked for this one. The transcript shows both, but reuse is drawn smaller
  // so the turn that actually uploaded stays identifiable at a glance.
  attachmentSticky?: boolean;
  // Assistant-only fields:
  modelUsed?: string | null;
  interactionId?: string | null;
  tier?: "cache" | "local" | "external" | null;
  responseId?: string | null;
  requestMessages?: Array<{ role: "user" | "assistant" | "system"; content: string }>;
  promptTokens?: number;
  completionTokens?: number;
  feedbackPhase?: FeedbackPhase;
  feedbackScore?: number | null;
  latencyMs?: number;
  cacheHit?: boolean;
  promptDifficulty?: string | null;
  // Already-forwarded headers the cache lookup produces on a hit; null on a
  // miss (local/cloud) or before the pipeline resolves either.
  cacheDistance?: number | null;
  cacheMatchedQuery?: string | null;
}

interface Props {
  message: AppMessage;
  // Parent handles the API call and updates feedbackPhase on the message.
  onFeedback: (messageId: string, rating: FeedbackRating, comment: string) => Promise<void>;
  onInspect?: (messageId: string) => void;
  inspected?: boolean;
  // This session's rolling average non-cache latency, and how many answers
  // it averages. Null/0 means the session has generated nothing yet, so the
  // cache line states the fact without a speed claim rather than defaulting
  // to an invented one.
  baselineMs: number | null;
  baselineSampleCount: number;
}

function routeAnswerLine(
  route: Route,
  modelUsed: string | null | undefined,
  comparison: CacheComparison,
  latencyMs: number | undefined,
  baselineMs: number | null,
): { title: string; body: string } {
  if (route === "cache") {
    return { title: "Answered from cache", body: cacheAnswerBody(comparison, latencyMs, baselineMs) };
  }
  if (route === "local") {
    return { title: "Answered locally", body: `Generated on ${modelUsed ?? "the local model"}.` };
  }
  return { title: "Answered by cloud", body: `Generated on ${modelUsed ?? "the external provider"}.` };
}

function cacheAnswerBody(
  comparison: CacheComparison,
  latencyMs: number | undefined,
  baselineMs: number | null,
): string {
  if (comparison.kind === "faster") {
    return `You asked this before — ${formatMultiplier(comparison.multiplier)} faster than this session's average generated answer.`;
  }
  if (comparison.kind === "not-faster" && latencyMs !== undefined && baselineMs !== null) {
    return `You asked this before — served in ${formatLatency(latencyMs)}, against a ${formatLatency(baselineMs)} average for this session's generated answers.`;
  }
  return "You asked this before — served straight from the store.";
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function ChatMessage({
  message,
  onFeedback,
  onInspect,
  inspected,
  baselineMs,
  baselineSampleCount,
}: Props) {
  const isUser = message.role === "user";
  const phase = message.feedbackPhase ?? "idle";

  // Immediately submit feedback without a comment or confirmation step.
  async function handleFeedbackClick(rating: FeedbackRating) {
    if (phase !== "idle" && phase !== "error") return;
    await onFeedback(message.id, rating, "");
  }

  // The user's turn is a card in the interface sans; the model's turn is
  // typeset prose in the serif. The two voices separate by register, not
  // by alignment alone.
  if (isUser) {
    return (
      <TurnShell gap={26}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
          <div
            style={{
              background: "var(--bg-3)",
              border: "1px solid var(--border)",
              borderRadius: "14px 14px 5px 14px",
              color: "var(--fg)",
              fontSize: "13.5px",
              lineHeight: "21px",
              maxWidth: "78%",
              padding: "10px 15px",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {message.imageUrl && !message.attachmentSticky && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={message.imageUrl}
                alt="Attached"
                style={{
                  borderRadius: "9px",
                  display: "block",
                  marginBottom: message.content ? "8px" : 0,
                  maxHeight: "240px",
                  maxWidth: "100%",
                  objectFit: "contain",
                }}
              />
            )}
            {(message.fileName || (message.imageUrl && message.attachmentSticky)) && (
              // Its own line: the chip names what the turn carried, it is not
              // part of the sentence.
              <div style={{ marginBottom: message.content ? "8px" : 0 }}>
                <span
                  style={{
                    alignItems: "center",
                    background: message.attachmentSticky ? "transparent" : "var(--bg-2)",
                    border: message.attachmentSticky
                      ? "1px dashed var(--border-2)"
                      : "1px solid var(--border-2)",
                    borderRadius: "7px",
                    color: "var(--fg-dim)",
                    display: "inline-flex",
                    fontSize: message.attachmentSticky ? "11px" : "11.5px",
                    gap: "6px",
                    maxWidth: "100%",
                    overflow: "hidden",
                    padding: "4px 9px",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {message.attachmentSticky ? (
                    // Reuse, not upload — a recycle glyph rather than the file icon.
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
                      <path d="M2.5 8a5.5 5.5 0 0 1 9.4-3.9M13.5 8a5.5 5.5 0 0 1-9.4 3.9" strokeLinecap="round" />
                      <path d="M12 1.5v3h-3M4 14.5v-3h3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : (
                    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
                      <path d="M9.5 1.5H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5l-3.5-3.5z" strokeLinejoin="round" />
                      <path d="M9.5 1.5V5H13" strokeLinejoin="round" />
                    </svg>
                  )}
                  {message.fileName ?? "same image"}
                </span>
              </div>
            )}
            {message.content}
          </div>
          <span className="dq-hover-meta" style={{ color: "var(--fg-dimmer)", fontSize: "10.5px", marginTop: "6px" }}>
            {formatTs(message.ts)}
          </span>
        </div>
      </TurnShell>
    );
  }

  // Null until the route is known — a streaming answer before its headers
  // land, or a response that carried none. Neither the strip nor a coloured
  // ring may guess at it.
  const route = classifyRoute(message.tier, message.modelUsed);
  const style = route === null ? null : ROUTE_STYLE[route];
  const line =
    route === null
      ? null
      : routeAnswerLine(
          route,
          message.modelUsed,
          cacheComparison(message.latencyMs, baselineMs, baselineSampleCount),
          message.latencyMs,
          baselineMs,
        );

  return (
    <TurnShell
      gap={40}
      marker={
        route === null ? (
          <WaitRing route={null} sinceMs={null} />
        ) : (
          <RouteRing route={route} latencyMs={message.latencyMs} active={inspected} />
        )
      }
    >
      {style && line && (
        <div
          style={{
            alignItems: "center",
            background: style.bg,
            borderRadius: "9px",
            display: "flex",
            gap: "10px",
            // min-height, not height: the cache line ("You asked this before -
            // Nx faster than this session's average generated answer.") wraps to
            // two lines in the 704px reading column, and a fixed 34px box clipped
            // it. Single-line strips (local, cloud) still measure exactly 34px.
            marginBottom: "16px",
            minHeight: "34px",
            padding: "0 12px",
          }}
        >
          <span style={{ color: style.ink, fontSize: "12.5px", fontWeight: 600 }}>{line.title}</span>
          <span style={{ color: "var(--fg-dim)", fontSize: "12.5px" }}>{line.body}</span>
          <div style={{ flex: 1 }} />
          {route === "cache" && onInspect && (
            <button
              onClick={() => onInspect(message.id)}
              style={{
                alignItems: "center",
                background: "transparent",
                border: "none",
                color: style.ink,
                cursor: "pointer",
                display: "flex",
                fontSize: "12px",
                fontWeight: 600,
                gap: "4px",
                padding: 0,
              }}
            >
              Why this matched
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 3.5 10.5 8 6 12.5" />
              </svg>
            </button>
          )}
        </div>
      )}

      <MarkdownContent content={message.content} />

      {/* Timestamp + response-detail affordance — hover-revealed; the strip
          above already carries the route, so this row is pure metadata. */}
      <div className="dq-hover-meta" style={{ alignItems: "center", display: "flex", gap: "8px", marginTop: "16px" }}>
        {message.sourceLabel && (
          <span style={{ color: "var(--fg-dimmer)", fontSize: "10.5px" }}>{message.sourceLabel}</span>
        )}
        <span style={{ color: "var(--fg-dimmer)", fontSize: "10.5px" }}>{formatTs(message.ts)}</span>
        {onInspect && route !== "cache" && (
          <button
            onClick={() => onInspect(message.id)}
            title={inspected ? "Currently inspecting" : "Response detail"}
            style={{
              alignItems: "center",
              background: inspected ? "var(--bg-3)" : "transparent",
              border: `1px solid ${inspected ? "var(--border-2)" : "var(--border)"}`,
              borderRadius: "5px",
              color: inspected ? "var(--fg)" : "var(--fg-dimmer)",
              cursor: "pointer",
              display: "flex",
              padding: "2px 5px",
              transition: "background var(--t-base), border-color var(--t-base), color var(--t-base)",
            }}
            aria-label="Response detail"
          >
            <InspectIcon />
          </button>
        )}
      </div>

      {/* Feedback row — icon-only thumbs, no comment box, immediate submit on click */}
      {(message.responseId || message.interactionId) && (
        <div style={{ alignItems: "center", display: "flex", gap: "4px", marginTop: "8px" }}>
          {(phase === "idle" || phase === "error" || phase === "submitting") && (
            <>
              <button
                onClick={() => handleFeedbackClick("positive")}
                disabled={phase === "submitting"}
                title="Helpful"
                style={thumbBtn(phase === "submitting")}
              >
                <ThumbUpIcon />
              </button>
              <button
                onClick={() => handleFeedbackClick("negative")}
                disabled={phase === "submitting"}
                title="Not helpful"
                style={thumbBtn(phase === "submitting")}
              >
                <ThumbDownIcon />
              </button>
            </>
          )}
          {phase === "positive" && (
            <span style={feedbackDoneStyle("positive")}>
              <ThumbUpIcon />
            </span>
          )}
          {phase === "negative" && (
            <span style={feedbackDoneStyle("negative")}>
              <ThumbDownIcon />
            </span>
          )}
          {typeof message.feedbackScore === "number" && (phase === "positive" || phase === "negative") && (
            <span style={feedbackScoreStyle()}>
              Recorded — this answer now scores {message.feedbackScore.toFixed(1)} in the cache.
            </span>
          )}
        </div>
      )}
    </TurnShell>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="dq-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: ({ children, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
          // A code block gets a language label and a copy control; a table
          // gets a scroller of its own so a wide one never widens the page.
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          table: ({ children }) => (
            <div className="dq-table-scroll">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

// ─── Style helpers ─────────────────────────────────────────────────────────────

function formatTs(ts: number): string {
  return new Date(ts).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function thumbBtn(disabled: boolean): React.CSSProperties {
  return {
    alignItems: "center",
    background: "var(--bg-3)",
    border: "1px solid var(--border)",
    borderRadius: "5px",
    color: "var(--fg-dimmer)",
    cursor: disabled ? "not-allowed" : "pointer",
    display: "flex",
    opacity: disabled ? 0.4 : 1,
    padding: "4px 6px",
  };
}

function feedbackDoneStyle(rating: FeedbackRating): React.CSSProperties {
  const ok = rating === "positive";
  return {
    alignItems: "center",
    background: ok ? "var(--green-bg)" : "var(--red-bg)",
    border: `1px solid ${ok ? "var(--green-border)" : "var(--red-border)"}`,
    borderRadius: "5px",
    color: ok ? "var(--green)" : "var(--red)",
    display: "flex",
    padding: "4px 6px",
  };
}

function feedbackScoreStyle(): React.CSSProperties {
  return {
    color: "var(--fg-dimmer)",
    fontSize: "11.5px",
    padding: "0 4px",
  };
}

// ─── Icons ─────────────────────────────────────────────────────────────────────

function ThumbUpIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M5 9V15H2a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1h3zm0 0L8 1l.5-.5A1.5 1.5 0 0 1 11 2v2h3.5a1 1 0 0 1 .97 1.24L14 11a1 1 0 0 1-.97.76H5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ThumbDownIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M11 7V1h3a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-3zm0 0L8 15l-.5.5A1.5 1.5 0 0 1 5 14v-2H1.5a1 1 0 0 1-.97-1.24L2 5a1 1 0 0 1 .97-.76H11" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function InspectIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5L14 14" strokeLinecap="round" />
      <path d="M7 5v2M7 8.5v.5" strokeLinecap="round" />
    </svg>
  );
}
