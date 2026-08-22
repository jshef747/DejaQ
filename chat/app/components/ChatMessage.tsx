"use client";

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import CodeBlock, { plainText } from "./CodeBlock";
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
import { canSave, isSaveShortcut, normalizeDraft } from "./edit-draft";
import { textDirection } from "./text-direction";
import type { FeedbackRating } from "./chat-api";

// The full feedback lifecycle for a single assistant message.
// "idle"/"error" are re-enabled states; "positive"/"negative" are terminal.
// The click sets the terminal state optimistically, before the request even
// lands — see ChatApp.handleFeedback — so there is no separate in-flight state.
export type FeedbackPhase = "idle" | "positive" | "negative" | "error";

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
  // Title of the knowledge-base document this turn explicitly referenced with
  // `@` — set on the user message from the picker selection, and on the
  // assistant message from the server's own confirmation header, so the mark
  // never claims a grounding the server didn't actually apply.
  ragDocumentTitle?: string | null;
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
  cacheEnrichedQuery?: string | null;
  // Count of knowledge-base passages injected on a miss that RAG grounded.
  // Null when nothing was retrieved, or on a cache hit (grounding, if
  // any, happened whenever that answer was first generated, not now). Count
  // only — the header carries no document title, and this is not worth a new
  // backend endpoint just to name it.
  ragChunks?: number | null;
  // Set by Stop: this answer was cut off mid-generation. Whatever text had
  // already streamed in is kept, marked, and never mistaken for a complete
  // answer — it carries no responseId/interactionId, so the feedback row
  // below simply doesn't render for it.
  stopped?: boolean;
  // The send this turn belongs to failed. Same shape as `stopped`: kept and
  // marked, never erased — the question is not thrown away because the request
  // was — with Retry on the mark. It sits on the question when nothing
  // streamed, and on the partial answer when something did.
  //
  // The value says which failure it was, because the two read as opposite
  // things to the person looking at them: "unsent" is the request itself
  // failing (network, 402, a stream that dropped mid-answer), while
  // "empty-answer" reached the server, came back HTTP 200, and simply had no
  // text in it — a rephrasing problem, not a connectivity one.
  failed?: "unsent" | "empty-answer";
  // Whether this turn carried an attachment, recorded on the turn itself
  // rather than read back off the composer. The file's bytes are never stored,
  // and `imageUrl` is stripped from storage on save, so this boolean is the
  // only thing that still knows the truth after a reload — and it is what
  // decides that a failed attachment turn gets no Retry, since the attachment
  // it needs can no longer be reproduced.
  hadAttachment?: boolean;
  // A person rewrote this answer through Edit & Save and it was accepted as the
  // cached answer. Persisted, so a reloaded conversation still shows the mark —
  // the transcript would otherwise claim a model wrote text a person did.
  editedByUser?: boolean;
  // This answer came back from a cache entry somebody ELSE corrected
  // (x-dejaq-answer-authored). Same claim as editedByUser — a person wrote
  // this — from the other side of the exchange, so it earns the same mark
  // with different wording.
  authoredByHuman?: boolean;
}

// What the mark under a failed turn says. The question and the answer failing
// are different sentences, and a request that arrived and returned nothing is
// a different sentence again — it matches the "Empty answer" toast rather than
// implying the send never left.
function failedLabel(message: AppMessage): string {
  if (message.failed === "empty-answer") return "Empty answer";
  return message.role === "assistant" ? "Answer failed" : "Not sent";
}

