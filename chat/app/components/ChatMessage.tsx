"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { FeedbackRating } from "./chat-api";

// The full feedback lifecycle for a single assistant message.
// "idle"/"error" are re-enabled states; "submitting" is in-flight; the rest are terminal.
export type FeedbackPhase = "idle" | "submitting" | "positive" | "negative" | "error";

export interface AppMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  ts: number;
  // Assistant-only fields:
  modelUsed?: string | null;
  responseId?: string | null;
  promptTokens?: number;
  completionTokens?: number;
  feedbackPhase?: FeedbackPhase;
  latencyMs?: number;
  cacheHit?: boolean;
  promptDifficulty?: string | null;
}

interface Props {
  message: AppMessage;
  // Parent handles the API call and updates feedbackPhase on the message.
  onFeedback: (messageId: string, rating: FeedbackRating, comment: string) => Promise<void>;
  onInspect?: (messageId: string) => void;
  inspected?: boolean;
}

// ─── Model source classification ──────────────────────────────────────────────

// The server sends "cache" for cache hits; external models use well-known
// vendor prefixes (gemini-, gpt-, claude-, o4-, etc.); everything else is local.
type ModelSource = "cache" | "local" | "external";

function classifyModelSource(modelUsed: string | null | undefined): ModelSource {
  if (!modelUsed || modelUsed === "cache") return "cache";
  const m = modelUsed.toLowerCase();
  if (
    m.startsWith("gemini-") ||
    m.startsWith("gpt-") ||
    m.startsWith("claude-") ||
    m.startsWith("o1-") ||
    m.startsWith("o3-") ||
    m.startsWith("o4-")
  ) {
    return "external";
  }
  return "local";
}

// Color scheme: green = cache hit, amber = local model, red = external provider.
function modelBadgeStyle(source: ModelSource): React.CSSProperties {
  const base: React.CSSProperties = {
    borderRadius: "4px",
    fontFamily: "var(--font-mono)",
    fontSize: "10px",
    padding: "2px 6px",
  };
  if (source === "cache") {
    return {
      ...base,
      background: "var(--green-bg)",
      border: "1px solid rgba(34,197,94,0.3)",
      color: "var(--green)",
    };
  }
  if (source === "external") {
    return {
      ...base,
      background: "var(--red-bg)",
      border: "1px solid var(--red-border)",
      color: "var(--red)",
    };
  }
  // local model
  return {
    ...base,
    background: "var(--amber-bg)",
    border: "1px solid var(--amber-border)",
    color: "var(--amber)",
  };
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function ChatMessage({ message, onFeedback, onInspect, inspected }: Props) {
  const isUser = message.role === "user";
  const phase = message.feedbackPhase ?? "idle";

  // Immediately submit feedback without a comment or confirmation step.
  async function handleFeedbackClick(rating: FeedbackRating) {
    if (phase !== "idle" && phase !== "error") return;
    await onFeedback(message.id, rating, "");
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: isUser ? "flex-end" : "flex-start",
        gap: "4px",
        padding: "0 24px 16px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: "10px",
          maxWidth: "82%",
          flexDirection: isUser ? "row-reverse" : "row",
        }}
      >
        {/* Avatar */}
        <div
          style={{
            alignItems: "center",
            background: isUser ? "var(--accent-bg)" : "var(--bg-3)",
            border: `1px solid ${isUser ? "var(--accent-border)" : "var(--border)"}`,
            borderRadius: "50%",
            color: isUser ? "var(--accent)" : "var(--fg-dim)",
            display: "flex",
            flexShrink: 0,
            fontSize: "10px",
            fontWeight: 700,
            height: "28px",
            justifyContent: "center",
            width: "28px",
          }}
        >
          {isUser ? "U" : <BotIcon />}
        </div>

        {/* Message bubble */}
        <div
          style={{
            background: isUser ? "var(--accent-bg)" : "var(--bg-2)",
            border: `1px solid ${isUser ? "var(--accent-border)" : inspected ? "var(--accent-border)" : "var(--border)"}`,
            borderRadius: isUser ? "12px 12px 3px 12px" : "12px 12px 12px 3px",
            color: "var(--fg)",
            fontSize: "13px",
            lineHeight: 1.6,
            padding: "10px 14px",
            whiteSpace: isUser ? "pre-wrap" : "normal",
            wordBreak: "break-word",
          }}
        >
          {isUser ? message.content : <MarkdownContent content={message.content} />}
        </div>
      </div>

      {/* Metadata row — color-coded model badge + token count + timestamp */}
      {!isUser && (
        <div
          style={{
            alignItems: "center",
            display: "flex",
            gap: "8px",
            paddingLeft: "38px", // aligns under the bubble (avatar 28px + gap 10px)
          }}
        >
          {message.modelUsed !== undefined && (
            <span style={modelBadgeStyle(classifyModelSource(message.modelUsed))}>
              {message.modelUsed ?? "cache"}
            </span>
          )}
          {(message.promptTokens !== undefined || message.completionTokens !== undefined) && (
            <span style={{ color: "var(--fg-dimmer)", fontFamily: "var(--font-mono)", fontSize: "10px" }}>
              {(message.promptTokens ?? 0) + (message.completionTokens ?? 0)} tok
            </span>
          )}
          <span style={{ color: "var(--fg-dimmer)", fontSize: "10px" }}>
            {formatTs(message.ts)}
          </span>
          {/* Inspect button for assistant messages */}
          {onInspect && (
            <button
              onClick={() => onInspect(message.id)}
              title={inspected ? "Currently inspecting" : "Inspect request metadata"}
              style={{
                alignItems: "center",
                background: inspected ? "var(--accent-bg)" : "transparent",
                border: `1px solid ${inspected ? "var(--accent-border)" : "var(--border)"}`,
                borderRadius: "4px",
                color: inspected ? "var(--accent)" : "var(--fg-dimmer)",
                cursor: "pointer",
                display: "flex",
                padding: "2px 5px",
                transition: "background 0.15s, border-color 0.15s, color 0.15s",
              }}
              aria-label="Inspect request metadata"
            >
              <InspectIcon />
            </button>
          )}
        </div>
      )}

      {/* Feedback row — icon-only thumbs, no comment box, immediate submit on click */}
      {!isUser && message.responseId && (
        <div style={{ alignItems: "center", display: "flex", gap: "4px", paddingLeft: "38px" }}>
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
        </div>
      )}

      {/* Timestamp for user messages */}
      {isUser && (
        <span style={{ color: "var(--fg-dimmer)", fontSize: "10px", paddingRight: "38px" }}>
          {formatTs(message.ts)}
        </span>
      )}
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="dq-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer">
              {children}
            </a>
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
    borderRadius: "4px",
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
    border: `1px solid ${ok ? "rgba(34,197,94,0.3)" : "var(--red-border)"}`,
    borderRadius: "4px",
    color: ok ? "var(--green)" : "var(--red)",
    display: "flex",
    padding: "4px 6px",
  };
}

// ─── Icons ─────────────────────────────────────────────────────────────────────

function BotIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="4" width="12" height="10" rx="2" />
      <circle cx="5.5" cy="9" r="1" fill="currentColor" stroke="none" />
      <circle cx="10.5" cy="9" r="1" fill="currentColor" stroke="none" />
      <path d="M6 12h4M8 4V2M6 2h4" strokeLinecap="round" />
    </svg>
  );
}

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
