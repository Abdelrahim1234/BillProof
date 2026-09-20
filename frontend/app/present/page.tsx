import { headers } from "next/headers";
import QRCode from "qrcode";
import Wall from "@/components/Wall";
import { isLoopback, lanAddress } from "@/lib/lan";

// The projector page: a QR code judges scan, and the comparison they send back.
export const dynamic = "force-dynamic";

/**
 * Where to send phones, in order of preference:
 *   1. ?url= on this page (paste a tunnel URL mid-demo without a restart)
 *   2. PUBLIC_URL in the environment (your domain, or a tunnel)
 *   3. this laptop's LAN address, when the page was opened on localhost
 *   4. whatever host the browser used
 */
async function resolvePublicUrl(override?: string): Promise<{ url: string; source: string }> {
  if (override) return { url: override.replace(/\/$/, ""), source: "?url= override" };

  const env = process.env.PUBLIC_URL;
  if (env) return { url: env.replace(/\/$/, ""), source: "PUBLIC_URL" };

  const host = (await headers()).get("host") ?? "localhost:3000";
  if (isLoopback(host)) {
    const lan = lanAddress();
    const port = host.split(":")[1] ?? "3000";
    if (lan) return { url: `http://${lan}:${port}`, source: "detected Wi-Fi address" };
  }
  return { url: `http://${host}`, source: "this browser's address" };
}

export default async function PresentPage({
  searchParams,
}: {
  searchParams: Promise<{ url?: string; room?: string }>;
}) {
  const params = await searchParams;
  const { url } = await resolvePublicUrl(params.url);

  // Stable by default, so the QR can be printed and survives restarts.
  const roomCode = (params.room ?? process.env.ROOM_CODE ?? "billproof").toLowerCase();
  const phoneUrl = `${url}/?room=${encodeURIComponent(roomCode)}`;
  const svg = await QRCode.toString(phoneUrl, {
    type: "svg",
    margin: 1,
    errorCorrectionLevel: "M",
  });

  return <Wall svg={svg} roomCode={roomCode} />;
}
