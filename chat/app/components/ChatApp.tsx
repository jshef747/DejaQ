"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  sendChatMessage,
  sendFeedback,
  isApiError,
  type FeedbackRating,
} from "./chat-api";
import {
  DEFAULT_CHAT_SETTINGS,
  loadSettings,
  persistSettings,
  type ChatSettings,
} from "./chat-store";
import {
  loadConversations,
  saveConversation,
  deleteConversation,
  titleFromMessages,
  type StoredConversation,
} from "./conversation-store";
import ChatMessage, { type AppMessage, type FeedbackPhase } from "./ChatMessage";
import ConversationSidebar from "./ConversationSidebar";
import MessageInput from "./MessageInput";
import SettingsModal from "./SettingsModal";
import TypingIndicator from "./TypingIndicator";
import ToastStack, { type ToastData } from "./Toast";

const WELCOME_PROMPTS = [
  "What are the main benefits of semantic caching for LLM APIs?",
  "Explain how transformer attention mechanisms work.",
  "What's the difference between RAG and fine-tuning?",
  "Summarize the trade-offs between local and cloud LLM inference.",
];

let msgCounter = 0;
function newId() {
  return `msg_${++msgCounter}_${Date.now()}`;
}

// ─── useWindowWidth hook ────────────────────────────────────────────────────

