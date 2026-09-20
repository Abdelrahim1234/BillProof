import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
