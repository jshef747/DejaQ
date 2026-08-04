// LocalStorage-backed settings for chat UI preferences, including the DejaQ
// workspace API key. A key entered here is sent to the chat app's own /api/*
// routes as a header and never logged; DEJAQ_API_KEY in chat/.env.local is
// only the fallback used when this is empty.

const STORAGE_KEY = "dejaq_chat_settings";

export interface ChatSettings {
  // Empty string = use the chat app's server-side default (DEJAQ_API_BASE_URL,
  // i.e. http://127.0.0.1:8000). Set to http://<other-host>:8000 to point the
  // chat app at a DejaQ server running on another machine on the LAN.
  serverBaseUrl: string;
  // Empty string = fall back to DEJAQ_API_KEY in chat/.env.local.
  apiKey: string;
  deptSlug: string;
  modelProfile: ModelProfile;
  routingMode: RoutingMode;
}

// One attachment per message: an image, a PDF, or a Markdown file. `dataUrl` is
// the only transport — the DejaQ API takes data URLs and nothing else.
export interface Attachment {
  dataUrl: string;
  kind: "image" | "pdf" | "markdown";
  name: string;
  size: number;
  // The attachment stays pinned after a send, so follow-ups carry it too.
  // false = the user just picked it, true = it survived a send and is being
  // re-sent. Nothing branches on this; it only labels the chip and the server
  // log so a carried turn can be told apart from a fresh one.
  sticky: boolean;
}

export type ModelProfile = "default" | "weak_cpu";
export type RoutingMode = "auto" | "easy_local" | "hard_external";

export const DEFAULT_CHAT_SETTINGS: ChatSettings = {
  serverBaseUrl: "",
  apiKey: "",
  deptSlug: "",
  modelProfile: "default",
  routingMode: "auto",
};

function parseModelProfile(value: unknown): ModelProfile {
  return value === "weak_cpu" ? "weak_cpu" : "default";
}

function parseRoutingMode(value: unknown): RoutingMode {
  return value === "easy_local" || value === "hard_external" ? value : "auto";
}

function sanitizeSettings(value: unknown): ChatSettings {
  const parsed = typeof value === "object" && value !== null ? value as Record<string, unknown> : {};
  return {
    serverBaseUrl: typeof parsed.serverBaseUrl === "string" ? parsed.serverBaseUrl.trim() : "",
    apiKey: typeof parsed.apiKey === "string" ? parsed.apiKey.trim() : "",
    deptSlug: typeof parsed.deptSlug === "string" ? parsed.deptSlug : "",
    modelProfile: parseModelProfile(parsed.modelProfile),
    routingMode: parseRoutingMode(parsed.routingMode),
  };
}

export function loadSettings(): ChatSettings {
  if (typeof window === "undefined") return DEFAULT_CHAT_SETTINGS;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_CHAT_SETTINGS;
    const settings = sanitizeSettings(JSON.parse(raw));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    return settings;
  } catch {
    return DEFAULT_CHAT_SETTINGS;
  }
}

export function persistSettings(settings: ChatSettings): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitizeSettings(settings)));
}

// The saved server override (empty = server-side default). Read on every /api/*
// call so the browser can point the proxy at another host without a rebuild.
export function loadServerBaseUrl(): string {
  return loadSettings().serverBaseUrl;
}

// The saved API key override (empty = fall back to DEJAQ_API_KEY server-side).
export function loadApiKey(): string {
  return loadSettings().apiKey;
}
