// Dev-bypass detection: when Supabase is unconfigured the dashboard runs in
// local mode — no login, backend grants a dev-admin context. Fill the Supabase
// env vars to enable real auth. Local development only; never deploy this way.
export const isLocalAuth = !process.env.NEXT_PUBLIC_SUPABASE_URL;
