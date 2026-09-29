/**
 * Route `fetch("/api/…")` to an in-memory mock server (no latency) — for page-level tests that
 * exercise real hooks, mutations and streams. Returns the server and a log of requests.
 */
import { vi } from "vitest";
import { createMockServer, type MockServer } from "@/mocks/server";

export interface FetchCall {
  method: string;
  path: string;
  body: unknown;
}

export function useMockApi(opts: { full?: boolean; staticDemo?: boolean } = {}): { srv: MockServer; calls: FetchCall[] } {
  const srv = createMockServer({ staticDemo: Boolean(opts.staticDemo), latency: 0 });
  if (opts.full) srv.openAllMail();
  const calls: FetchCall[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = undefined;
    if (typeof init?.body === "string") {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    } else if (init?.body instanceof FormData) {
      body = init.body; // multipart uploads (the mock handlers read the form)
    }
    const path = url.pathname.replace(/^\/api/, "");
    calls.push({ method, path, body });
    return srv.handle(method, path, url.searchParams, body, init?.signal ?? null);
  });
  return { srv, calls };
}
