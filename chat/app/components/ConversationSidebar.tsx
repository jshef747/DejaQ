"use client";

import type { StoredConversation } from "./conversation-store";

interface Props {
  conversations: StoredConversation[];
  activeId: string | null;
  onSelect: (conv: StoredConversation) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export default function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: Props) {
  return (
    <aside
      style={{
        background: "var(--bg-2)",
        borderRight: "1px solid var(--border-2)",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        overflow: "hidden",
        width: "220px",
      }}
    >
      {/* New conversation button at top of sidebar */}
      <div style={{ borderBottom: "1px solid var(--border)", padding: "10px" }}>
        <button
          onClick={onNew}
          style={{
            alignItems: "center",
            background: "var(--bg-3)",
            border: "1px solid var(--border)",
            borderRadius: "6px",
            color: "var(--fg)",
            cursor: "pointer",
            display: "flex",
            fontSize: "12px",
            fontWeight: 500,
            gap: "6px",
            justifyContent: "center",
            padding: "7px 12px",
            transition: "background 0.1s, border-color 0.1s",
            width: "100%",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--bg-hover)";
            e.currentTarget.style.borderColor = "var(--border-2)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "var(--bg-3)";
            e.currentTarget.style.borderColor = "var(--border)";
          }}
        >
          <span style={{ color: "var(--accent)" }}><PlusIcon /></span>
          New chat
        </button>
      </div>

      {/* Scrollable list of past conversations */}
      <div style={{ flex: 1, overflowY: "auto", padding: "6px" }}>
        {conversations.length === 0 ? (
          <p
            style={{
              color: "var(--fg-dimmer)",
              fontSize: "11px",
              padding: "12px 8px",
              textAlign: "center",
            }}
          >
            No past conversations
          </p>
        ) : (
          conversations.map((conv) => (
            <ConversationRow
              key={conv.id}
              conv={conv}
              active={conv.id === activeId}
              onSelect={() => onSelect(conv)}
              onDelete={() => onDelete(conv.id)}
            />
          ))
        )}
      </div>
    </aside>
  );
}

// ─── Single conversation row ───────────────────────────────────────────────────

function ConversationRow({
  conv,
  active,
  onSelect,
  onDelete,
}: {
  conv: StoredConversation;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      style={{
        alignItems: "center",
        background: active ? "var(--accent-bg)" : "transparent",
        border: `1px solid ${active ? "var(--accent-border)" : "transparent"}`,
        borderRadius: "6px",
        cursor: "pointer",
        display: "flex",
        gap: "4px",
        marginBottom: "2px",
        padding: "6px 8px",
        transition: "background 0.1s",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.background = "var(--bg-3)";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.background = "transparent";
      }}
    >
      {/* Title and relative date */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <p
          style={{
            color: active ? "var(--accent)" : "var(--fg)",
            fontSize: "12px",
            fontWeight: active ? 500 : 400,
            margin: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {conv.title}
        </p>
        <p style={{ color: "var(--fg-dimmer)", fontSize: "10px", margin: "1px 0 0" }}>
          {formatRelativeDate(conv.lastUpdated)}
        </p>
      </div>

      {/* Delete button — faint by default, full opacity when hovered */}
      <button
        onClick={(e) => {
          e.stopPropagation(); // prevent triggering onSelect
          onDelete();
        }}
        style={{
          alignItems: "center",
          background: "transparent",
          border: "none",
          borderRadius: "3px",
          color: "var(--fg-dimmer)",
          cursor: "pointer",
          display: "flex",
          flexShrink: 0,
          opacity: 0.35,
          padding: "2px",
          transition: "opacity 0.1s",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = "1")}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = "0.35")}
        title="Delete conversation"
        aria-label="Delete conversation"
      >
        <SmallTrashIcon />
      </button>
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatRelativeDate(ts: number): string {
  const diff = Date.now() - ts;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ─── Icons ─────────────────────────────────────────────────────────────────────

function PlusIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M8 2v12M2 8h12" />
    </svg>
  );
}

function SmallTrashIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M2 4h12M5 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1M6 7v5M10 7v5M3 4l1 9a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l1-9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
