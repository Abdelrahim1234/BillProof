import type { NextConfig } from "next";

// Phones on the venue Wi-Fi only ever talk to this Next server; it proxies the
// API to the backend. That keeps one origin (no CORS) and means port 8000 never
// has to be reachable from the network.
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${backend}/api/v1/:path*` }];
  },
  // `next dev` blocks cross-origin requests to dev assets, which is exactly what
  // a phone on the LAN does. Demo day should use `npm run present` (production),
  // but these keep `npm run dev` usable from a phone or a tunnel too.
  allowedDevOrigins: [
    "10.*.*.*",
    "172.*.*.*",
    "192.168.*.*",
    "*.local",
    "**.trycloudflare.com",
    "**.ngrok-free.app",
    "**.ngrok.app",
  ],
};

export default nextConfig;
