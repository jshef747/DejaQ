import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // In local dev (no Supabase env) this client must not be used; callers gate on
  // isLocalAuth. Throw only when Supabase is partially configured.
  if (!url) throw new Error("NEXT_PUBLIC_SUPABASE_URL is required");
  if (!key) throw new Error("NEXT_PUBLIC_SUPABASE_ANON_KEY is required");

  const cookieStore = await cookies();

  return createServerClient(url, key, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options)
          );
        } catch {
          // setAll called from a Server Component — middleware handles refresh
        }
      },
    },
  });
}
