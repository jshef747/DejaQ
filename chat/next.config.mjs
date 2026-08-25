/** @type {import('next').NextConfig} */
const nextConfig = {
  // Next 16 blocks /_next/* dev-asset requests (HMR, RSC payload chunks, fonts)
  // from an origin it doesn't recognize as "local" - and its own allowlist
  // apparently doesn't treat "127.0.0.1" as equivalent to "localhost": hitting
  // the dev server at http://127.0.0.1:<port> silently fails to hydrate (every
  // client effect never runs, no console error at all - the only visible clue
  // is a blocked-cross-origin warning in the SERVER's own terminal log, not the
  // browser). Reproduced live: the exact same page hydrates fine at
  // http://localhost:<port>. 127.0.0.1 always means "this machine", so it is
  // exactly as safe to allow as "localhost" already implicitly is.
  //
  // In LAN mode (start.sh --lan) the dev server is also reached via the host's
  // LAN IP, which needs the same allowlisting - DEJAQ_LAN_IP is inert when unset
  // (default run).
  allowedDevOrigins: [
    "127.0.0.1",
    ...(process.env.DEJAQ_LAN_IP ? [process.env.DEJAQ_LAN_IP] : []),
  ],
};

export default nextConfig;
