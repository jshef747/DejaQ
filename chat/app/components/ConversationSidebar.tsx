"use client";

import type { StoredConversation } from "./conversation-store";
import { classifyRoute, ROUTE_STYLE } from "./provenance";
import { useNewChatShortcutLabel } from "./shortcuts";
import { textDirection } from "./text-direction";

// Below this window width the sidebar gives up its width rather than the
// reading column's measure — narrow windows lose margins, never measure.
export const SIDEBAR_COLLAPSE_WIDTH = 1100;
const SIDEBAR_WIDTH = 272;
const SIDEBAR_RAIL_WIDTH = 56;

interface Props {
  conversations: StoredConversation[];
  activeId: string | null;
  onSelect: (conv: StoredConversation) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onOpenSettings: () => void;
  // Department slug from Settings — the only workspace-identity string the
  // chat app actually has (it has no separate workspace-name endpoint).
  deptSlug: string;
  connected: boolean;
  collapsed: boolean;
  // Conversations with an answer still generating. Navigating away from one is
  // allowed, so this is how a user who did knows an answer is still coming.
  generatingIds: string[];
}

export default function ConversationSidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onOpenSettings,
  deptSlug,
  connected,
  collapsed,
  generatingIds,
}: Props) {
  const shortcut = useNewChatShortcutLabel();

  if (collapsed) {
    return (
      <CollapsedRail
        onNew={connected ? onNew : undefined}
        onOpenSettings={onOpenSettings}
        deptSlug={deptSlug}
        shortcut={shortcut}
        working={generatingIds.length > 0}
      />
    );
  }

  const groups = groupConversations(conversations);

  return (
    <aside
      style={{
        background: "var(--bg-2)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        overflow: "hidden",
        width: `${SIDEBAR_WIDTH}px`,
      }}
    >
      <div style={{ padding: "12px 12px 8px" }}>
        <button
          onClick={onNew}
          disabled={!connected}
          style={{
            alignItems: "center",
            background: "var(--bg-3)",
            border: `1px solid var(--border-2)`,
            borderRadius: "9px",
            color: "var(--fg)",
            cursor: connected ? "pointer" : "not-allowed",
            display: "flex",
            fontSize: "13px",
            fontWeight: 500,
            gap: "8px",
            height: "34px",
            opacity: connected ? 1 : 0.4,
            padding: "0 11px",
            transition: "background var(--t-base), border-color var(--t-base)",
            width: "100%",
          }}
          onMouseEnter={(e) => {
            if (connected) e.currentTarget.style.background = "var(--bg-hover)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "var(--bg-3)";
          }}
        >
          <span style={{ color: "var(--fg-dim)", display: "flex" }}>
            <PlusIcon />
          </span>
          <span style={{ flex: 1, textAlign: "left" }}>New chat</span>
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "4px 8px" }}>
        {!connected ? (
          <div style={{ alignItems: "center", display: "flex", height: "100%", justifyContent: "center", padding: "0 22px", textAlign: "center" }}>
            <p style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", lineHeight: "17px", margin: 0 }}>
              Connect a workspace to start.
            </p>
          </div>
        ) : conversations.length === 0 ? (
          <div style={{ alignItems: "center", display: "flex", height: "100%", justifyContent: "center", padding: "0 22px", textAlign: "center" }}>
            <div>
              <p style={{ color: "var(--fg-dim)", fontSize: "12.5px", margin: 0 }}>No chats yet</p>
              <p style={{ color: "var(--fg-dimmer)", fontSize: "11.5px", lineHeight: "17px", margin: "5px 0 0" }}>
                Your conversations stay in this browser.
              </p>
            </div>
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.label}>
              <div
                style={{
                  color: "var(--fg-dimmer)",
                  fontSize: "10.5px",
                  fontWeight: 600,
                  letterSpacing: "0.10em",
                  padding: "10px 8px 6px",
                  textTransform: "uppercase",
                }}
              >
                {group.label}
              </div>
              {group.items.map((conv) => (
                <ConversationRow
                  key={conv.id}
                  conv={conv}
                  active={conv.id === activeId}
                  working={generatingIds.includes(conv.id)}
                  onSelect={() => onSelect(conv)}
                  onDelete={() => onDelete(conv.id)}
                />
              ))}
            </div>
          ))
        )}
      </div>

      <WorkspaceFooter deptSlug={deptSlug} connected={connected} onOpenSettings={onOpenSettings} />
    </aside>
  );
}

