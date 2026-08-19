"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  sendChatMessage,
  sendFeedback,
  saveEditedAnswer,
  isApiError,
  type FeedbackRating,
} from "./chat-api";
import { editLanded, editStatusNotice } from "./edit-draft";
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
import ConnectScreen from "./ConnectScreen";
import ConversationSidebar, { SIDEBAR_COLLAPSE_WIDTH } from "./ConversationSidebar";
import MessageInput from "./MessageInput";
import ResponseDetail from "./ResponseDetail";
import SettingsModal from "./SettingsModal";
import TypingIndicator from "./TypingIndicator";
import ToastStack, { type ToastAction, type ToastData, type ToastKind } from "./Toast";
import { RailTrack } from "./ReadingColumn";
import { classifyRoute, type Route } from "./provenance";
import { matchesNewChatShortcut } from "./shortcuts";

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

// The question a turn started from: the given message if it is the question
// itself, otherwise the nearest one above it. Both the retry itself and the
// decision to offer it read the turn through this, so neither can end up
// judging one message and re-running another.
function turnQuestionIndex(messages: AppMessage[], index: number): number {
  for (let i = index; i >= 0; i--) {
    if (messages[i].role === "user") return i;
  }
  return -1;
}

// A conversation with nothing in it yet. Shared instance so the empty
// transcript keeps a stable identity across renders and the effects that
// depend on it do not re-run for a conversation that has not changed.
const NO_MESSAGES: AppMessage[] = [];

// What one in-flight answer looks like from the outside. Generation is tracked
// per conversation, not once for the app: a send belongs to the conversation
// that asked, and the user is free to navigate away from it while it runs, so
// a single global flag cannot describe two conversations where only one is
// working.
interface GenerationState {
  // No content delta has landed yet, so the wait strip is still up. The
  // whole record's presence, not this flag, means "generating".
  waiting: boolean;
  route: Route | null;
  model: string | null;
  sinceMs: number | null;
}

