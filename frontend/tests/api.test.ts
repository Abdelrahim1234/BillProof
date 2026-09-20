import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, api, request } from "../lib/api.ts";

type FetchImplementation = typeof globalThis.fetch;

async function withFetch<T>(implementation: FetchImplementation, run: () => Promise<T>): Promise<T> {
  const original = globalThis.fetch;
  globalThis.fetch = implementation;
  try {
    return await run();
  } finally {
    globalThis.fetch = original;
  }
}

test("typed client uses the same-origin API and accepts an empty evidence result", async () => {
  await withFetch(
    async (input) => {
      assert.equal(input, "/api/v1/prices/search?hospital_id=hospital-1&charge_type=discounted_cash");
      return Response.json({ data: [], request_id: "request-1" });
    },
    async () => assert.deepEqual(await api.cashPrices("hospital-1"), []),
  );
});

test("typed client preserves backend validation errors", async () => {
  await withFetch(
    async () =>
      Response.json(
        {
          error: { code: "VALIDATION_ERROR", message: "Select an active hospital.", field: "hospital_id" },
          request_id: "request-2",
        },
        { status: 422 },
      ),
    async () => {
      await assert.rejects(api.createCase({ hospital_id: "inactive" }), (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "VALIDATION_ERROR");
        assert.equal(error.status, 422);
        assert.equal(error.message, "Select an active hospital.");
        return true;
      });
    },
  );
});

test("typed client turns network failures into a safe unavailable error", async () => {
  await withFetch(
    async () => {
      throw new TypeError("connection refused at an internal host");
    },
    async () => {
      await assert.rejects(api.hospitals(), (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "NETWORK");
        assert.equal(error.status, 0);
        assert.equal(error.message.includes("internal host"), false);
        return true;
      });
    },
  );
});

test("typed client reports its own timeout distinctly", async () => {
  await withFetch(
    (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true },
        );
      }),
    async () => {
      await assert.rejects(request("/ready", { timeoutMs: 5 }), (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "TIMEOUT");
        return true;
      });
    },
  );
});

test("typed client distinguishes caller cancellation from a timeout", async () => {
  await withFetch(
    (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true },
        );
      }),
    async () => {
      const controller = new AbortController();
      const pending = request("/hospitals", { signal: controller.signal });
      controller.abort();
      await assert.rejects(pending, (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "CANCELLED");
        return true;
      });
    },
  );
});