// ─── Grouping ───────────────────────────────────────────────────────────────

interface ConversationGroup {
  label: string;
  items: StoredConversation[];
}

function groupConversations(conversations: StoredConversation[]): ConversationGroup[] {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const todayCutoff = startOfToday.getTime();

  const today: StoredConversation[] = [];
  const earlier: StoredConversation[] = [];
  for (const conv of conversations) {
    (conv.lastUpdated >= todayCutoff ? today : earlier).push(conv);
  }

  const groups: ConversationGroup[] = [];
  if (today.length > 0) groups.push({ label: "Today", items: today });
  if (earlier.length > 0) groups.push({ label: "Earlier", items: earlier });
  return groups;
}

// ─── Single conversation row ───────────────────────────────────────────────────

function ConversationRow({
  conv,
  active,
  working,
  onSelect,
  onDelete,
}: {
  conv: StoredConversation;
  active: boolean;
  working: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      style={{
        alignItems: "center",
        background: active ? "var(--bg-3)" : "transparent",
        borderRadius: "9px",
        cursor: "pointer",
        display: "flex",
        gap: "4px",
        marginBottom: "2px",
        padding: "9px 10px 9px 12px",
        position: "relative",
        transition: "background var(--t-fast)",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.background = "var(--bg-3)";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.background = "transparent";
      }}
    >
      {active && (
        <span
          aria-hidden
          style={{
            background: "var(--fg)",
            borderRadius: "2px",
            bottom: "9px",
            left: 0,
            position: "absolute",
            top: "9px",
            width: "2.5px",
          }}
        />
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <p
          dir={textDirection(conv.title)}
          style={{
            color: active ? "var(--fg)" : "var(--fg-dim)",
            fontSize: "13px",
            fontWeight: active ? 500 : 400,
            margin: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {conv.title}
        </p>
        <div style={{ alignItems: "center", display: "flex", gap: "7px", marginTop: "6px" }}>
          {working ? (
            <>
              <WorkingDot />
              <p style={{ color: "var(--fg-dim)", fontSize: "11px", margin: 0 }}>Still answering…</p>
            </>
          ) : (
            <>
              <RouteDashes conv={conv} />
              <p style={{ color: "var(--fg-dimmer)", fontSize: "11px", margin: 0 }}>
                {formatRelativeDate(conv.lastUpdated)}
              </p>
            </>
          )}
        </div>
      </div>

      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        style={{
          alignItems: "center",
          background: "transparent",
          border: "none",
          borderRadius: "5px",
          color: "var(--fg-dimmer)",
          cursor: "pointer",
          display: "flex",
          flexShrink: 0,
          opacity: 0.35,
          padding: "3px",
          transition: "opacity var(--t-fast)",
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

// The same colour vocabulary as the provenance rail, compressed to a row of
// dashes: one per assistant turn, in order, so a glance says which chats
// spent money. Capped so a long conversation doesn't overrun the row.
const MAX_DASHES = 6;

function RouteDashes({ conv }: { conv: StoredConversation }) {
  const dashes = (Array.isArray(conv.messages) ? conv.messages : [])
    .filter((m) => m.role === "assistant")
    .map((m) => classifyRoute(m.tier, m.modelUsed))
    .filter((route) => route !== null)
    .slice(0, MAX_DASHES);
  if (dashes.length === 0) return null;
  return (
    <div style={{ display: "flex", gap: "3px" }}>
      {dashes.map((route, i) => (
        <span
          key={i}
          style={{
            background: ROUTE_STYLE[route].solid,
            borderRadius: "2px",
            height: "3px",
            width: "12px",
          }}
        />
      ))}
    </div>
  );
}

// ─── Workspace footer ───────────────────────────────────────────────────────

function WorkspaceFooter({
  deptSlug,
  connected,
  onOpenSettings,
}: {
  deptSlug: string;
  connected: boolean;
  onOpenSettings: () => void;
}) {
  const initials = connected && deptSlug ? deptSlug.slice(0, 2).toUpperCase() : "";
  return (
    <div style={{ alignItems: "center", borderTop: "1px solid var(--border)", display: "flex", flexShrink: 0, gap: "10px", padding: "12px 14px" }}>
      <div
        style={{
          alignItems: "center",
          background: "var(--bg-3)",
          border: connected ? "1px solid var(--border-2)" : "1px dashed var(--border-2)",
          borderRadius: "8px",
          color: "var(--fg-dim)",
          display: "flex",
          flexShrink: 0,
          fontSize: "11px",
          fontWeight: 600,
          height: "28px",
          justifyContent: "center",
          width: "28px",
        }}
      >
        {initials}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        {connected ? (
          <div style={{ color: "var(--fg)", fontSize: "12.5px", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {deptSlug}
          </div>
        ) : (
          <div style={{ color: "var(--fg-dimmer)", fontSize: "12.5px" }}>Not connected</div>
        )}
      </div>
      {connected && (
        <button
          onClick={onOpenSettings}
          title="Settings"
          aria-label="Settings"
          style={{
            alignItems: "center",
            background: "transparent",
            border: "none",
            borderRadius: "8px",
            color: "var(--fg-dimmer)",
            cursor: "pointer",
            display: "flex",
            flexShrink: 0,
            height: "30px",
            justifyContent: "center",
            width: "30px",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-3)")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        >
          <SettingsGearIcon />
        </button>
      )}
    </div>
  );
}

// ─── Collapsed rail (< SIDEBAR_COLLAPSE_WIDTH) ─────────────────────────────

// A row's answer is still generating. The dashes it replaces describe finished
// turns, so the two never need to show at once.
function WorkingDot() {
  return (
    <span
      aria-hidden
      className="dq-working-dot"
      style={{ background: "var(--fg-dim)", borderRadius: "999px", flexShrink: 0, height: "6px", width: "6px" }}
    />
  );
}

function CollapsedRail({
  onNew,
  onOpenSettings,
  deptSlug,
  shortcut,
  working,
}: {
  onNew?: () => void;
  onOpenSettings: () => void;
  deptSlug: string;
  shortcut: string;
  // No conversation rows exist at this width, so the rail can only report that
  // something is still generating, not which one.
  working: boolean;
}) {
  return (
    <aside
      style={{
        alignItems: "center",
        background: "var(--bg-2)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        gap: "10px",
        padding: "12px 0",
        width: `${SIDEBAR_RAIL_WIDTH}px`,
      }}
    >
      <div
        aria-hidden
        style={{ background: "var(--fg-dim)", borderRadius: "7px", flexShrink: 0, height: "24px", width: "24px" }}
      />
      <button
        onClick={onNew}
        disabled={!onNew}
        title={`New chat (${shortcut})`}
        aria-label="New chat"
        style={{
          alignItems: "center",
          background: "var(--bg-3)",
          border: "1px solid var(--border-2)",
          borderRadius: "8px",
          color: onNew ? "var(--fg)" : "var(--fg-dimmer)",
          cursor: onNew ? "pointer" : "not-allowed",
          display: "flex",
          height: "30px",
          justifyContent: "center",
          opacity: onNew ? 1 : 0.4,
          width: "30px",
        }}
      >
        <PlusIcon />
      </button>
      {working && (
        <div title="An answer is still generating">
          <WorkingDot />
        </div>
      )}
      <div style={{ flex: 1 }} />
      <button
        onClick={onOpenSettings}
        title={deptSlug ? `Settings — ${deptSlug}` : "Settings"}
        aria-label="Settings"
        style={{
          alignItems: "center",
          background: "transparent",
          border: "none",
          borderRadius: "8px",
          color: "var(--fg-dimmer)",
          cursor: "pointer",
          display: "flex",
          height: "30px",
          justifyContent: "center",
          width: "30px",
        }}
      >
        <SettingsGearIcon />
      </button>
    </aside>
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
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round">
      <path d="M8 3v10M3 8h10" />
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

function SettingsGearIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M2.5 4.5h11M2.5 11.5h11" />
      <circle cx="5.8" cy="4.5" r="1.9" fill="var(--bg-2)" />
      <circle cx="10.4" cy="11.5" r="1.9" fill="var(--bg-2)" />
    </svg>
  );
}
