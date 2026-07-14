/** @type {import('next').NextConfig} */
const nextConfig = {
  // In LAN mode (start.sh --lan) the dev server is reached via the host's LAN IP.
  // Next 16 blocks /_next/* dev-asset requests from non-localhost origins unless
  // that origin is allowlisted. Inert when DEJAQ_LAN_IP is unset (default run).
  ...(process.env.DEJAQ_LAN_IP
    ? { allowedDevOrigins: [process.env.DEJAQ_LAN_IP] }
    : {}),
};

export default nextConfig;
