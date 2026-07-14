// LocalStorage-backed settings for non-secret chat UI preferences.
// DejaQ credentials are read server-side from chat/.env.local and are never
// persisted in the browser.

const STORAGE_KEY = "dejaq_chat_settings";

export interface ChatSettings {
  // Empty string = use the chat app's server-side default (DEJAQ_API_BASE_URL,
  // i.e. http://127.0.0.1:8000). Set to http://<other-host>:8000 to point the
  // chat app at a DejaQ server running on another machine on the LAN.
  serverBaseUrl: string;
  deptSlug: string;
  modelProfile: ModelProfile;
  routingMode: RoutingMode;
}

export type ModelProfile = "default" | "weak_cpu";
export type RoutingMode = "auto" | "easy_local" | "hard_external";

export const DEFAULT_CHAT_SETTINGS: ChatSettings = {
  serverBaseUrl: "",
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