interface Props {
  message: AppMessage;
  // Parent handles the API call and updates feedbackPhase on the message.
  onFeedback: (messageId: string, rating: FeedbackRating, comment: string) => Promise<void>;
  // Re-runs the turn this message belongs to. Only ever offered on a message
  // marked `failed`.
  onRetry?: (messageId: string) => void;
  // Commits an edited answer. Resolves false when the save failed, which keeps
  // the editor open with the draft intact rather than discarding the user's
  // work on a network blip.
  onSaveEdit?: (messageId: string, text: string) => Promise<boolean>;
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
  onRetry,
  onSaveEdit,
  onInspect,
  inspected,
  baselineMs,
  baselineSampleCount,
}: Props) {
  const isUser = message.role === "user";
  const phase = message.feedbackPhase ?? "idle";

  // The draft lives here, not in ChatApp. Lifting it would push every keystroke
  // through updateTranscript, re-rendering the whole transcript and arming a
  // localStorage write per character. Only the committed save goes up — the
  // same split CodeBlock uses for its copy state.
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  function startEditing() {
    setDraft(message.content);
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setDraft("");
  }

  async function commitEdit() {
    if (!onSaveEdit || saving || !canSave(message.content, draft)) return;
    setSaving(true);
    const ok = await onSaveEdit(message.id, normalizeDraft(draft));
    setSaving(false);
    // Only close on success. A failed save keeps the editor open with the
    // draft intact — the alternative throws away work the user just did.
    if (ok) {
      setEditing(false);
      setDraft("");
    }
  }

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
                  <bdi>{message.fileName ?? "same image"}</bdi>
                </span>
              </div>
            )}
            {message.ragDocumentTitle && (
              // Same chip language as the attachment one above, but its own
              // line and glyph: a knowledge-base reference isn't an upload.
              <div style={{ marginBottom: message.content ? "8px" : 0 }}>
                <span
                  style={{
                    alignItems: "center",
                    background: "var(--bg-2)",
                    border: "1px solid var(--border-2)",
                    borderRadius: "7px",
                    color: "var(--fg-dim)",
                    display: "inline-flex",
                    fontSize: "11.5px",
                    gap: "6px",
                    maxWidth: "100%",
                    overflow: "hidden",
                    padding: "4px 9px",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
                    <path d="M3.5 2.5h6L12 5.5v8a1 1 0 0 1-1 1h-7.5a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1z" strokeLinejoin="round" />
                    <path d="M5.5 7h5M5.5 9.5h5M5.5 12h3" strokeLinecap="round" />
                  </svg>
                  @<bdi>{message.ragDocumentTitle}</bdi>
                </span>
              </div>
            )}
            {message.content && <div dir={textDirection(message.content)}>{message.content}</div>}
          </div>
          {message.failed && (
            <FailedRow
              label={failedLabel(message)}
              onRetry={onRetry ? () => onRetry(message.id) : undefined}
            />
          )}
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
  // Editing is offered on an answer the cache can actually be told about: it
  // needs a target (response_id or interaction_id), and a stopped or failed
  // turn is not a finished answer to correct.
  const canEdit =
    Boolean(onSaveEdit) &&
    Boolean(message.responseId || message.interactionId) &&
    !message.stopped &&
    !message.failed;

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

      {editing ? (
        <AnswerEditor
          value={draft}
          onChange={setDraft}
          onSave={commitEdit}
          onCancel={cancelEditing}
          saving={saving}
          canCommit={canSave(message.content, draft)}
        />
      ) : (
        <MarkdownContent content={message.content} />
      )}

      {message.stopped && (
        <div style={{ alignItems: "center", color: "var(--fg-dimmer)", display: "flex", fontSize: "12px", gap: "6px", marginTop: "10px" }}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor">
            <rect x="4" y="4" width="8" height="8" rx="1.5" />
          </svg>
          Stopped
        </div>
      )}

      {message.failed && (
        <FailedRow
          label={failedLabel(message)}
          onRetry={onRetry ? () => onRetry(message.id) : undefined}
        />
      )}

      {/* Timestamp + response-detail affordance — hover-revealed; the strip
          above already carries the route, so this row is pure metadata. The
          whole row and the feedback row below are replaced by the editor's own
          controls while editing, so the turn never shows two action bars. */}
      {!editing && (
      <div className="dq-hover-meta" style={{ alignItems: "center", display: "flex", gap: "8px", marginTop: "16px" }}>
        {message.sourceLabel && (
          <span style={{ color: "var(--fg-dimmer)", fontSize: "10.5px" }}>{message.sourceLabel}</span>
        )}
        <span style={{ color: "var(--fg-dimmer)", fontSize: "10.5px" }}>{formatTs(message.ts)}</span>
        {(message.editedByUser || message.authoredByHuman) && (
          // Same quiet register as the Stopped mark: the transcript must not
          // let a person's words read as the model's — whether that person was
          // this user or a teammate who corrected it earlier.
          <span style={{ alignItems: "center", color: "var(--fg-dimmer)", display: "flex", fontSize: "10.5px", gap: "4px" }}>
            <PencilIcon />
            {message.editedByUser ? "Edited by you" : "Human-verified answer"}
          </span>
        )}
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
        {canEdit && (
          <button
            onClick={startEditing}
            title="Edit this answer"
            aria-label="Edit this answer"
            style={{
              alignItems: "center",
              background: "transparent",
              border: "1px solid var(--border)",
              borderRadius: "5px",
              color: "var(--fg-dimmer)",
              cursor: "pointer",
              display: "flex",
              padding: "2px 5px",
              transition: "background var(--t-base), border-color var(--t-base), color var(--t-base)",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--bg-3)";
              e.currentTarget.style.borderColor = "var(--border-2)";
              e.currentTarget.style.color = "var(--fg)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.borderColor = "var(--border)";
              e.currentTarget.style.color = "var(--fg-dimmer)";
            }}
          >
            <PencilIcon />
          </button>
        )}
      </div>
      )}

      {/* Feedback row — icon-only thumbs, no comment box, immediate submit on click */}
      {!editing && (message.responseId || message.interactionId) && (
        <div style={{ alignItems: "center", display: "flex", gap: "4px", marginTop: "8px" }}>
          {(phase === "idle" || phase === "error") && (
            <>
              <button onClick={() => handleFeedbackClick("positive")} title="Helpful" style={thumbBtn()}>
                <ThumbUpIcon />
              </button>
              <button onClick={() => handleFeedbackClick("negative")} title="Not helpful" style={thumbBtn()}>
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

// The failed turn's mark, drawn on the same lines as the Stopped mark above:
// small, quiet, underneath what it is about. It carries Retry because the
// question it marks is the only copy of what the user typed — nothing was put
// back in the composer for them.
function FailedRow({ label, onRetry }: { label: string; onRetry?: () => void }) {
  return (
    <div style={{ alignItems: "center", color: "var(--red)", display: "flex", fontSize: "12px", gap: "10px", marginTop: "10px" }}>
      <span style={{ alignItems: "center", display: "flex", gap: "6px" }}>
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="8" cy="8" r="6.3" />
          <path d="M8 4.9v3.7" />
          <path d="M8 11.1h.01" />
        </svg>
        {label}
      </span>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            alignItems: "center",
            background: "transparent",
            border: "1px solid var(--border-2)",
            borderRadius: "999px",
            color: "var(--fg-dim)",
            cursor: "pointer",
            display: "inline-flex",
            fontSize: "11.5px",
            fontWeight: 500,
            gap: "6px",
            height: "24px",
            padding: "0 10px",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "var(--fg)";
            e.currentTarget.style.borderColor = "var(--fg-dimmer)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "var(--fg-dim)";
            e.currentTarget.style.borderColor = "var(--border-2)";
          }}
        >
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2.6 8a5.4 5.4 0 0 1 9.2-3.8M13.4 8a5.4 5.4 0 0 1-9.2 3.8" />
            <path d="M11.9 1.7v3h-3M4.1 14.3v-3h3" />
          </svg>
          Retry
        </button>
      )}
    </div>
  );
}

// The editing state. It deliberately carries the reading column's exact type
// metrics — serif, 16.5/27, the same measure — so the words do not move when
// the answer becomes editable. That stillness is the whole trick: the turn
// reads as the same text, now typeable, rather than as a form that replaced it.
function AnswerEditor({
  value,
  onChange,
  onSave,
  onCancel,
  saving,
  canCommit,
}: {
  value: string;
  onChange: (next: string) => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  canCommit: boolean;
}) {
  const ref = useRef<HTMLTextAreaElement | null>(null);

  // Grow to fit rather than scroll internally: an answer is read as one block,
  // and a nested scroller inside the reading column would break that.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  // Caret at the end on open, so the user starts where they stopped reading.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  return (
    <div>
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={saving}
        dir={textDirection(value)}
        aria-label="Edit the answer"
        onKeyDown={(e) => {
          if (isSaveShortcut(e)) {
            e.preventDefault();
            onSave();
          } else if (e.key === "Escape") {
            e.preventDefault();
            onCancel();
          }
        }}
        style={{
          background: "var(--bg-2)",
          border: "1px solid var(--border-2)",
          borderRadius: "10px",
          boxSizing: "border-box",
          color: "var(--fg)",
          display: "block",
          fontFamily: "var(--font-serif)",
          fontSize: "16.5px",
          lineHeight: "27px",
          minHeight: "108px",
          opacity: saving ? 0.6 : 1,
          outline: "none",
          overflow: "hidden",
          padding: "14px 16px",
          resize: "none",
          width: "100%",
        }}
      />
      <div style={{ alignItems: "center", display: "flex", gap: "8px", marginTop: "12px" }}>
        <button
          onClick={onSave}
          disabled={saving || !canCommit}
          style={{
            alignItems: "center",
            background: "var(--fg)",
            border: "1px solid var(--fg)",
            borderRadius: "999px",
            color: "var(--bg)",
            cursor: saving || !canCommit ? "not-allowed" : "pointer",
            display: "inline-flex",
            fontSize: "12px",
            fontWeight: 600,
            gap: "7px",
            height: "28px",
            opacity: saving || !canCommit ? 0.45 : 1,
            padding: "0 14px",
          }}
        >
          {saving && (
            // The class carries only the pulse; size and colour are inline, as
            // in ConversationSidebar's WorkingDot. On the filled Save button the
            // dot takes the button's own foreground.
            <span
              aria-hidden
              className="dq-working-dot"
              style={{ background: "var(--bg)", borderRadius: "999px", flexShrink: 0, height: "6px", width: "6px" }}
            />
          )}
          {saving ? "Saving" : "Save"}
        </button>
        <button
          onClick={onCancel}
          disabled={saving}
          style={{
            background: "transparent",
            border: "1px solid var(--border-2)",
            borderRadius: "999px",
            color: "var(--fg-dim)",
            cursor: saving ? "not-allowed" : "pointer",
            fontSize: "12px",
            fontWeight: 500,
            height: "28px",
            padding: "0 14px",
          }}
        >
          Cancel
        </button>
        {/* The blast radius, said plainly. This is not a private note: the next
            person in the department who asks this gets what you typed. */}
        <span style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", marginLeft: "2px" }}>
          Saves as the cached answer for your department.
        </span>
      </div>
    </div>
  );
}

