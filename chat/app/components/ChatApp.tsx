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
  type Attachment,
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
import ResponseDetail from "./ResponseDetail";
import SettingsModal from "./SettingsModal";
import TypingIndicator from "./TypingIndicator";
import ToastStack, { type ToastData } from "./Toast";
import { RailTrack } from "./ReadingColumn";
import { classifyRoute, type Route } from "./provenance";

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

// The response detail panel floats above the layout and reserves no room in
// it, so opening it cannot move or rewrap anything: the reading column, the
// sidebar and the composer are laid out identically whether it is open or
// shut. Every attempt to carve space out instead ended up narrowing the very
// measure the panel exists to explain. It covers the right margin, and the
// gutter before it, which is the accepted cost. Below DRAWER_MAX_WIDTH it
// becomes the bottom sheet.
const DRAWER_MAX_WIDTH = 1024;

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

// ─── ChatApp ───────────────────────────────────────────────────────────────────

export default function ChatApp() {
  const [messages, setMessages] = useState<AppMessage[]>([]);
  const [input, setInput] = useState("");
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<ChatSettings>(DEFAULT_CHAT_SETTINGS);
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const [conversations, setConversations] = useState<StoredConversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [inspectedMsgId, setInspectedMsgId] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  // The route/model become known as soon as headers land, well before the
  // first content delta — the wait strip narrates from this. sinceMs is set
  // the instant the route resolves, so the rail's elapsed counter reflects
  // actual generation time, not time spent waiting on the cache lookup.
  const [waitRoute, setWaitRoute] = useState<Route | null>(null);
  const [waitModel, setWaitModel] = useState<string | null>(null);
  const [waitSinceMs, setWaitSinceMs] = useState<number | null>(null);
  // A client-side rolling average of this session's non-cache latencies —
  // the only source for "if generated" in the response detail panel. No
  // server field for it; empty until the session has a generated answer.
  const [baselineLatencies, setBaselineLatencies] = useState<number[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<AppMessage[]>([]);
  const windowWidth = useWindowWidth();
  const isNarrow = windowWidth < DRAWER_MAX_WIDTH;

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
    setAttachment(null);
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
    // The pin belongs to the conversation it was attached in. A stored
    // conversation never carries one back (see the note in handleSend), so
    // switching always drops it rather than silently re-sending the old file.
    setAttachment(null);
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
      setAttachment(null);
      setInspectedMsgId(null);
      setInspectorOpen(false);
    }
  }

  async function handleSend() {
    const text = input.trim();
    if ((!text && !attachment) || isLoading) return;
    if (!settings.deptSlug) {
      addToast("error", "Select a department in Settings to start chatting.");
      setSettingsOpen(true);
      return;
    }

    // The backend needs a non-empty query; default one for attachment-only sends.
    const sentAttachment = attachment;
    const queryText =
      text ||
      (sentAttachment && sentAttachment.kind !== "image"
        ? "What is in this document?"
        : "What is in this image?");
    const userMsg: AppMessage = {
      id: newId(),
      role: "user",
      content: queryText,
      ts: Date.now(),
      imageUrl: sentAttachment?.kind === "image" ? sentAttachment.dataUrl : null,
      fileName:
        sentAttachment && sentAttachment.kind !== "image"
          ? sentAttachment.name || "Document"
          : null,
      // Distinguishes the turn that uploaded the file from the turns that
      // re-sent it, so the transcript shows which is which.
      attachmentSticky: sentAttachment?.sticky ?? false,
    };

    // Capture snapshot before any state updates so async code works with stable refs.
    const preSendMessages = messages;
    const withUserMsg = [...preSendMessages, userMsg];

    setMessages(withUserMsg);
    setInput("");
    // The attachment is NOT cleared here. It stays pinned so every follow-up
    // carries it: without that, turn 2 goes to /v1/chat/completions with no file
    // at all — the model answers from its own previous reply, and the answer is
    // stored as an ungated plain-text entry that a different document could
    // later match. The pin is dropped only by Unpin or a conversation switch.
    // ponytail: pin lives in memory only. A 10MB base64 data URL does not fit in
    // localStorage, so a reload means re-attaching; persist small ones if
    // surviving a reload is ever asked for.
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

    setWaitRoute(null);
    setWaitModel(null);
    setWaitSinceMs(null);

    let firstDelta = true;
    // The route/model arrive with the headers, before the first delta. The
    // placeholder carries them from birth so the rail marker is never drawn
    // in a route the answer didn't take while the stream replays.
    let streamMeta: { modelUsed: string | null; tier: "cache" | "local" | "external" | null } | null = null;
    const result = await sendChatMessage(
      history,
      settings.deptSlug,
      settings.modelProfile,
      settings.routingMode,
      sentAttachment,
      (delta) => {
        if (firstDelta) {
          // Show the placeholder bubble and hide the typing indicator on first byte.
          firstDelta = false;
          setIsLoading(false);
          setMessages((prev) => [...prev, { ...assistantPlaceholder, ...streamMeta, content: delta }]);
        } else {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m))
          );
        }
      },
      (meta) => {
        // Headers land before the first delta, so the wait strip can name the
        // route and model while the answer is still generating.
        streamMeta = { modelUsed: meta.modelUsed, tier: meta.tier };
        const route = classifyRoute(meta.tier, meta.modelUsed);
        setWaitRoute(route);
        setWaitModel(meta.modelUsed);
        setWaitSinceMs(Date.now());
      },
    );
    setIsLoading(false);
    setWaitRoute(null);
    setWaitModel(null);
    setWaitSinceMs(null);

    if (isApiError(result)) {
      addToast("error", result.message);
      // Revert optimistic messages so the user can retry. The attachment needs
      // no restoring — it was never cleared — and a failed send leaves it
      // un-pinned, so a retry still reads as the first attempt.
      setMessages(preSendMessages);
      setInput(text);
      return;
    }

    // The assistant bubble is only ever created by the first delta, so a stream
    // that yields none leaves the finalization below mapping over a list with no
    // assistantId: it quietly no-ops and the user sees their own message, no
    // reply, and no error whatsoever. Observed live — a thinking model spent its
    // whole token budget on the scratchpad and returned an empty answer with
    // HTTP 200. Never fail silently here.
    if (firstDelta) {
      if (result.text) {
        setMessages((prev) => [...prev, { ...assistantPlaceholder, content: result.text }]);
      } else {
        addToast("error", "The model returned an empty answer. Try rephrasing, or switch routing to external.");
        setMessages(preSendMessages);
        setInput(text);
        return;
      }
      firstDelta = false;
    }

    // The send worked, so the attachment is now being carried rather than freshly
    // picked. Identity check because the user may have swapped in a different
    // file while this request was in flight — that one is still fresh.
    if (sentAttachment) {
      setAttachment((prev) => (prev === sentAttachment ? { ...prev, sticky: true } : prev));
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
                cacheDistance: result.cacheDistance,
                cacheMatchedQuery: result.cacheMatchedQuery,
              }
            : m
        );
        resolve(updated);
        return updated;
      });
    });

    // The response detail panel's "if generated" comparison is a rolling
    // average of this session's own non-cache latencies — never the cache
    // path itself, or every comparison would trivially be "1x".
    if (!result.cacheHit && result.latencyMs > 0) {
      setBaselineLatencies((prev) => [...prev, result.latencyMs]);
    }

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
    const messages = messagesRef.current;
    const msgIndex = messages.findIndex((m) => m.id === msgId);
    const msg = msgIndex >= 0 ? messages[msgIndex] : undefined;
    if (!msg?.responseId && !msg?.interactionId) return;

    // An escalation replay re-answers from requestMessages alone - role/content
    // history, never the attachment - so a blind re-answer to a document/image
    // question would get cached as an ungated text entry. Withhold the replay
    // for a turn whose preceding user message carried an attachment; feedback
    // (score adjustment / delete) is still recorded either way.
    const precedingUserMsg = [...messages.slice(0, msgIndex)].reverse().find((m) => m.role === "user");
    const isAttachmentAnchored = Boolean(precedingUserMsg?.imageUrl || precedingUserMsg?.fileName);

    updateFeedbackPhase(msgId, "submitting");

    const result = await sendFeedback(
      msg.responseId ?? null,
      msg.interactionId ?? null,
      isAttachmentAnchored ? null : msg.requestMessages ?? null,
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
  const baselineMs =
    baselineLatencies.length > 0
      ? baselineLatencies.reduce((sum, ms) => sum + ms, 0) / baselineLatencies.length
      : null;

  // The question as typed, for the "why it matched" diff — looked up from
  // the user turn immediately before the given assistant message.
  function typedQueryFor(message: AppMessage): string | null {
    const index = messages.findIndex((m) => m.id === message.id);
    if (index < 0) return null;
    return [...messages.slice(0, index)].reverse().find((m) => m.role === "user")?.content ?? null;
  }

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
          background: "var(--bg)",
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
              background: "var(--fg)",
              borderRadius: "4px",
              color: "var(--bg)",
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
            border: `1px solid ${hasDepartment ? "var(--green-border)" : "var(--border)"}`,
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

        {/* Response detail toggle button — neutral, not orange: it opens for
            every route, not just a cache hit. */}
        <button
          onClick={() => setInspectorOpen((v) => !v)}
          title={inspectorOpen ? "Hide response detail" : "Show response detail"}
          style={{
            ...iconBtn(),
            color: inspectorOpen ? "var(--fg)" : "var(--fg-dim)",
            borderColor: inspectorOpen ? "var(--border-2)" : "var(--border)",
            background: inspectorOpen ? "var(--bg-3)" : "transparent",
          }}
        >
          <InspectorPanelIcon />
          <span>Response detail</span>
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

        {/* Main chat area: message list + input. */}
        <div style={{ display: "flex", flex: 1, flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
          {/* Transcript region. This — not the whole column — is the response
              detail panel's positioning context, which is what keeps the panel
              off the composer: it can only ever span from below the header to
              the top of the input, so the attach control, the textarea and the
              send button stay visible and clickable at every width. */}
          <div
            style={{
              display: "flex",
              flex: 1,
              flexDirection: "column",
              minWidth: 0,
              overflow: "hidden",
              position: "relative",
            }}
          >
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
                <div style={{ position: "relative" }}>
                  <RailTrack />
                  {messages.map((msg) => (
                    <ChatMessage
                      key={msg.id}
                      message={msg}
                      onFeedback={handleFeedback}
                      onInspect={msg.role === "assistant" ? handleInspect : undefined}
                      inspected={msg.id === inspectedMsgId && inspectorOpen}
                      baselineMs={baselineMs}
                      baselineSampleCount={baselineLatencies.length}
                    />
                  ))}
                  {isLoading && <TypingIndicator route={waitRoute} modelUsed={waitModel} sinceMs={waitSinceMs} />}
                </div>
              )}
              <div ref={bottomRef} />
            </main>

            {/* Response detail panel — an overlay over the transcript here;
                below DRAWER_MAX_WIDTH it drops to a fixed bottom sheet instead
                (rendered outside this column so it isn't clipped by
                overflow:hidden here). */}
            {inspectorOpen && !isNarrow && (
              <ResponseDetail
                message={inspectedMessage}
                typedQuery={inspectedMessage ? typedQueryFor(inspectedMessage) : null}
                deptSlug={settings.deptSlug}
                baselineMs={baselineMs}
                baselineSampleCount={baselineLatencies.length}
                onClose={() => { setInspectorOpen(false); setInspectedMsgId(null); }}
                asDrawer={false}
              />
            )}
          </div>

          {/* Message input */}
          <MessageInput
            value={input}
            onChange={setInput}
            onSend={handleSend}
            disabled={isLoading}
            attachment={attachment}
            onAttachmentChange={setAttachment}
            onAttachmentError={(msg) => addToast("error", msg)}
          />
        </div>
      </div>

      {inspectorOpen && isNarrow && (
        <ResponseDetail
          message={inspectedMessage}
          typedQuery={inspectedMessage ? typedQueryFor(inspectedMessage) : null}
          deptSlug={settings.deptSlug}
          baselineMs={baselineMs}
          baselineSampleCount={baselineLatencies.length}
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
            background: "var(--bg-3)",
            border: "1px solid var(--border-2)",
            borderRadius: "12px",
            display: "inline-flex",
            justifyContent: "center",
            marginBottom: "16px",
            padding: "14px",
          }}
        >
          <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
            <rect x="2" y="8" width="28" height="18" rx="4" stroke="var(--fg-dim)" strokeWidth="2" />
            <circle cx="10" cy="17" r="2" fill="var(--fg-dim)" />
            <circle cx="22" cy="17" r="2" fill="var(--fg-dim)" />
            <path d="M16 8V4M12 4h8" stroke="var(--fg-dim)" strokeWidth="2" strokeLinecap="round" />
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
                color: "var(--fg)",
                cursor: "pointer",
                fontSize: "12px",
                fontWeight: 600,
                padding: 0,
                textDecoration: "underline",
                textDecorationColor: "var(--border-2)",
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