function useWindowWidth(): number {
  const [width, setWidth] = useState<number>(1200);
  useEffect(() => {
    setWidth(window.innerWidth);
    function onResize() { setWidth(window.innerWidth); }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

// ─── RequestInspector ──────────────────────────────────────────────────────────

interface InspectorProps {
  message: AppMessage | null;
  onClose: () => void;
  asDrawer: boolean;
}

type InspectorTone = "green" | "amber" | "red" | "blue" | "neutral";

function RequestInspector({ message, onClose, asDrawer }: InspectorProps) {
  const [copied, setCopied] = useState(false);
  const difficulty = difficultyMeta(message?.promptDifficulty, message?.cacheHit);

  function copyResponseId() {
    if (!message?.responseId) return;
    navigator.clipboard.writeText(message.responseId).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  const panelStyle: React.CSSProperties = asDrawer
    ? {
        background: "var(--bg-2)",
        borderTop: "1px solid var(--border-2)",
        bottom: 0,
        display: "flex",
        flexDirection: "column",
        left: 0,
        maxHeight: "48vh",
        position: "fixed",
        right: 0,
        zIndex: 40,
        boxShadow: "0 -4px 24px rgba(0,0,0,0.4)",
      }
    : {
        background: "#161616",
        borderLeft: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        minWidth: "320px",
        overflow: "hidden",
        width: "340px",
      };

  return (
    <aside style={panelStyle}>
      {/* Header */}
      <div
        style={{
          alignItems: "center",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          flexShrink: 0,
          gap: "8px",
          padding: asDrawer ? "12px 18px" : "12px 14px",
        }}
      >
        <span
          style={{
            color: "var(--fg-dim)",
            fontSize: "11px",
            fontWeight: 600,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          Request Inspector
        </span>
        <div style={{ flex: 1 }} />
        <button
          onClick={onClose}
          title="Close inspector"
          style={{
            alignItems: "center",
            background: "transparent",
            border: "none",
            borderRadius: "4px",
            color: "var(--fg-dimmer)",
            cursor: "pointer",
            display: "flex",
            fontSize: "14px",
            padding: "2px 6px",
          }}
          aria-label="Close inspector"
        >
          ✕
        </button>
      </div>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: asDrawer ? "14px 18px 18px" : "14px",
        }}
      >
        {!message ? (
          <p style={{ color: "var(--fg-dimmer)", fontSize: "12px", lineHeight: 1.5, margin: 0 }}>
            Click the inspect icon on an assistant message to view its metadata here.
          </p>
        ) : (
          <div style={{ display: "grid", gap: "12px" }}>
            <div
              style={{
                display: "grid",
                gap: "10px",
                gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
              }}
            >
              <MetricCard label="Cache">
                <StatusPill tone={message.cacheHit ? "green" : "amber"}>
                  {message.cacheHit ? "HIT" : "MISS"}
                </StatusPill>
              </MetricCard>
              <MetricCard label="Difficulty">
                <StatusPill tone={difficulty.tone}>{difficulty.label}</StatusPill>
              </MetricCard>
              <MetricCard label="Model" wide>
                <MonoValue>{message.modelUsed ?? "-"}</MonoValue>
              </MetricCard>
              <MetricCard label="Tier">
                <StatusPill tone={message.tier === "cache" ? "green" : message.tier === "external" ? "red" : "amber"}>
                  {message.tier?.toUpperCase() ?? "-"}
                </StatusPill>
              </MetricCard>
              <MetricCard label="Latency">
                <MonoValue>{message.latencyMs !== undefined ? `${message.latencyMs} ms` : "-"}</MonoValue>
              </MetricCard>
            </div>

            <InspectorSection title="Tokens">
              <div
                style={{
                  display: "grid",
                  gap: "10px",
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                }}
              >
                <TokenCount label="Prompt" value={message.promptTokens} />
                <TokenCount label="Completion" value={message.completionTokens} />
              </div>
            </InspectorSection>

            {message.responseId && (
              <InspectorSection
                title="Response ID"
                action={
                  <button
                    onClick={copyResponseId}
                    title="Copy response ID"
                    style={{
                      alignItems: "center",
                      background: copied ? "var(--green-bg)" : "var(--bg-3)",
                      border: `1px solid ${copied ? "rgba(34,197,94,0.3)" : "var(--border)"}`,
                      borderRadius: "4px",
                      color: copied ? "var(--green)" : "var(--fg-dimmer)",
                      cursor: "pointer",
                      display: "flex",
                      flexShrink: 0,
                      fontSize: "10px",
                      padding: "3px 7px",
                      transition: "background 0.15s, color 0.15s",
                    }}
                  >
                    {copied ? "Copied" : "Copy"}
                  </button>
                }
              >
                <span
                  style={{
                    color: "var(--fg-dim)",
                    display: "block",
                    fontFamily: "var(--font-jetbrains-mono, ui-monospace, 'SF Mono', Menlo, monospace)",
                    fontSize: "11px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={message.responseId}
                >
                  {message.responseId}
                </span>
              </InspectorSection>
            )}
            {message.interactionId && (
              <InspectorSection title="Interaction ID">
                <span
                  style={{
                    color: "var(--fg-dim)",
                    display: "block",
                    fontFamily: "var(--font-jetbrains-mono, ui-monospace, 'SF Mono', Menlo, monospace)",
                    fontSize: "11px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={message.interactionId}
                >
                  {message.interactionId}
                </span>
              </InspectorSection>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

function MetricCard({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div
      style={{
        background: "var(--bg-2)",
        border: "1px solid var(--border)",
        borderRadius: "7px",
        gridColumn: wide ? "span 2" : undefined,
        minWidth: 0,
        padding: "10px",
      }}
    >
      <InspectorLabel>{label}</InspectorLabel>
      <div style={{ marginTop: "6px", minWidth: 0 }}>{children}</div>
    </div>
  );
}

function TokenCount({ label, value }: { label: string; value?: number }) {
  return (
    <div
      style={{
        background: "#181818",
        border: "1px solid var(--border)",
        borderRadius: "6px",
        padding: "9px",
      }}
    >
      <InspectorLabel>{label}</InspectorLabel>
      <div
        style={{
          color: "var(--fg)",
          fontFamily: "var(--font-jetbrains-mono, ui-monospace, 'SF Mono', Menlo, monospace)",
          fontSize: "13px",
          marginTop: "5px",
        }}
      >
        {value ?? 0}
      </div>
    </div>
  );
}

function InspectorSection({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section
      style={{
        background: "var(--bg-2)",
        border: "1px solid var(--border)",
        borderRadius: "7px",
        padding: "10px",
      }}
    >
      <div style={{ alignItems: "center", display: "flex", gap: "8px", marginBottom: "8px" }}>
        <InspectorLabel>{title}</InspectorLabel>
        <div style={{ flex: 1 }} />
        {action}
      </div>
      {children}
    </section>
  );
}

function InspectorLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        color: "var(--fg-dimmer)",
        fontSize: "10px",
        fontWeight: 600,
        letterSpacing: "0.05em",
        textTransform: "uppercase",
      }}
    >
      {children}
    </div>
  );
}

function MonoValue({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        color: "var(--fg)",
        display: "block",
        fontFamily: "var(--font-jetbrains-mono, ui-monospace, 'SF Mono', Menlo, monospace)",
        fontSize: "12px",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}
      title={typeof children === "string" ? children : undefined}
    >
      {children}
    </span>
  );
}

function StatusPill({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone: InspectorTone;
}) {
  const toneStyles: Record<InspectorTone, React.CSSProperties> = {
    green: { background: "var(--green-bg)", border: "1px solid rgba(34,197,94,0.3)", color: "var(--green)" },
    amber: { background: "var(--amber-bg)", border: "1px solid var(--amber-border)", color: "var(--amber)" },
    red: { background: "var(--red-bg)", border: "1px solid var(--red-border)", color: "var(--red)" },
    blue: { background: "var(--blue-bg)", border: "1px solid var(--blue-border)", color: "var(--blue)" },
    neutral: { background: "var(--bg-3)", border: "1px solid var(--border)", color: "var(--fg-dim)" },
  };
  return (
    <span
      style={{
        borderRadius: "5px",
        display: "inline-flex",
        fontSize: "11px",
        fontWeight: 700,
        letterSpacing: "0.04em",
        maxWidth: "100%",
        padding: "3px 8px",
        ...toneStyles[tone],
      }}
    >
      {children}
    </span>
  );
}

function difficultyMeta(
  difficulty: string | null | undefined,
  cacheHit: boolean | undefined,
): { label: string; tone: InspectorTone } {
  const normalized = difficulty?.toLowerCase();
  if (normalized === "easy") return { label: "EASY", tone: "green" };
  if (normalized === "hard") return { label: "HARD", tone: "red" };
  if (cacheHit) return { label: "CACHED", tone: "blue" };
  return { label: "-", tone: "neutral" };
}

// ─── ChatApp ───────────────────────────────────────────────────────────────────

export default function ChatApp() {
  const [messages, setMessages] = useState<AppMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<ChatSettings>(DEFAULT_CHAT_SETTINGS);
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const [conversations, setConversations] = useState<StoredConversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [inspectedMsgId, setInspectedMsgId] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<AppMessage[]>([]);
  const windowWidth = useWindowWidth();
  const isNarrow = windowWidth < 1024;

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // Load settings and conversation history from localStorage on first render.
  useEffect(() => {
    setSettings(loadSettings());
    setConversations(loadConversations());
  }, []);

  // Scroll to the newest message whenever the list changes.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // Open settings automatically until the user picks a department.
  useEffect(() => {
    if (!settings.deptSlug) setSettingsOpen(true);
  }, [settings.deptSlug]);

  function addToast(kind: ToastData["kind"], message: string) {
    const id = `toast_${Date.now()}_${Math.random()}`;
    setToasts((prev) => [...prev, { id, kind, message }]);
  }

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  function saveSettings(next: ChatSettings) {
    persistSettings(next);
    setSettings(next);
  }

  // Persist the given messages under the given conversation ID and refresh sidebar.
  function persistConversation(convId: string, currentMessages: AppMessage[]) {
    const conv: StoredConversation = {
      id: convId,
      title: titleFromMessages(currentMessages),
      messages: currentMessages,
      lastUpdated: Date.now(),
    };
    saveConversation(conv);
    setConversations(loadConversations());
  }

  // Save the current conversation (if any) and start a blank slate.
  function startNewConversation() {
    if (messages.length > 0 && activeConvId) {
      persistConversation(activeConvId, messages);
    }
    setMessages([]);
    setActiveConvId(null);
    setInput("");
    setInspectedMsgId(null);
    setInspectorOpen(false);
  }

  // Load a conversation selected from the sidebar.
  function handleSelectConversation(conv: StoredConversation) {
    // Save the currently open conversation before switching away.
    if (messages.length > 0 && activeConvId) {
      persistConversation(activeConvId, messages);
    }
    setActiveConvId(conv.id);
    setMessages(conv.messages);
    setInput("");
    setInspectedMsgId(null);
    setInspectorOpen(false);
  }

  function handleDeleteConversation(id: string) {
    deleteConversation(id);
    setConversations(loadConversations());
    // If the deleted conversation was active, clear the chat area.
    if (id === activeConvId) {
      setMessages([]);
      setActiveConvId(null);
      setInspectedMsgId(null);
      setInspectorOpen(false);
    }
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || isLoading) return;
    if (!settings.deptSlug) {
      addToast("error", "Select a department in Settings to start chatting.");
      setSettingsOpen(true);
      return;
    }

    const userMsg: AppMessage = { id: newId(), role: "user", content: text, ts: Date.now() };

    // Capture snapshot before any state updates so async code works with stable refs.
    const preSendMessages = messages;
    const withUserMsg = [...preSendMessages, userMsg];

    setMessages(withUserMsg);
    setInput("");
    setIsLoading(true);

    // Pre-allocate the assistant message so we can append deltas in-place.
    const assistantId = newId();
    const assistantPlaceholder: AppMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      ts: Date.now(),
    };

    // Send the full conversation history so the model has context.
    const history = withUserMsg.map((m) => ({ role: m.role, content: m.content }));

    let firstDelta = true;
    const result = await sendChatMessage(
      history,
      settings.deptSlug,
      settings.modelProfile,
      settings.routingMode,
      (delta) => {
        if (firstDelta) {
          // Show the placeholder bubble and hide the typing indicator on first byte.
          firstDelta = false;
          setIsLoading(false);
          setMessages((prev) => [...prev, { ...assistantPlaceholder, content: delta }]);
        } else {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m))
          );
        }
      },
    );
    setIsLoading(false);

    if (isApiError(result)) {
      addToast("error", result.message);
      // Revert optimistic messages so the user can retry.
      setMessages(preSendMessages);
      setInput(text);
      return;
    }

    // Attach metadata to the assistant message now that the stream is complete.
    const finalMessages = await new Promise<AppMessage[]>((resolve) => {
      setMessages((prev) => {
        const updated = prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content: result.text || m.content,
                modelUsed: result.modelUsed,
                interactionId: result.interactionId,
                tier: result.tier,
                responseId: result.responseId,
                requestMessages: history,
                promptTokens: result.promptTokens,
                completionTokens: result.completionTokens,
                feedbackPhase: "idle" as const,
                latencyMs: result.latencyMs,
                cacheHit: result.cacheHit,
                promptDifficulty: result.promptDifficulty,
              }
            : m
        );
        resolve(updated);
        return updated;
      });
    });

    // Assign a conversation ID on the first reply and persist to localStorage.
    const convId = activeConvId ?? `conv_${Date.now()}`;
    if (!activeConvId) setActiveConvId(convId);
    persistConversation(convId, finalMessages);
  }

  function updateFeedbackPhase(msgId: string, phase: FeedbackPhase) {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, feedbackPhase: phase } : m))
    );
  }

  function persistCurrentMessages(nextMessages: AppMessage[]) {
    if (activeConvId) {
      persistConversation(activeConvId, nextMessages);
    }
  }

  function escalationToast(status: string | null | undefined): string | null {
    switch (status) {
      case "no_further_escalation":
        return "No higher answer tier is available for this response.";
      case "no_credential":
        return "No external provider credential is configured for a better answer.";
      case "provider_error":
        return "The higher answer tier failed. Feedback was still recorded.";
      case "timeout":
        return "The higher answer tier timed out. Feedback was still recorded.";
      case "message_mismatch":
        return "Could not re-answer because the saved request context no longer matches.";
      case "already_escalated":
        return "This answer was already escalated.";
      default:
        return null;
    }
  }

  async function handleFeedback(msgId: string, rating: FeedbackRating, comment: string) {
    const msg = messagesRef.current.find((m) => m.id === msgId);
    if (!msg?.responseId && !msg?.interactionId) return;

    updateFeedbackPhase(msgId, "submitting");

    const result = await sendFeedback(
      msg.responseId ?? null,
      msg.interactionId ?? null,
      msg.requestMessages ?? null,
      rating,
      comment,
      settings.deptSlug,
    );

    if (isApiError(result)) {
      updateFeedbackPhase(msgId, "error");
      addToast("error", `Feedback failed: ${result.message}`);
      return;
    }

    if (result.status === "deleted") {
      addToast("info", "Feedback recorded — the cached response was removed.");
    } else if (typeof result.newScore === "number") {
      addToast("success", `Feedback recorded. New score: ${result.newScore.toFixed(1)}`);
    } else {
      addToast("success", "Feedback recorded.");
    }

    const feedbackScore = typeof result.newScore === "number" ? result.newScore : null;
    const reanswered =
      rating === "negative" && result.escalatedResponse
        ? ({
            id: newId(),
            role: "assistant",
            content: result.escalatedResponse.content,
            ts: Date.now(),
            modelUsed: result.escalatedResponse.tier,
            interactionId: result.escalatedResponse.interactionId,
            tier: result.escalatedResponse.tier,
            responseId: result.escalatedResponse.responseId,
            requestMessages: msg.requestMessages,
            feedbackPhase: "idle",
            cacheHit: false,
            sourceLabel: `Re-answered by ${result.escalatedResponse.tier}`,
          } satisfies AppMessage)
        : null;

    const updatedMessages = messagesRef.current.map((m) =>
      m.id === msgId ? { ...m, feedbackPhase: rating, feedbackScore } : m
    );
    const nextMessages = reanswered ? [...updatedMessages, reanswered] : updatedMessages;
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    persistCurrentMessages(nextMessages);

    if (rating === "negative" && result.escalatedResponse) {
      addToast("success", `Re-answered by ${result.escalatedResponse.tier}.`);
      return;
    }

    const toast = escalationToast(result.escalationStatus);
    if (toast) addToast("info", toast);
  }

  function handleWelcomePrompt(prompt: string) {
    setInput(prompt);
  }

  function handleInspect(msgId: string) {
    if (inspectedMsgId === msgId && inspectorOpen) {
      // Toggle off if same message clicked again
      setInspectorOpen(false);
      setInspectedMsgId(null);
    } else {
      setInspectedMsgId(msgId);
      setInspectorOpen(true);
    }
  }

  const hasDepartment = Boolean(settings.deptSlug);
  const dashboardUrl = process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "http://localhost:3000/dashboard";
  const inspectedMessage = messages.find((m) => m.id === inspectedMsgId) ?? null;

  return (
    <div
      style={{
        background: "var(--bg)",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
      }}
    >
      {/* ── Header ── */}
      <header
        style={{
          alignItems: "center",
          background: "#181818",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          flexShrink: 0,
          gap: "10px",
          padding: "0 20px",
          height: "48px",
        }}
      >
        {/* Logo */}
        <div style={{ alignItems: "center", display: "flex", gap: "8px" }}>
          <div
            style={{
              alignItems: "center",
              background: "var(--accent)",
              borderRadius: "4px",
              color: "#0a0a0a",
              display: "flex",
              flexShrink: 0,
              fontFamily: "var(--font-mono)",
              fontSize: "11px",
              fontWeight: 700,
              height: "22px",
              justifyContent: "center",
              letterSpacing: "-1px",
              width: "22px",
            }}
          >
            Dq
          </div>
          <span style={{ fontSize: "14px", fontWeight: 600 }}>DejaQ Chat</span>
        </div>

        {/* Connection status badge */}
        <div
          style={{
            alignItems: "center",
            background: hasDepartment ? "var(--green-bg)" : "var(--bg-3)",
            border: `1px solid ${hasDepartment ? "rgba(34,197,94,0.3)" : "var(--border)"}`,
            borderRadius: "4px",
            color: hasDepartment ? "var(--green)" : "var(--fg-dim)",
            display: "flex",
            fontSize: "11px",
            gap: "5px",
            padding: "3px 8px",
          }}
        >
          <span
            style={{
              background: hasDepartment ? "var(--green)" : "var(--fg-dimmer)",
              borderRadius: "50%",
              display: "inline-block",
              height: "5px",
              width: "5px",
            }}
          />
          {hasDepartment ? `Department · ${settings.deptSlug}` : "No department"}
        </div>

        <div style={{ flex: 1 }} />

        {/* Inspector toggle button */}
        <button
          onClick={() => setInspectorOpen((v) => !v)}
          title={inspectorOpen ? "Hide inspector" : "Show request inspector"}
          style={{
            ...iconBtn(),
            color: inspectorOpen ? "var(--accent)" : "var(--fg-dim)",
            borderColor: inspectorOpen ? "var(--accent-border)" : "var(--border)",
            background: inspectorOpen ? "var(--accent-bg)" : "transparent",
          }}
        >
          <InspectorPanelIcon />
          <span>Inspector</span>
        </button>

        {/* Header action buttons */}
        <button
          onClick={() => setSettingsOpen(true)}
          title="Settings"
          style={iconBtn()}
        >
          <SettingsGearIcon />
          <span>Settings</span>
        </button>
        <a
          href={dashboardUrl}
          style={{
            ...iconBtn(),
            color: "var(--fg-dim)",
            textDecoration: "none",
            display: "flex",
            alignItems: "center",
            gap: "5px",
          }}
          title="Go to Dashboard"
        >
          <DashboardIcon />
          <span>Dashboard</span>
        </a>
      </header>

      {/* ── Body: sidebar + chat area + inspector (wide) ── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Conversation history sidebar */}
        <ConversationSidebar
          conversations={conversations}
          activeId={activeConvId}
          onSelect={handleSelectConversation}
          onNew={startNewConversation}
          onDelete={handleDeleteConversation}
        />

        {/* Main chat area: message list + input */}
        <div style={{ display: "flex", flex: 1, flexDirection: "column", overflow: "hidden" }}>
          {/* Message list */}
          <main
            style={{
              display: "flex",
              flex: 1,
              flexDirection: "column",
              overflowY: "auto",
              paddingTop: "16px",
            }}
          >
            {messages.length === 0 ? (
              <WelcomeScreen
                hasDepartment={hasDepartment}
                onOpenSettings={() => setSettingsOpen(true)}
                onSelectPrompt={handleWelcomePrompt}
              />
            ) : (
              <>
                {messages.map((msg) => (
                  <ChatMessage
                    key={msg.id}
                    message={msg}
                    onFeedback={handleFeedback}
                    onInspect={msg.role === "assistant" ? handleInspect : undefined}
                    inspected={msg.id === inspectedMsgId && inspectorOpen}
                  />
                ))}
                {isLoading && <TypingIndicator />}
              </>
            )}
            <div ref={bottomRef} />
          </main>

          {/* Message input */}
          <MessageInput
            value={input}
            onChange={setInput}
            onSend={handleSend}
            disabled={isLoading}
          />
        </div>

        {/* Request Inspector panel — right column on wide viewports */}
        {inspectorOpen && !isNarrow && (
          <RequestInspector
            message={inspectedMessage}
            onClose={() => { setInspectorOpen(false); setInspectedMsgId(null); }}
            asDrawer={false}
          />
        )}
      </div>

      {/* Request Inspector drawer — fixed bottom on narrow viewports */}
      {inspectorOpen && isNarrow && (
        <RequestInspector
          message={inspectedMessage}
          onClose={() => { setInspectorOpen(false); setInspectedMsgId(null); }}
          asDrawer={true}
        />
      )}

      {/* ── Overlays ── */}
      <SettingsModal
        open={settingsOpen}
        initialSettings={settings}
        onSave={saveSettings}
        onClose={() => setSettingsOpen(false)}
      />
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}

