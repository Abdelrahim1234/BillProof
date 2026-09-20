import assert from "node:assert/strict";
import test from "node:test";

import {
  backendBaseUrl,
  backendTarget,
  effectiveRequestOrigin,
  forwardedRequestHeaders,
  mutationOriginAllowed,
  PayloadTooLargeError,
  positiveInteger,
  readBoundedBody,
  secureCaseCreationBody,
  shouldClearCaseCookie,
} from "../lib/backend-proxy.ts";

test("effective request origin supports localhost, loopback, and LAN hosts", () => {
  assert.equal(
    effectiveRequestOrigin(new Headers({ host: "localhost:3000" }), "http:").origin,
    "http://localhost:3000",
  );
  assert.equal(
    effectiveRequestOrigin(new Headers({ host: "127.0.0.1:3000" }), "http:").origin,
    "http://127.0.0.1:3000",
  );
  assert.equal(
    effectiveRequestOrigin(new Headers({ host: "192.168.1.25:3000" }), "http:").origin,
    "http://192.168.1.25:3000",
  );
});

test("effective request origin uses the first validated forwarded HTTPS host", () => {
  const origin = effectiveRequestOrigin(
    new Headers({
      host: "internal-service:3000",
      "x-forwarded-host": "demo.example.test, internal-service:3000",
      "x-forwarded-proto": "https, http",
    }),
    "http:",
  );
  assert.equal(origin.origin, "https://demo.example.test");
  assert.equal(origin.protocol, "https:");
});

test("request origin matching accepts effective origins and rejects mismatches", () => {
  const loopback = effectiveRequestOrigin(new Headers({ host: "127.0.0.1:3000" }), "http:");
  assert.equal(mutationOriginAllowed("http://127.0.0.1:3000", loopback), true);
  assert.equal(mutationOriginAllowed("http://localhost:3000", loopback), false);
  assert.equal(mutationOriginAllowed("https://127.0.0.1:3000", loopback), false);
  assert.equal(mutationOriginAllowed("http://127.0.0.1:3000/path", loopback), false);
  assert.equal(mutationOriginAllowed(null, loopback), true);
});

test("effective request origin rejects malformed forwarding values", () => {
  assert.throws(
    () => effectiveRequestOrigin(new Headers({ host: "localhost:3000", "x-forwarded-proto": "javascript" }), "http:"),
    /HTTP or HTTPS/i,
  );
  assert.throws(
    () => effectiveRequestOrigin(new Headers({ "x-forwarded-host": "user@example.test" }), "https:"),
    /host is invalid/i,
  );
  assert.throws(
    () => effectiveRequestOrigin(new Headers({ host: "example..test" }), "https:"),
    /host is invalid/i,
  );
});

test("backend URL is server-configured, credential-free, and origin-only", () => {
  assert.equal(backendBaseUrl({ BACKEND_API_URL: "https://api.example.test" }).href, "https://api.example.test/");
  assert.throws(() => backendBaseUrl({}), /not configured/i);
  assert.throws(() => backendBaseUrl({ BACKEND_API_URL: "https://user:secret@example.test" }), /credentials/i);
  assert.throws(() => backendBaseUrl({ BACKEND_API_URL: "https://api.example.test/base" }), /without a path/i);
});

test("target preserves query values while encoding path segments", () => {
  const target = backendTarget(
    new URL("https://api.example.test"),
    ["screens", "room/name", "latest"],
    "?code=71046&name=a+b",
  );
  assert.equal(
    target.href,
    "https://api.example.test/api/v1/screens/room%2Fname/latest?code=71046&name=a+b",
  );
});

test("request header allowlist excludes browser credentials and infrastructure headers", () => {
  const headers = forwardedRequestHeaders(
    new Headers({
      accept: "application/json",
      authorization: "Bearer opaque",
      cookie: "secret=value",
      "content-type": "multipart/form-data; boundary=preserve-this-boundary",
      "x-railway-request-id": "internal",
    }),
  );
  assert.equal(headers.get("authorization"), null);
  assert.equal(headers.get("content-type"), "multipart/form-data; boundary=preserve-this-boundary");
  assert.equal(headers.get("cookie"), null);
  assert.equal(headers.get("x-railway-request-id"), null);
});

test("bounded reader accepts small bodies and rejects oversized streams", async () => {
  const small = new Response("hello").body;
  const result = await readBoundedBody(small, 5);
  assert.equal(new TextDecoder().decode(result!), "hello");

  await assert.rejects(readBoundedBody(new Response("too large").body, 3), PayloadTooLargeError);
});

test("positive integer environment parsing falls back safely", () => {
  assert.equal(positiveInteger("2500", 100), 2500);
  assert.equal(positiveInteger("0", 100), 100);
  assert.equal(positiveInteger("nope", 100), 100);
});

test("case creation credentials are removed from the browser response", () => {
  const original = new TextEncoder().encode(
    JSON.stringify({
      data: {
        case_id: "case-1",
        access_token: "raw-secret-token",
        expires_at: "2030-01-01T00:00:00Z",
      },
      request_id: "request-1",
    }),
  );
  const secured = secureCaseCreationBody(original.buffer as ArrayBuffer);
  assert.equal(secured.token, "raw-secret-token");
  const browserBody = new TextDecoder().decode(secured.body!);
  assert.equal(browserBody.includes("raw-secret-token"), false);
  assert.deepEqual(JSON.parse(browserBody).data, {
    case_id: "case-1",
    expires_at: "2030-01-01T00:00:00Z",
  });
});

test("case cookie clearing distinguishes authentication failures from market policy", () => {
  const body = (code: string) => {
    const encoded = new TextEncoder().encode(JSON.stringify({ error: { code } }));
    return encoded.buffer.slice(encoded.byteOffset, encoded.byteOffset + encoded.byteLength) as ArrayBuffer;
  };

  assert.equal(shouldClearCaseCookie(401, null), true);
  assert.equal(shouldClearCaseCookie(403, body("INVALID_CASE_TOKEN")), true);
  assert.equal(shouldClearCaseCookie(403, body("CASE_TOKEN_EXPIRED")), true);
  assert.equal(shouldClearCaseCookie(403, body("CASE_OUTSIDE_ACTIVE_MARKET")), false);
  assert.equal(shouldClearCaseCookie(403, body("FORBIDDEN")), false);
  assert.equal(shouldClearCaseCookie(404, body("NOT_FOUND")), false);
});