// The mutable half of the same send, reached synchronously from the stream
// callbacks — they cannot wait for a render to know they have been cancelled.
interface LiveSend {
  assistantId: string;
  controller: AbortController;
  cancelled: boolean;
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
  // Every conversation this session has open or in flight, keyed by id. The
  // visible transcript is whichever one activeConvId names; a send writes to
  // the id it captured when it started, so an answer always lands in the
  // conversation that asked for it even when that is not the one on screen.
  const [transcripts, setTranscripts] = useState<Record<string, AppMessage[]>>({});
  // Conversations currently generating, keyed by the same id.
  const [generating, setGenerating] = useState<Record<string, GenerationState>>({});
  const [input, setInput] = useState("");
  const [attachment, setAttachment] = useState<Attachment | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<ChatSettings>(DEFAULT_CHAT_SETTINGS);
  // Settings load from localStorage after mount. Until then, deptSlug is
  // empty by construction — rendering the connect screen against that would
  // flash it in front of an already-connected user for one frame.
  const [hydrated, setHydrated] = useState(false);
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const [conversations, setConversations] = useState<StoredConversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [inspectedMsgId, setInspectedMsgId] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  // A client-side rolling average of this session's non-cache latencies —
  // the only source for "if generated" in the response detail panel. No
  // server field for it; empty until the session has a generated answer.
  const [baselineLatencies, setBaselineLatencies] = useState<number[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const transcriptsRef = useRef<Record<string, AppMessage[]>>({});
  const activeConvIdRef = useRef<string | null>(null);
  // Stop's abort path, one entry per in-flight send. abort() tears down the
  // real fetch/stream (sendChatMessage forwards the signal); `cancelled` is
  // the app-level companion that makes every callback and the post-await
  // continuation of that send a no-op immediately, without waiting on the
  // network teardown to complete.
  const sendsRef = useRef(new Map<string, LiveSend>());
  // localStorage writes queued by a transcript update, flushed from the effect
  // below so nothing writes storage or schedules state from inside a state
  // updater. A write may carry a predicate: it runs only if the committed
  // transcript actually shows the change that asked for it, so an update that
  // turned out to be a no-op cannot leave a write armed for some later,
  // unrelated change to fire.
  const pendingPersistRef = useRef<{ convId: string; requires?: (msgs: AppMessage[]) => boolean }[]>([]);
  const windowWidth = useWindowWidth();
  const isNarrow = windowWidth < DRAWER_MAX_WIDTH;
  const sidebarCollapsed = windowWidth < SIDEBAR_COLLAPSE_WIDTH;

  // The transcript on screen. A conversation with no id yet (a brand-new chat)
  // has nothing to show until its first send gives it one.
  const messages = (activeConvId ? transcripts[activeConvId] : undefined) ?? NO_MESSAGES;
  // Everything below reads the conversation on screen. A send running for some
  // other conversation is deliberately invisible here — it shows up in the
  // sidebar instead, and in its own transcript when the user goes back to it.
  const activeGeneration = activeConvId ? generating[activeConvId] : undefined;
  const isGenerating = Boolean(activeGeneration);
  const isWaiting = activeGeneration?.waiting ?? false;
  const generatingIds = Object.keys(generating);

  useEffect(() => {
    transcriptsRef.current = transcripts;
    const queued = pendingPersistRef.current;
    if (queued.length === 0) return;
    pendingPersistRef.current = [];
    for (const write of queued) {
      const msgs = transcripts[write.convId];
      if (!msgs || msgs.length === 0) continue;
      if (write.requires && !write.requires(msgs)) continue;
      persistConversation(write.convId, msgs);
    }
  }, [transcripts]);

  useEffect(() => {
    activeConvIdRef.current = activeConvId;
  }, [activeConvId]);

  // Load settings and conversation history from localStorage on first render.
  useEffect(() => {
    setSettings(loadSettings());
    setConversations(loadConversations());
    setHydrated(true);
  }, []);

  // Scroll to the newest message whenever the list changes.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isWaiting]);

  // New chat shortcut. Binding and the label the sidebar renders both come
  // from NEW_CHAT_SHORTCUT so they cannot drift. No dep array:
  // startNewConversation closes over the live transcript, which it saves
  // before clearing.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!matchesNewChatShortcut(e)) return;
      if (!settings.deptSlug || settingsOpen) return;
      e.preventDefault();
      startNewConversation();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  function addToast(kind: ToastKind, title: string, body: string, action?: ToastAction) {
    const id = `toast_${Date.now()}_${Math.random()}`;
    setToasts((prev) => [...prev, { id, kind, title, body, action }]);
  }

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  function saveSettings(next: ChatSettings) {
    persistSettings(next);
    setSettings(next);
  }

  function handleConnected(next: ChatSettings) {
    persistSettings(next);
    setSettings(next);
    addToast("success", "Connected", `Using the ${next.deptSlug} department.`);
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

  // The one way a transcript changes. `update` must be pure — the storage write
  // it may ask for is queued and flushed from the effect above, once the result
  // has actually been committed.
  function updateTranscript(
    convId: string,
    update: (prev: AppMessage[]) => AppMessage[],
    persist?: { requires?: (msgs: AppMessage[]) => boolean },
  ) {
    if (persist) pendingPersistRef.current.push({ convId, requires: persist.requires });
    setTranscripts((prev) => ({ ...prev, [convId]: update(prev[convId] ?? NO_MESSAGES) }));
  }

  function clearTranscript(convId: string) {
    pendingPersistRef.current = pendingPersistRef.current.filter((w) => w.convId !== convId);
    setTranscripts((prev) => {
      if (!(convId in prev)) return prev;
      const next = { ...prev };
      delete next[convId];
      return next;
    });
  }

  function endGeneration(convId: string) {
    setGenerating((prev) => {
      if (!(convId in prev)) return prev;
      const next = { ...prev };
      delete next[convId];
      return next;
    });
  }

  // Save the conversation being navigated away from. Skipped while it is
  // generating: that send persisted the question itself and will persist the
  // finished answer, so writing here would only store a half-streamed answer
  // that nothing marks as unfinished.
  function persistOnLeave() {
    if (activeConvId && messages.length > 0 && !isGenerating) {
      persistConversation(activeConvId, messages);
    }
  }

  // Navigating away from a generating conversation is allowed: the send keeps
  // running against the id it captured and its answer appears in that
  // conversation, whether or not it is the one on screen when it lands.
  function startNewConversation() {
    persistOnLeave();
    setActiveConvId(null);
    setInput("");
    setAttachment(null);
    setInspectedMsgId(null);
    setInspectorOpen(false);
  }

  // Load a conversation selected from the sidebar.
  function handleSelectConversation(conv: StoredConversation) {
    persistOnLeave();
    // Keep the in-memory copy if there is one: it is never staler than the
    // stored copy, and for a conversation generating in the background it is
    // the only one carrying the partial answer.
    setTranscripts((prev) => (prev[conv.id] ? prev : { ...prev, [conv.id]: conv.messages }));
    setActiveConvId(conv.id);
    setInput("");
    // The pin belongs to the conversation it was attached in. A stored
    // conversation never carries one back (see the note in handleSend), so
    // switching always drops it rather than silently re-sending the old file.
    setAttachment(null);
    setInspectedMsgId(null);
    setInspectorOpen(false);
  }

  function handleDeleteConversation(id: string) {
    // The one case where an in-flight answer has nowhere to land, so it is
    // aborted rather than left to finish into a conversation that is gone.
    cancelSend(id, "discard");
    deleteConversation(id);
    setConversations(loadConversations());
    clearTranscript(id);
    // If the deleted conversation was active, clear the chat area.
    if (id === activeConvId) {
      setActiveConvId(null);
      setAttachment(null);
      setInspectedMsgId(null);
      setInspectorOpen(false);
    }
  }

  // The one genuine behaviour change in this stage: Stop must leave the
  // conversation coherent, never looking like a complete answer, and must
  // actually cancel the request rather than just hiding the spinner. abort()
  // tears down the real fetch/stream (sendChatMessage forwards the signal
  // into fetch and the read loop); `cancelled` flips every callback and the
  // continuation of that send to a no-op immediately, so nothing has to wait
  // on the network teardown to be coherent.
  //
  // "stopped" keeps whatever text had already arrived and marks it — a press
  // before the first token has landed has no placeholder to mark, so that turn
  // just goes back to normal. "discard" is for a conversation being deleted,
  // where there is nothing left to mark.
  function cancelSend(convId: string, mode: "stopped" | "discard") {
    const send = sendsRef.current.get(convId);
    if (!send) return;
    send.cancelled = true;
    send.controller.abort();
    sendsRef.current.delete(convId);
    endGeneration(convId);
    if (mode === "discard") return;
    updateTranscript(
      convId,
      (prev) =>
        prev.some((m) => m.id === send.assistantId)
          ? prev.map((m) => (m.id === send.assistantId ? { ...m, stopped: true } : m))
          : prev,
      { requires: (msgs) => msgs.some((m) => m.id === send.assistantId && m.stopped) },
    );
  }

  // Stop belongs to the conversation on screen, never to whichever send
  // happens to be running.
  function handleStop() {
    if (activeConvId) cancelSend(activeConvId, "stopped");
  }

  // A send that produced no answer. The question is never taken back out of
  // the transcript — an answer can land in a conversation the user has
  // navigated away from, so a revert would delete a question out of a screen
  // nobody is looking at and leave nothing behind. It is marked instead, the
  // same way Stop marks a cut-off answer, and the mark carries Retry. The mark
  // goes on whatever ended the turn: a partial answer when the stream dropped
  // mid-flight, otherwise the question itself.
  function markSendFailed(
    convId: string,
    userMsgId: string,
    assistantId: string,
    reason: "unsent" | "empty-answer",
  ) {
    updateTranscript(
      convId,
      (prev) => {
        const targetId = prev.some((m) => m.id === assistantId) ? assistantId : userMsgId;
        return prev.map((m) => (m.id === targetId ? { ...m, failed: reason } : m));
      },
      {
        requires: (msgs) =>
          msgs.some((m) => (m.id === assistantId || m.id === userMsgId) && m.failed),
      },
    );
  }

  async function handleSend() {
    const text = input.trim();
    if ((!text && !attachment) || isGenerating) return;

    // The conversation this send belongs to, decided here and never re-read
    // from the active conversation again: everything below — every delta, the
    // final answer and its metadata, the storage write — addresses this id, so
    // navigating away mid-answer cannot land it anywhere else.
    const convId = activeConvId ?? `conv_${Date.now()}`;
    if (!activeConvId) setActiveConvId(convId);
    setInput("");
    await runSend(convId, messages, text, attachment);
  }

  // Re-run a turn that failed. The question is already in the transcript, so
  // the retry re-sends its text against the history in front of it and
  // replaces everything from that turn on — the failed mark, and any partial
  // answer under it.
  //
  // It replays that turn and nothing else: no attachment is passed, because
  // the only attachment a retry could reach for is whatever the composer is
  // holding right now, which is not what the turn sent — a conversation
  // switch clears the pin, and the file's bytes are never stored. A turn that
  // did carry one is not retryable at all (see retryableMsgId).
  function handleRetry(msgId: string) {
    const convId = activeConvIdRef.current;
    if (!convId || generating[convId]) return;
    const msgs = transcriptsRef.current[convId] ?? NO_MESSAGES;
    const index = msgs.findIndex((m) => m.id === msgId);
    if (index < 0) return;
    const userIndex = turnQuestionIndex(msgs, index);
    if (userIndex < 0 || msgs[userIndex].hadAttachment) return;
    void runSend(convId, msgs.slice(0, userIndex), msgs[userIndex].content, null);
  }

  async function runSend(
    convId: string,
    priorMessages: AppMessage[],
    text: string,
    sentAttachment: Attachment | null,
  ) {
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
      hadAttachment: sentAttachment !== null,
    };

    // The transcript this send writes into: the history in front of the
    // question, plus the question. A retry passes the history in front of the
    // turn it re-runs, so replacing the transcript with this drops the failed
    // mark and any partial answer under it. Persisted right away so the
    // sidebar can show the conversation, and its still-working indicator, from
    // the moment the question is asked.
    const withUserMsg = [...priorMessages, userMsg];

    updateTranscript(convId, () => withUserMsg, {});
    // The attachment is NOT cleared here. It stays pinned so every follow-up
    // carries it: without that, turn 2 goes to /v1/chat/completions with no file
    // at all — the model answers from its own previous reply, and the answer is
    // stored as an ungated plain-text entry that a different document could
    // later match. The pin is dropped only by Unpin or a conversation switch.
    // ponytail: pin lives in memory only. A 10MB base64 data URL does not fit in
    // localStorage, so a reload means re-attaching; persist small ones if
    // surviving a reload is ever asked for.

    // Pre-allocate the assistant message so we can append deltas in-place.
    const assistantId = newId();
    const send: LiveSend = { assistantId, controller: new AbortController(), cancelled: false };
    sendsRef.current.set(convId, send);
    setGenerating((prev) => ({
      ...prev,
      [convId]: { waiting: true, route: null, model: null, sinceMs: null },
    }));

    const assistantPlaceholder: AppMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      ts: Date.now(),
    };

    // Send the full conversation history so the model has context.
    const history = withUserMsg.map((m) => ({ role: m.role, content: m.content }));

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
        if (send.cancelled) return;
        if (firstDelta) {
          // Show the placeholder bubble and hide the typing indicator on first byte.
          firstDelta = false;
          setGenerating((prev) =>
            prev[convId] ? { ...prev, [convId]: { ...prev[convId], waiting: false } } : prev
          );
          updateTranscript(convId, (prev) => [...prev, { ...assistantPlaceholder, ...streamMeta, content: delta }]);
        } else {
          updateTranscript(convId, (prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + delta } : m))
          );
        }
      },
      (meta) => {
        if (send.cancelled) return;
        // Headers land before the first delta, so the wait strip can name the
        // route and model while the answer is still generating.
        streamMeta = { modelUsed: meta.modelUsed, tier: meta.tier };
        const route = classifyRoute(meta.tier, meta.modelUsed);
        setGenerating((prev) =>
          prev[convId]
            ? { ...prev, [convId]: { ...prev[convId], route, model: meta.modelUsed, sinceMs: Date.now() } }
            : prev
        );
      },
      send.controller.signal,
    );

    // A send only tears down the record it owns. A stop followed by a fresh
    // send for the same conversation puts a different LiveSend in this slot,
    // and clearing that one would re-enable the composer and drop Stop while
    // the replacement answer is still streaming.
    if (sendsRef.current.get(convId) === send) {
      sendsRef.current.delete(convId);
      endGeneration(convId);
    }

    // Stopped or deleted while this was in flight: cancelSend already finalized
    // the message and aborted the request. Nothing below may touch state again
    // — that is exactly the corruption Stop exists to prevent.
    if (send.cancelled) return;

    if (isApiError(result)) {
      if (result.status === 402) {
        addToast(
          "error",
          "No cloud provider key",
          "This question needed a cloud model, and the workspace has no provider credential configured.",
          { label: "Add one in the dashboard", href: dashboardUrl },
        );
      } else {
        addToast("error", "Request failed", result.message);
      }
      // The question stays where it was asked, marked, with Retry on it. The
      // attachment needs no restoring — it was never cleared — and a failed
      // send leaves it un-pinned, so a retry still reads as the first attempt.
      markSendFailed(convId, userMsg.id, assistantId, "unsent");
      return;
    }

    // A stream that broke part-way still carries real text, so the turn is kept
    // rather than reverted - but never silently: a cut-off answer is
    // indistinguishable from a finished one in the bubble alone.
    if (result.streamError) {
      addToast("error", "Answer cut off", result.streamError);
    }

    // The assistant bubble is only ever created by the first delta, so a stream
    // that yields none leaves the finalization below mapping over a list with no
    // assistantId: it quietly no-ops and the user sees their own message, no
    // reply, and no error whatsoever. Observed live — a thinking model spent its
    // whole token budget on the scratchpad and returned an empty answer with
    // HTTP 200. Never fail silently here.
    if (firstDelta) {
      if (result.text) {
        updateTranscript(convId, (prev) => [...prev, { ...assistantPlaceholder, content: result.text }]);
      } else {
        addToast("error", "Empty answer", "The model returned an empty answer. Try rephrasing, or switch routing to external.");
        markSendFailed(convId, userMsg.id, assistantId, "empty-answer");
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

    // Attach metadata to the assistant message now that the stream is complete,
    // and write the finished conversation to storage.
    updateTranscript(
      convId,
      (prev) =>
        prev.map((m) =>
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
                authoredByHuman: result.answerAuthored === "human",
                cacheEnrichedQuery: result.cacheEnrichedQuery,
              }
            : m
        ),
      {},
    );

    // The response detail panel's "if generated" comparison is a rolling
    // average of this session's own non-cache latencies — never the cache
    // path itself, or every comparison would trivially be "1x".
    if (!result.cacheHit && result.latencyMs > 0) {
      setBaselineLatencies((prev) => [...prev, result.latencyMs]);
    }
  }

  function updateFeedbackPhase(convId: string, msgId: string, phase: FeedbackPhase) {
    updateTranscript(convId, (prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, feedbackPhase: phase } : m))
    );
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
    // Feedback is given on a turn the user is looking at, so the conversation
    // it belongs to is the active one — captured here and used for every write
    // below, since the reply can outlive the user's stay on this screen.
    const convId = activeConvIdRef.current;
    if (!convId) return;
    const messages = transcriptsRef.current[convId] ?? NO_MESSAGES;
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

    updateFeedbackPhase(convId, msgId, "submitting");

    const result = await sendFeedback(
      msg.responseId ?? null,
      msg.interactionId ?? null,
      isAttachmentAnchored ? null : msg.requestMessages ?? null,
      rating,
      comment,
      settings.deptSlug,
    );

    if (isApiError(result)) {
      updateFeedbackPhase(convId, msgId, "error");
      addToast("error", "Feedback failed", result.message);
      return;
    }

    if (result.status === "deleted") {
      addToast("info", "Cached answer removed", "The next person to ask this gets a fresh answer.");
    } else if (typeof result.newScore === "number") {
      addToast("success", "Thanks — noted", `This answer scores ${result.newScore.toFixed(1)} and will be served more often.`);
    } else {
      addToast("success", "Thanks — noted", "Feedback recorded.");
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

    updateTranscript(
      convId,
      (prev) => {
        const updated = prev.map((m) =>
          m.id === msgId ? { ...m, feedbackPhase: rating, feedbackScore } : m
        );
        return reanswered ? [...updated, reanswered] : updated;
      },
      {},
    );

    if (rating === "negative" && result.escalatedResponse) {
      addToast("success", "Re-answered", `You marked the last one wrong, so it went to ${result.escalatedResponse.tier}.`);
      return;
    }

    const toast = escalationToast(result.escalationStatus);
    if (toast) addToast("info", "Notice", toast);
  }

  // Edit & Save. Returns false when nothing was committed, which keeps the
  // editor open with the user's draft rather than discarding it.
  //
  // Modeled on handleFeedback above, and shares its attachment rule for the
  // same reason: the request replay carries role/content history only, never
  // the attachment, so a turn anchored to an image or a file must not hand the
  // server material to build an ungated text entry from. Withholding
  // requestMessages is what limits those turns to overwriting an entry that
  // already exists, with its fingerprints intact.
  async function handleSaveEdit(msgId: string, text: string): Promise<boolean> {
    const convId = activeConvIdRef.current;
    if (!convId) return false;
    const currentMessages = transcriptsRef.current[convId] ?? NO_MESSAGES;
    const msgIndex = currentMessages.findIndex((m) => m.id === msgId);
    const msg = msgIndex >= 0 ? currentMessages[msgIndex] : undefined;
    if (!msg?.responseId && !msg?.interactionId) return false;

    const precedingUserMsg = [...currentMessages.slice(0, msgIndex)]
      .reverse()
      .find((m) => m.role === "user");
    const isAttachmentAnchored = Boolean(precedingUserMsg?.imageUrl || precedingUserMsg?.fileName);

    const result = await saveEditedAnswer(
      msg.responseId ?? null,
      msg.interactionId ?? null,
      isAttachmentAnchored ? null : msg.requestMessages ?? null,
      text,
      settings.deptSlug,
    );

    if (isApiError(result)) {
      addToast("error", "Could not save", result.message);
      return false;
    }

    // The edit is committed to the transcript whatever the cache did with it:
    // the user corrected the answer they are looking at, and that much is true
    // even when the entry could not be written. The toast says which happened.
    //
    // The thumbs row is a different question. A save that never reached the
    // cache got no +1.0 either, so claiming the terminal thumbs-up state would
    // be a lie AND would take away the only control left for rating the answer.
    const landed = editLanded(result.editStatus);
    updateTranscript(
      convId,
      (prev) =>
        prev.map((m) =>
          m.id === msgId
            ? {
                ...m,
                content: text,
                editedByUser: true,
                // A save IS a like — when it lands, the server applies the
                // +1.0 in the same call, so the row shows its terminal
                // thumbs-up state. When it didn't, the row stays open.
                feedbackPhase: landed ? ("positive" as const) : m.feedbackPhase,
                feedbackScore: typeof result.newScore === "number" ? result.newScore : m.feedbackScore,
                // The server may have redirected an alias to its root or keyed
                // a new entry; later feedback must address the entry that
                // actually holds this text.
                responseId: result.responseId ?? m.responseId,
              }
            : m
        ),
      {},
    );

    const notice = editStatusNotice(result.editStatus);
    if (notice) addToast(notice.kind, notice.title, notice.body);
    return true;
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

  const connected = Boolean(settings.deptSlug);
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

  // The one message, if any, that may carry Retry. Two conditions, both about
  // being able to honour the offer:
  //
  // It must be the last message, because a retry replaces the failed turn and
  // everything under it, so a failure the user has already moved past stays
  // marked but can no longer take later turns with it.
  //
  // And its turn must not have carried an attachment. The file is gone — the
  // pin is cleared by a conversation switch and its bytes are never persisted
  // — so re-running the turn would send "What is in this document?" with no
  // document, and the answer to that gets stored as an ungated text entry
  // another document could later match. The turn's own recorded
  // `hadAttachment` decides this, never the live composer, so the answer does
  // not change under the user as they pin and unpin things.
  const lastMessage = messages[messages.length - 1];
  const retryableMsgId = (() => {
    if (!lastMessage?.failed) return null;
    const questionIndex = turnQuestionIndex(messages, messages.length - 1);
    if (questionIndex < 0 || messages[questionIndex].hadAttachment) return null;
    return lastMessage.id;
  })();

  // Cache hits among this conversation's answered turns — the header's
  // "N of M from cache" pulse. Only counted once a route is known.
  const cacheStats = messages.reduce(
    (acc, m) => {
      if (m.role !== "assistant") return acc;
      const route = classifyRoute(m.tier, m.modelUsed);
      if (route === null) return acc;
      acc.total += 1;
      if (route === "cache") acc.cache += 1;
      return acc;
    },
    { cache: 0, total: 0 },
  );

  return (
    <div
      style={{
        background: "var(--bg)",
        display: "flex",
        height: "100vh",
        overflow: "hidden",
      }}
    >
      <ConversationSidebar
        conversations={conversations}
        activeId={activeConvId}
        onSelect={handleSelectConversation}
        onNew={startNewConversation}
        onDelete={handleDeleteConversation}
        onOpenSettings={() => setSettingsOpen(true)}
        deptSlug={settings.deptSlug}
        connected={connected}
        collapsed={sidebarCollapsed}
        generatingIds={generatingIds}
      />

      <div style={{ display: "flex", flex: 1, flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
        {/* ── Header ── */}
        <header
          style={{
            alignItems: "center",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            flexShrink: 0,
            gap: "14px",
            height: "56px",
            padding: "0 20px 0 28px",
          }}
        >
          {!hydrated ? (
            <div style={{ flex: 1 }} />
          ) : !connected ? (
            <>
              <div style={{ flex: 1 }} />
              <div
                style={{
                  alignItems: "center",
                  background: "var(--red-bg)",
                  border: "1px solid var(--red-border)",
                  borderRadius: "999px",
                  display: "flex",
                  gap: "8px",
                  height: "28px",
                  padding: "0 11px",
                }}
              >
                <span style={{ background: "var(--red)", borderRadius: "999px", flexShrink: 0, height: "6px", width: "6px" }} />
                <span style={{ color: "var(--red)", fontSize: "12px", fontWeight: 500 }}>Not connected</span>
              </div>
            </>
          ) : (
            <>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: messages.length === 0 ? "var(--fg-dimmer)" : "var(--fg)", fontSize: "15px", fontWeight: 600, letterSpacing: "-0.015em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {messages.length === 0 ? "New chat" : titleFromMessages(messages)}
                </div>
              </div>

              {cacheStats.total > 0 && (
                <div
                  style={{
                    alignItems: "center",
                    background: "var(--accent-bg)",
                    border: "1px solid var(--accent-border)",
                    borderRadius: "999px",
                    display: "flex",
                    gap: "8px",
                    height: "30px",
                    padding: "0 11px 0 9px",
                  }}
                >
                  <span style={{ color: "var(--accent)", display: "flex" }}>
                    <CacheGlyph />
                  </span>
                  <span style={{ color: "var(--accent)", fontSize: "12px", fontWeight: 600, letterSpacing: "-0.003em" }}>
                    {cacheStats.cache} of {cacheStats.total} from cache
                  </span>
                </div>
              )}

              <div style={{ background: "var(--border)", height: "20px", width: "1px" }} />

              <button
                onClick={() => setInspectorOpen((v) => !v)}
                title={inspectorOpen ? "Hide response detail" : "Show response detail"}
                style={iconBtn(inspectorOpen)}
              >
                <InspectorPanelIcon />
              </button>
              <a href={dashboardUrl} target="_blank" rel="noreferrer" style={iconBtn(false)} title="Open dashboard">
                <DashboardIcon />
              </a>
            </>
          )}
        </header>

        {/* ── Body ── */}
        {!hydrated ? null : !connected ? (
          <ConnectScreen initialSettings={settings} onConnected={handleConnected} dashboardUrl={dashboardUrl} />
        ) : (
          <div style={{ display: "flex", flex: 1, flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
            {/* Transcript region. This — not the whole column — is the response
                detail panel's positioning context, which is what keeps the panel
                off the composer: it can only ever span from below the header to
                the top of the input, so the attach control, the textarea and the
                send button stay visible and clickable at every width. */}
            <div style={{ display: "flex", flex: 1, flexDirection: "column", minWidth: 0, overflow: "hidden", position: "relative" }}>
              <main style={{ display: "flex", flex: 1, flexDirection: "column", overflowY: "auto", paddingTop: "16px" }}>
                {messages.length === 0 ? (
                  <WelcomeScreen onSelectPrompt={handleWelcomePrompt} />
                ) : (
                  <div style={{ position: "relative" }}>
                    <RailTrack />
                    {messages.map((msg) => (
                      <ChatMessage
                        key={msg.id}
                        message={msg}
                        onFeedback={handleFeedback}
                        onRetry={msg.id === retryableMsgId ? handleRetry : undefined}
                        onSaveEdit={msg.role === "assistant" ? handleSaveEdit : undefined}
                        onInspect={msg.role === "assistant" ? handleInspect : undefined}
                        inspected={msg.id === inspectedMsgId && inspectorOpen}
                        baselineMs={baselineMs}
                        baselineSampleCount={baselineLatencies.length}
                      />
                    ))}
                    {isWaiting && activeGeneration && (
                      <TypingIndicator
                        route={activeGeneration.route}
                        modelUsed={activeGeneration.model}
                        sinceMs={activeGeneration.sinceMs}
                      />
                    )}
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

            <MessageInput
              value={input}
              onChange={setInput}
              onSend={handleSend}
              disabled={isGenerating}
              attachment={attachment}
              onAttachmentChange={setAttachment}
              onAttachmentError={(msg) => addToast("error", "Couldn't attach that file", msg)}
              isGenerating={isGenerating}
              onStop={handleStop}
            />
          </div>
        )}
      </div>

      {inspectorOpen && isNarrow && connected && (
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

const ROUTE_LEGEND: { key: Route; label: string; sub: string }[] = [
  { key: "cache", label: "Cache", sub: "instant" },
  { key: "local", label: "Local", sub: "easy questions" },
  { key: "cloud", label: "Cloud", sub: "the hard ones" },
];

function WelcomeScreen({ onSelectPrompt }: { onSelectPrompt: (p: string) => void }) {
  return (
    <div style={{ alignItems: "center", display: "flex", flex: 1, justifyContent: "center", minHeight: 0, paddingBottom: "30px" }}>
      {/* Same rail+gutter offset as every turn and the composer below, so the
          hero and the prompt grid line up with the reading column rather than
          sitting centred under it. */}
      <div style={{ display: "flex", margin: "0 auto", maxWidth: "calc(var(--shell) + 32px)", padding: "0 16px", width: "100%" }}>
        <div style={{ flex: "none", width: "calc(var(--rail) + var(--gutter))" }} />
        <div style={{ flex: 1, maxWidth: "var(--col)", minWidth: 0 }}>
          <div style={{ alignItems: "flex-start", display: "flex", gap: "22px" }}>
            <div
              aria-hidden
              style={{
                alignItems: "center",
                background: "var(--accent-bg)",
                border: "1px solid var(--accent-border)",
                borderRadius: "20px",
                color: "var(--accent)",
                display: "flex",
                flexShrink: 0,
                height: "68px",
                justifyContent: "center",
                width: "68px",
              }}
            >
              <CacheGlyph size={34} />
            </div>
            <div style={{ flex: 1, paddingTop: "4px" }}>
              <div style={{ fontSize: "30px", fontWeight: 600, letterSpacing: "-0.028em", lineHeight: "36px" }}>
                Ask anything.
              </div>
              <div style={{ color: "var(--fg-dim)", fontSize: "16px", lineHeight: "26px", marginTop: "10px", maxWidth: "540px" }}>
                Questions this workspace has answered before come back in milliseconds. Everything else is
                routed to the cheapest model that can handle it — and stored, so the next person doesn&apos;t
                pay for it twice.
              </div>
            </div>
          </div>

          {/* Route legend: teaches the three-colour language before it is used. */}
          <div style={{ alignItems: "center", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "12px", display: "flex", gap: "24px", marginTop: "34px", padding: "14px 18px" }}>
            {ROUTE_LEGEND.map((r) => {
              const style = ROUTE_LEGEND_STYLE[r.key];
              return (
                <div key={r.key} style={{ alignItems: "center", display: "flex", gap: "9px" }}>
                  <span
                    style={{
                      alignItems: "center",
                      background: style.bg,
                      border: `1.5px solid ${style.border}`,
                      borderRadius: "999px",
                      color: style.ink,
                      display: "flex",
                      height: "22px",
                      justifyContent: "center",
                      width: "22px",
                    }}
                  >
                    {r.key === "cache" && <CacheGlyph size={11} />}
                    {r.key === "local" && <LocalGlyph size={11} />}
                    {r.key === "cloud" && <CloudGlyph size={11} />}
                  </span>
                  <span style={{ color: "var(--fg-dim)", fontSize: "12.5px" }}>
                    <span style={{ color: "var(--fg)", fontWeight: 500 }}>{r.label}</span> · {r.sub}
                  </span>
                </div>
              );
            })}
          </div>

          <div style={{ color: "var(--fg-dimmer)", fontSize: "10.5px", fontWeight: 600, letterSpacing: "0.10em", marginTop: "34px", textTransform: "uppercase" }}>
            Start with
          </div>
          <div style={{ display: "grid", gap: "10px", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", marginTop: "12px" }}>
            {WELCOME_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                onClick={() => onSelectPrompt(prompt)}
                style={{
                  alignItems: "flex-start",
                  background: "var(--bg-2)",
                  border: "1px solid var(--border)",
                  borderRadius: "11px",
                  color: "var(--fg)",
                  cursor: "pointer",
                  display: "flex",
                  fontSize: "13.5px",
                  gap: "10px",
                  lineHeight: "20px",
                  padding: "15px 16px",
                  textAlign: "left",
                  transition: "border-color var(--t-base), background var(--t-base)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--bg-3)";
                  e.currentTarget.style.borderColor = "var(--border-2)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "var(--bg-2)";
                  e.currentTarget.style.borderColor = "var(--border)";
                }}
              >
                <span style={{ flex: 1 }}>{prompt}</span>
                <span style={{ color: "var(--fg-dimmer)", display: "flex", flexShrink: 0, paddingTop: "3px" }}>
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M6 3.5 10.5 8 6 12.5" />
                  </svg>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

const ROUTE_LEGEND_STYLE: Record<Route, { ink: string; bg: string; border: string }> = {
  cache: { ink: "var(--accent)", bg: "var(--accent-bg)", border: "var(--accent-border)" },
  local: { ink: "var(--local)", bg: "var(--local-bg)", border: "var(--local-border)" },
  cloud: { ink: "var(--blue)", bg: "var(--blue-bg)", border: "var(--blue-border)" },
};

// ─── Style helpers ─────────────────────────────────────────────────────────────

function iconBtn(active: boolean): React.CSSProperties {
  return {
    alignItems: "center",
    background: active ? "var(--bg-3)" : "transparent",
    border: "none",
    borderRadius: "8px",
    color: active ? "var(--fg)" : "var(--fg-dimmer)",
    cursor: "pointer",
    display: "flex",
    height: "30px",
    justifyContent: "center",
    textDecoration: "none",
    width: "30px",
  };
}

// ─── Icons ──────────────────────────────────────────────────────────────────

function CacheGlyph({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M13.5 7.4A5.6 5.6 0 0 0 3.4 5" />
      <path d="M2.5 8.6a5.6 5.6 0 0 0 10.1 2.4" />
      <path d="M3.3 2v3h3" />
      <path d="M12.7 14v-3h-3" />
    </svg>
  );
}

function LocalGlyph({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
      <rect x="4.6" y="4.6" width="6.8" height="6.8" rx="1.3" />
      <path d="M6.4 1.9v2.7M9.6 1.9v2.7M6.4 11.4v2.7M9.6 11.4v2.7M1.9 6.4h2.7M1.9 9.6h2.7M11.4 6.4h2.7M11.4 9.6h2.7" />
    </svg>
  );
}

function CloudGlyph({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round">
      <path d="M4.7 12.6A3.15 3.15 0 0 1 5 6.4a4.35 4.35 0 0 1 8.3 1.3 2.65 2.65 0 0 1-.5 5.1H4.7z" />
    </svg>
  );
}

function DashboardIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9.6 2.4h4v4" />
      <path d="M13.6 2.4 7.6 8.4" />
      <path d="M12.1 9.6v3.4a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4.9a1 1 0 0 1 1-1h3.4" />
    </svg>
  );
}

function InspectorPanelIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="1.9" y="2.6" width="12.2" height="10.8" rx="2" />
      <path d="M10.1 2.6v10.8" />
    </svg>
  );
}
