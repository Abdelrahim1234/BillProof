import os from "node:os";

/**
 * Best guess at the address a phone on the same Wi-Fi can reach this laptop on.
 * Private ranges are preferred, since those are what venue Wi-Fi hands out.
 */
export function lanAddress(): string | null {
  const found: string[] = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const net of list ?? []) {
      if (net.family !== "IPv4" || net.internal) continue;
      found.push(net.address);
    }
  }
  const rank = (a: string) =>
    a.startsWith("192.168.") ? 0 : a.startsWith("10.") ? 1 : /^172\.(1[6-9]|2\d|3[01])\./.test(a) ? 2 : 3;
  found.sort((a, b) => rank(a) - rank(b));
  return found[0] ?? null;
}

export function isLoopback(host: string): boolean {
  const name = host.split(":")[0];
  return name === "localhost" || name === "127.0.0.1" || name === "::1" || name === "0.0.0.0";
}
