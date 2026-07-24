// LocalStorage-backed conversation history store.
// Persists chat sessions client-side without requiring a server endpoint.
// The API returns X-DejaQ-Conversation-Id but there is no GET /conversations
// endpoint, so we manage history entirely in the browser.

import type { AppMessage } from "./ChatMessage";

export interface StoredConversation {
  id: string;
  // Short title derived from the first user message.
  title: string;
  messages: AppMessage[];
  lastUpdated: number;
}

const STORAGE_KEY = "dejaq_conversations";
const MAX_CONVERSATIONS = 20;

function readFromStorage(): StoredConversation[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function loadConversations(): StoredConversation[] {
  return readFromStorage().sort((a, b) => b.lastUpdated - a.lastUpdated);
}

export function saveConversation(conv: StoredConversation): void {
  if (typeof window === "undefined") return;
  // Strip attached-image data URLs before persisting: base64 images blow through
  // the ~5 MB localStorage quota fast. Thumbnails survive for the live session
  // only; a reloaded conversation shows the text without the image.
  const lean: StoredConversation = {
    ...conv,
    messages: conv.messages.map(({ imageUrl, ...m }) => m),
  };
  // Replace any existing entry for this ID, then cap the list size.
  const rest = readFromStorage().filter((c) => c.id !== conv.id);
  const updated = [lean, ...rest].slice(0, MAX_CONVERSATIONS);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  } catch {
    // Quota exceeded or storage disabled — history is best-effort, so drop it.
  }
}

export function deleteConversation(id: string): void {
  if (typeof window === "undefined") return;
  const updated = readFromStorage().filter((c) => c.id !== id);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
}

/** Derive a short display title from the first user message in a conversation. */
export function titleFromMessages(messages: AppMessage[]): string {
  const first = messages.find((m) => m.role === "user");
  if (!first) return "New conversation";
  const text = first.content.trim().replace(/\s+/g, " ");
  return text.length > 60 ? `${text.slice(0, 57)}…` : text;
}
