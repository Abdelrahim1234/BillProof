import "server-only";

import type { NextRequest } from "next/server";
import {
  backendBaseUrl,
  backendTarget,
  DEFAULT_MAX_REQUEST_BYTES,
  DEFAULT_MAX_RESPONSE_BYTES,
  DEFAULT_PROXY_TIMEOUT_MS,
  effectiveRequestOrigin,
  forwardedRequestHeaders,
  mutationOriginAllowed,
  PayloadTooLargeError,
  positiveInteger,
  ProxyConfigError,
  readBoundedBody,
  secureCaseCreationBody,
  shouldClearCaseCookie,
} from "@/lib/backend-proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RouteContext = { params: Promise<{ path: string[] }> };
const CASE_TOKEN_COOKIE = "billproof_case_token";

function protectedCasePath(path: string[]): boolean {
  return path[0] === "cases" && path.length >= 2;
}

function createsCase(path: string[], method: string): boolean {
  return (
    method === "POST" &&
    ((path.length === 1 && path[0] === "cases") ||
      (path.length === 2 && path[0] === "demo" && path[1] === "cases"))
  );
}

function cookieHeader(token: string, expiresAt: unknown, secure: boolean): string {
  const expires = typeof expiresAt === "string" ? Date.parse(expiresAt) : Number.NaN;
  const seconds = Number.isFinite(expires)
    ? Math.max(60, Math.min(7 * 24 * 60 * 60, Math.floor((expires - Date.now()) / 1000)))
    : 24 * 60 * 60;
  return [
    `${CASE_TOKEN_COOKIE}=${encodeURIComponent(token)}`,
    "HttpOnly",
    "SameSite=Lax",
    "Path=/api/v1",
    `Max-Age=${seconds}`,
    secure ? "Secure" : "",
  ]
    .filter(Boolean)
    .join("; ");
}

function clearCookieHeader(secure: boolean): string {
  return [
    `${CASE_TOKEN_COOKIE}=`,
    "HttpOnly",
    "SameSite=Lax",
    "Path=/api/v1",
    "Max-Age=0",
    secure ? "Secure" : "",
  ]
    .filter(Boolean)
    .join("; ");
}