// ─── Welcome screen ────────────────────────────────────────────────────────────

function WelcomeScreen({
  hasDepartment,
  onOpenSettings,
  onSelectPrompt,
}: {
  hasDepartment: boolean;
  onOpenSettings: () => void;
  onSelectPrompt: (p: string) => void;
}) {
  return (
    <div
      style={{
        alignItems: "center",
        display: "flex",
        flex: 1,
        flexDirection: "column",
        gap: "28px",
        justifyContent: "center",
        padding: "40px 24px",
      }}
    >
      {/* Hero */}
      <div style={{ maxWidth: "460px", textAlign: "center" }}>
        <div
          style={{
            alignItems: "center",
            background: "var(--accent-bg)",
            border: "1px solid var(--accent-border)",
            borderRadius: "12px",
            display: "inline-flex",
            justifyContent: "center",
            marginBottom: "16px",
            padding: "14px",
          }}
        >
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
            <rect x="2" y="8" width="28" height="18" rx="4" stroke="var(--accent)" strokeWidth="2" />
            <circle cx="10" cy="17" r="2" fill="var(--accent)" />
            <circle cx="22" cy="17" r="2" fill="var(--accent)" />
            <path d="M16 8V4M12 4h8" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </div>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 8px" }}>
          Welcome to DejaQ Chat
        </h1>
        <p style={{ color: "var(--fg-dim)", fontSize: "13px", lineHeight: 1.6, margin: 0 }}>
          Your queries are semantically cached and intelligently routed — easy questions go local, hard
          ones reach your configured external provider. Repeated questions get instant cached answers.
        </p>
      </div>

      {/* Department warning */}
      {!hasDepartment && (
        <div
          style={{
            alignItems: "center",
            borderLeft: "2px solid var(--amber-border)",
            borderRadius: "3px",
            display: "flex",
            gap: "8px",
            maxWidth: "460px",
            padding: "8px 12px",
            width: "100%",
          }}
        >
          <span
            style={{
              background: "var(--amber)",
              borderRadius: "50%",
              display: "inline-block",
              flexShrink: 0,
              height: "5px",
              width: "5px",
            }}
          />
          <span style={{ color: "var(--fg-dim)", flex: 1, fontSize: "12px", lineHeight: 1.45 }}>
            Select a department to start chatting.{" "}
            <button
              onClick={onOpenSettings}
              style={{
                background: "none",
                border: "none",
                color: "var(--accent)",
                cursor: "pointer",
                fontSize: "12px",
                padding: 0,
                textDecoration: "underline",
                textDecorationColor: "var(--accent-border)",
                textUnderlineOffset: "2px",
              }}
            >
              Open settings
            </button>
          </span>
        </div>
      )}

      {/* Example prompts */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "8px",
          maxWidth: "460px",
          width: "100%",
        }}
      >
        <p
          style={{
            color: "var(--fg-dimmer)",
            fontSize: "11px",
            letterSpacing: "0.06em",
            margin: "0 0 4px",
            textTransform: "uppercase",
          }}
        >
          Try asking
        </p>
        {WELCOME_PROMPTS.map((prompt) => (
          <button
            key={prompt}
            onClick={() => onSelectPrompt(prompt)}
            disabled={!hasDepartment}
            style={{
              background: "var(--bg-2)",
              border: "1px solid var(--border)",
              borderRadius: "8px",
              color: hasDepartment ? "var(--fg)" : "var(--fg-dimmer)",
              cursor: hasDepartment ? "pointer" : "not-allowed",
              fontSize: "13px",
              lineHeight: 1.5,
              padding: "10px 14px",
              textAlign: "left",
              transition: "border-color 0.15s, background 0.15s",
            }}
            onMouseEnter={(e) => {
              if (hasDepartment) {
                (e.currentTarget as HTMLButtonElement).style.background = "var(--bg-3)";
                (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border-2)";
              }
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = "var(--bg-2)";
              (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--border)";
            }}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Style helpers ─────────────────────────────────────────────────────────────

function iconBtn(): React.CSSProperties {
  return {
    alignItems: "center",
    background: "transparent",
    border: "1px solid var(--border)",
    borderRadius: "5px",
    color: "var(--fg-dim)",
    cursor: "pointer",
    display: "flex",
    fontSize: "12px",
    gap: "5px",
    padding: "4px 8px",
  };
}

// ─── Header icons ──────────────────────────────────────────────────────────────

function SettingsGearIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="8" r="2.5" />
      <path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3.05 3.05l1.06 1.06M11.89 11.89l1.06 1.06M3.05 12.95l1.06-1.06M11.89 4.11l1.06-1.06" strokeLinecap="round" />
    </svg>
  );
}

function DashboardIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="1" y="1" width="6" height="6" rx="1" />
      <rect x="9" y="1" width="6" height="6" rx="1" />
      <rect x="1" y="9" width="6" height="6" rx="1" />
      <rect x="9" y="9" width="6" height="6" rx="1" />
    </svg>
  );
}

function InspectorPanelIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="1" y="1" width="9" height="14" rx="1.5" />
      <rect x="12" y="1" width="3" height="14" rx="1" />
      <path d="M4 5h4M4 8h4M4 11h2" strokeLinecap="round" />
    </svg>
  );
}
