import "server-only";
import { createClient } from "@/lib/supabase/server";
import { isLocalAuth } from "@/lib/authMode";

export async function apiFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!BASE_URL) throw new Error("NEXT_PUBLIC_API_BASE_URL is required");

  // Local dev bypass: backend grants a dev-admin context and ignores the token.
  let token = "dev-local";
  if (!isLocalAuth) {
    const supabase = await createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new Error("No active session — cannot make authenticated API request");
    }
    token = session.access_token;
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
  });

  if (response.status === 401) {
    throw new Error("API request unauthorized — session may have expired");
  }

  if (response.status >= 500) {
    throw new Error(`API server error: ${response.status} ${response.statusText}`);
  }

  return response;
}
