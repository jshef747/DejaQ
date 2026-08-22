/** @type {import('next').NextConfig} */
const nextConfig = {
  // The dev-tools indicator defaults to bottom-left, which sits on top of the
  // sidebar's bottom-left signed-in user block (avatar + email + role).
  devIndicators: { position: "bottom-right" },
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
