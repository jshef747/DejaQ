/** @type {import('next').NextConfig} */
const nextConfig = {
  // The dev-tools indicator defaults to bottom-left, which sits on top of the
  // sidebar's bottom-left signed-in user block (avatar + email + role).
  devIndicators: { position: "bottom-right" },
  // Next 16 blocks /_next/* dev-asset requests (HMR, RSC payload chunks,
  // fonts) from an origin outside allowedDevOrigins, and "127.0.0.1" isn't
  // in the default allowlist alongside "localhost" - hitting this dev
  // server at http://127.0.0.1:<port> renders the static shell but never
  // hydrates (no console error; the only clue is a blocked-cross-origin
  // line in the dev server's own terminal log). Same bug and fix as
  // chat/next.config.mjs - see AGENTS.md "Chat app dev server silently
  // fails to hydrate when hit via 127.0.0.1, not localhost".
  allowedDevOrigins: ["127.0.0.1"],
  experimental: {
    serverActions: {
      // Matches the backend's DEJAQ_MAX_ATTACHMENT_BYTES (10 MB) — the Knowledge
      // Base file upload goes through a Server Action, which defaults to a 1 MB
      // body limit and otherwise rejects any real document before it reaches the API.
      bodySizeLimit: "10mb",
    },
  },
};

export default nextConfig;
