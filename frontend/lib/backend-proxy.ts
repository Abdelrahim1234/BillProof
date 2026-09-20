/**
 * Server-side proxy policy shared by the route handler and its unit tests.
 *
 * This module deliberately contains no import-time environment reads. That
 * keeps `next build` deterministic and lets a missing backend URL fail as a
 * bounded 503 at request time instead of leaking configuration into a client
 * bundle.
 */

export const DEFAULT_PROXY_TIMEOUT_MS = 60_000;
export const DEFAULT_MAX_REQUEST_BYTES = 5 * 1024 * 1024;
export const DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024;

const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "accept-language",
  "content-type",
  "if-match",
] as const;

export class ProxyConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProxyConfigError";
  }
}

export class PayloadTooLargeError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PayloadTooLargeError";
  }
}

function firstHeaderValue(value: string | null): string | null {
  if (!value) return null;
  const first = value.split(",", 1)[0]?.trim();
  return first || null;
}

function normalizedHttpProtocol(value: string): "http" | "https" {
  const normalized = value.trim().toLowerCase().replace(/:$/, "");
  if (normalized !== "http" && normalized !== "https") {
    throw new ProxyConfigError("The request protocol must be HTTP or HTTPS.");
  }
  return normalized;
}

function validHostname(hostname: string): boolean {
  // URL.hostname keeps brackets around IPv6 literals. URL construction below
  // performs the actual IPv6 validation, so only the bracket shape is needed
  // here. DNS/IPv4 labels are deliberately ASCII-only at this trust boundary.
  if (hostname.startsWith("[") && hostname.endsWith("]")) return true;
  const value = hostname.endsWith(".") ? hostname.slice(0, -1) : hostname;
  if (!value || value.length > 253) return false;
  return value.split(".").every(
    (label) =>
      label.length > 0 &&
      label.length <= 63 &&
      /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/i.test(label),
  );
}

/**
 * Resolve the browser-visible origin behind Next.js, a LAN address, or a
 * trusted reverse proxy. Next's request.nextUrl may retain its canonical
 * localhost host, so it cannot be used for same-origin checks by itself.
 *
 * Reverse proxies conventionally append comma-separated forwarding values;
 * the first value is the public edge value. Every selected value is parsed
 * and validated before it influences CSRF checks or cookie security.
 */
export function effectiveRequestOrigin(headers: Headers, fallbackProtocol: string): URL {
  const host = firstHeaderValue(headers.get("x-forwarded-host")) ?? firstHeaderValue(headers.get("host"));
  if (!host || /[\s/@\\?#]/.test(host)) {
    throw new ProxyConfigError("The request host is invalid.");
  }

  const protocol = normalizedHttpProtocol(
    firstHeaderValue(headers.get("x-forwarded-proto")) ?? fallbackProtocol,
  );

  let parsed: URL;
  try {
    parsed = new URL(`${protocol}://${host}`);
  } catch {
    throw new ProxyConfigError("The request host is invalid.");
  }

  if (
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash ||
    !validHostname(parsed.hostname)
  ) {
    throw new ProxyConfigError("The request host is invalid.");
  }

  // Return the normalized origin (including a non-default port), never the
  // raw forwarding value.
  return new URL(parsed.origin);
}

/** Missing Origin preserves non-browser clients; a supplied Origin must be a
 * single, origin-only HTTP(S) URL that exactly matches the effective request. */
export function mutationOriginAllowed(incomingOrigin: string | null, effectiveOrigin: URL): boolean {
  if (!incomingOrigin) return true;
  if (incomingOrigin !== incomingOrigin.trim() || incomingOrigin.includes(",")) return false;

  try {
    const parsed = new URL(incomingOrigin);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      !parsed.username &&
      !parsed.password &&
      parsed.pathname === "/" &&
      !parsed.search &&
      !parsed.hash &&
      parsed.origin === effectiveOrigin.origin
    );
  } catch {
    return false;
  }
}

type BackendEnvironment = {
  BACKEND_API_URL?: string;
  BACKEND_URL?: string;
};

export function backendBaseUrl(
  env: BackendEnvironment = {
    BACKEND_API_URL: process.env.BACKEND_API_URL,
    BACKEND_URL: process.env.BACKEND_URL,
  },
): URL {
  // BACKEND_URL is accepted temporarily so the currently deployed project can
  // migrate without downtime. New environments should set BACKEND_API_URL.
  const configured = env.BACKEND_API_URL?.trim() || env.BACKEND_URL?.trim();
  if (!configured) {
    throw new ProxyConfigError("The backend API is not configured.");
  }

  let url: URL;
  try {
    url = new URL(configured);
  } catch {
    throw new ProxyConfigError("The backend API configuration is invalid.");
  }

  if (!(["http:", "https:"] as string[]).includes(url.protocol)) {
    throw new ProxyConfigError("The backend API must use HTTP or HTTPS.");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new ProxyConfigError("The backend API URL must not contain credentials, a query, or a fragment.");
  }
  if (url.pathname !== "/" && url.pathname !== "") {
    throw new ProxyConfigError("The backend API URL must be an origin without a path.");
  }

  url.pathname = "/";
  return url;
}

export function backendTarget(base: URL, path: string[], search: string): URL {
  const encodedPath = path.map((part) => encodeURIComponent(part)).join("/");
  const target = new URL(`/api/v1/${encodedPath}`, base);
  target.search = search;
  return target;
}

export function forwardedRequestHeaders(incoming: Headers): Headers {
  const outgoing = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = incoming.get(name);
    if (value) outgoing.set(name, value);
  }
  return outgoing;
}

export function positiveInteger(value: string | undefined, fallback: number): number {
  if (!value) return fallback;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export async function readBoundedBody(
  body: ReadableStream<Uint8Array> | null,
  maximumBytes: number,
): Promise<ArrayBuffer | null> {
  if (!body) return null;

  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maximumBytes) {
        await reader.cancel();
        throw new PayloadTooLargeError(`Payload exceeds the ${maximumBytes}-byte proxy limit.`);
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const combined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return combined.buffer;
}

export function secureCaseCreationBody(
  body: ArrayBuffer | null,
): { body: ArrayBuffer | null; token: string | null; expiresAt: unknown } {
  if (!body) return { body, token: null, expiresAt: null };
  try {
    const parsed = JSON.parse(new TextDecoder().decode(body)) as {
      data?: Record<string, unknown>;
    };
    const token = typeof parsed.data?.access_token === "string" ? parsed.data.access_token : null;
    const expiresAt = parsed.data?.expires_at;
    if (!token || !parsed.data) return { body, token: null, expiresAt };
    delete parsed.data.access_token;
    const secured = new TextEncoder().encode(JSON.stringify(parsed));
    return {
      body: secured.buffer.slice(secured.byteOffset, secured.byteOffset + secured.byteLength) as ArrayBuffer,
      token,
      expiresAt,
    };
  } catch {
    return { body, token: null, expiresAt: null };
  }
}

export function shouldClearCaseCookie(status: number, body: ArrayBuffer | null): boolean {
  if (status === 401) return true;
  if (status !== 403 || !body) return false;

  try {
    const parsed = JSON.parse(new TextDecoder().decode(body)) as {
      error?: { code?: unknown };
    };
    return ["INVALID_CASE_TOKEN", "CASE_TOKEN_EXPIRED"].includes(
      typeof parsed.error?.code === "string" ? parsed.error.code : "",
    );
  } catch {
    // A policy or malformed 403 must not destroy a still-valid capability.
    return false;
  }
}