function errorResponse(status: number, code: string, message: string, retryable = false): Response {
  const requestId = crypto.randomUUID();
  return Response.json(
    {
      error: { code, message, field: null, retryable, details: {} },
      request_id: requestId,
    },
    {
      status,
      headers: {
        "cache-control": "no-store",
        "x-request-id": requestId,
      },
    },
  );
}

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  let base: URL;
  try {
    base = backendBaseUrl();
  } catch (error) {
    const message = error instanceof ProxyConfigError ? error.message : "The backend API is not configured.";
    return errorResponse(503, "BACKEND_NOT_CONFIGURED", message);
  }

  let publicOrigin: URL;
  try {
    publicOrigin = effectiveRequestOrigin(request.headers, request.nextUrl.protocol);
  } catch {
    return errorResponse(400, "INVALID_REQUEST_ORIGIN", "The request host or protocol is invalid.");
  }

  const { path } = await context.params;
  const mutating = !["GET", "HEAD", "OPTIONS"].includes(request.method);
  const origin = request.headers.get("origin");
  if (mutating && !mutationOriginAllowed(origin, publicOrigin)) {
    return errorResponse(403, "CROSS_ORIGIN_REQUEST", "Cross-origin changes are not allowed.");
  }

  const maximumRequestBytes = positiveInteger(
    process.env.BFF_MAX_REQUEST_BYTES,
    DEFAULT_MAX_REQUEST_BYTES,
  );
  const maximumResponseBytes = positiveInteger(
    process.env.BFF_MAX_RESPONSE_BYTES,
    DEFAULT_MAX_RESPONSE_BYTES,
  );
  const timeoutMs = positiveInteger(process.env.BFF_TIMEOUT_MS, DEFAULT_PROXY_TIMEOUT_MS);

  const contentLength = Number(request.headers.get("content-length") ?? 0);
  if (Number.isFinite(contentLength) && contentLength > maximumRequestBytes) {
    return errorResponse(413, "PAYLOAD_TOO_LARGE", "The request is too large for this deployment.");
  }

  let body: ArrayBuffer | null = null;
  try {
    if (request.method !== "GET" && request.method !== "HEAD") {
      body = await readBoundedBody(request.body, maximumRequestBytes);
    }
  } catch (error) {
    if (error instanceof PayloadTooLargeError) {
      return errorResponse(413, "PAYLOAD_TOO_LARGE", "The request is too large for this deployment.");
    }
    return errorResponse(400, "INVALID_REQUEST_BODY", "The request body could not be read.");
  }

  const target = backendTarget(base, path, request.nextUrl.search);
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const abort = () => controller.abort();
  request.signal.addEventListener("abort", abort, { once: true });

  try {
    const requestHeaders = forwardedRequestHeaders(request.headers);
    if (protectedCasePath(path)) {
      const token = request.cookies.get(CASE_TOKEN_COOKIE)?.value;
      if (token) requestHeaders.set("authorization", `Bearer ${token}`);
    }

    const upstream = await fetch(target, {
      method: request.method,
      headers: requestHeaders,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: controller.signal,
    });

    const upstreamLength = Number(upstream.headers.get("content-length") ?? 0);
    if (Number.isFinite(upstreamLength) && upstreamLength > maximumResponseBytes) {
      controller.abort();
      return errorResponse(502, "UPSTREAM_RESPONSE_TOO_LARGE", "The backend returned too much data.");
    }

    let responseBody: ArrayBuffer | null;
    try {
      responseBody = request.method === "HEAD" ? null : await readBoundedBody(upstream.body, maximumResponseBytes);
    } catch (error) {
      if (error instanceof PayloadTooLargeError) {
        controller.abort();
        return errorResponse(502, "UPSTREAM_RESPONSE_TOO_LARGE", "The backend returned too much data.");
      }
      throw error;
    }

    // Only browser-relevant headers cross the trust boundary. In particular,
    // x-railway-*, x-hikari-* and upstream server identity never leave here.
    const headers = new Headers({ "cache-control": "no-store" });
    const contentType = upstream.headers.get("content-type");
    if (contentType) headers.set("content-type", contentType);
    const requestId = upstream.headers.get("x-request-id");
    if (requestId) headers.set("x-request-id", requestId);

    const secureCookie = publicOrigin.protocol === "https:";
    if (upstream.ok && createsCase(path, request.method)) {
      const secured = secureCaseCreationBody(responseBody);
      responseBody = secured.body;
      if (!secured.token) {
        return errorResponse(502, "INVALID_BACKEND_RESPONSE", "The backend returned an invalid case session.");
      }
      headers.set("set-cookie", cookieHeader(secured.token, secured.expiresAt, secureCookie));
    } else if (
      (upstream.ok && request.method === "DELETE" && path[0] === "cases" && path.length === 2) ||
      (protectedCasePath(path) && shouldClearCaseCookie(upstream.status, responseBody))
    ) {
      headers.set("set-cookie", clearCookieHeader(secureCookie));
    }

    return new Response(responseBody, { status: upstream.status, headers });
  } catch (error) {
    if (timedOut) {
      return errorResponse(504, "BACKEND_TIMEOUT", "The backend took too long to respond.", true);
    }
    if (request.signal.aborted) {
      return errorResponse(499, "CLIENT_CLOSED_REQUEST", "The request was cancelled.");
    }
    return errorResponse(502, "BACKEND_UNAVAILABLE", "The BillBuster backend is temporarily unavailable.", true);
  } finally {
    clearTimeout(timeout);
    request.signal.removeEventListener("abort", abort);
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