// Direction per block, not for the whole message: a code sample's English
// tokens (`import requests`, `response.json()`) would otherwise swamp the
// character count for a mostly-Hebrew answer and flip the whole thing ltr.
// Each paragraph/heading/list item/quote picks its own direction from its own
// text instead, exactly like the reading order already treats them as blocks.
function directional(Tag: "p" | "li" | "h1" | "h2" | "h3" | "h4" | "h5" | "h6" | "blockquote") {
  return function DirectionalBlock({ children }: { children?: ReactNode }) {
    return <Tag dir={textDirection(plainText(children))}>{children}</Tag>;
  };
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
          // Code stays ltr regardless (globals.css), so it needs no direction.
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          table: ({ children }) => (
            <div className="dq-table-scroll">
              <table>{children}</table>
            </div>
          ),
          p: directional("p"),
          li: directional("li"),
          h1: directional("h1"),
          h2: directional("h2"),
          h3: directional("h3"),
          h4: directional("h4"),
          h5: directional("h5"),
          h6: directional("h6"),
          blockquote: directional("blockquote"),
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

function thumbBtn(): React.CSSProperties {
  return {
    alignItems: "center",
    background: "var(--bg-3)",
    border: "1px solid var(--border)",
    borderRadius: "5px",
    color: "var(--fg-dimmer)",
    cursor: "pointer",
    display: "flex",
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

function PencilIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M11.2 2.3a1.6 1.6 0 0 1 2.3 2.3l-7.6 7.6-3 .7.7-3 7.6-7.6z" />
      <path d="M10.1 3.4l2.3 2.3" />
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
