/**
 * Mock mode: a `window.fetch` interceptor that serves `/api/*` from an in-memory copy of Sam
 * Rivera's sample life, a mock EventSource for `/api/events`, and data-URL page images.
 *
 * Enabled by `?mock=1` (remembered for the tab in sessionStorage; `?mock=0` turns it off),
 * `?mock=full` (all New-mail letters already opened) or a build with `VITE_STATIC_DEMO=1`
 * (the zero-install hosted demo, where actions that need Claude show a friendly message).
 */
import { setAssetResolver } from "@/api/client";
import { emit, installMockEventSource } from "./events";
import { createMockServer, type MockServer } from "./server";
import { isStaticDemo, mockMode } from "./mode";

export { isStaticDemo, mockMode, shouldUseMocks } from "./mode";

let server: MockServer | null = null;

/** Install the interceptors (idempotent). Returns the mock server for dev tools / tests. */
export function installMocks(opts: { latency?: number; full?: boolean } = {}): MockServer {
  if (server) return server;
  const srv = createMockServer({ staticDemo: isStaticDemo(), latency: opts.latency });
  server = srv;
  if (opts.full ?? mockMode() === "full") srv.openAllMail();

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const req = input instanceof Request ? input : null;
    const url = new URL(req ? req.url : String(input), window.location.href);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/")) return realFetch(input, init);
    const method = (init?.method ?? req?.method ?? "GET").toUpperCase();
    let body: unknown = undefined;
    const rawBody = init?.body ?? null;
    if (rawBody instanceof FormData) body = rawBody;
    else if (typeof rawBody === "string") {
      try {
        body = JSON.parse(rawBody);
      } catch {
        body = rawBody;
      }
    } else if (req && method !== "GET") {
      try {
        body = await req.clone().json();
      } catch {
        body = undefined;
      }
    }
    return srv.handle(method, url.pathname.slice(4), url.searchParams, body, init?.signal ?? req?.signal ?? null);
  };

  installMockEventSource();
  setAssetResolver((path, query) => srv.resolveAsset(path, query));
  Object.assign(window, { __ordnungMock: srv, __ordnungMockEmit: emit });
  return srv;
}
