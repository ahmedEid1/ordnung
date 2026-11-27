/**
 * Route `fetch("/api/…")` to an in-memory mock server (no latency) — for page-level tests that
 * exercise real hooks, mutations and streams. Returns the server and a log of requests.
 *
 * `client: "phone"` makes the server the phone listener a paired phone talks to: health says
 * `client: "phone"`, and every request outside the phone's allow-list — read from `web/openapi.json`'s
 * `x-ordnung-phone` marks, the list the API itself enforces — gets 403 `computer_only` and is listed in
 * `srv.refused` (a page in phone mode should leave it empty). `paired: false` is a phone that isn't paired
 * (any more): every request but `POST /api/phone/pair` gets 401 `phone_not_paired`.
 */
import { vi } from "vitest";
import openapiText from "../../openapi.json?raw";
import type { ClientKind } from "@/api/types";
import { setClientKind } from "@/api/clientKind";
import { createMockServer, type MockServer } from "@/mocks/server";
import { phoneScopeFromOpenApi, type PhoneScope } from "@/mocks/phone";

export interface FetchCall {
  method: string;
  path: string;
  body: unknown;
}

export interface MockApiOptions {
  /** Open all New-mail letters first (`?mock=full`). */
  full?: boolean;
  /** The zero-install hosted demo's refusals. */
  staticDemo?: boolean;
  /** Who is asking: the computer (default) or a paired phone (the phone listener and its allow-list). */
  client?: ClientKind;
  /** With `client: "phone"`: whether this phone is paired (default true). */
  paired?: boolean;
}

let scope: PhoneScope | null = null;

/** The phone's allow-list as the API publishes it (`x-ordnung-phone` in `web/openapi.json`). */
export function openApiPhoneScope(): PhoneScope {
  scope ??= phoneScopeFromOpenApi(JSON.parse(openapiText) as { paths: Record<string, Record<string, unknown>> });
  return scope;
}

export function useMockApi(opts: MockApiOptions = {}): { srv: MockServer; calls: FetchCall[] } {
  const phone = opts.client === "phone";
  const srv = createMockServer({ staticDemo: Boolean(opts.staticDemo), latency: 0, phoneScope: phone ? openApiPhoneScope() : undefined });
  if (opts.full) srv.openAllMail();
  if (phone && opts.paired === false) srv.phone.removeThisPhone();
  // what the app learns from health (renderWithProviders seeds a phone's health from it)
  setClientKind(phone ? "phone" : "computer");
  const calls: FetchCall[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const { url, ...call } = request(input, init);
    calls.push(call);
    return srv.handle(call.method, call.path, url.searchParams, call.body, init?.signal ?? null);
  });
  return { srv, calls };
}

/** A fetch call as the mock server reads it: method, path under /api, the JSON body parsed. */
function request(input: RequestInfo | URL, init?: RequestInit): FetchCall & { url: URL } {
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
  return { url, method, path: url.pathname.replace(/^\/api/, ""), body };
}

/**
 * After {@link useMockApi}: the requests `match` picks answer 500, as a server that broke would — to see what a failed
 * request (an Undo's, say) leaves behind. `failed` counts them.
 */
export function failRequests(match: (call: FetchCall) => boolean): { failed: number } {
  const mocked = globalThis.fetch;
  const seen = { failed: 0 };
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    if (!match(request(input, init))) return mocked(input, init);
    seen.failed += 1;
    return new Response(JSON.stringify({ detail: "Failed on purpose." }), { status: 500, headers: { "Content-Type": "application/json" } });
  });
  return seen;
}

/** Requests {@link holdRequests} keeps unanswered, and how the test answers them. */
export interface HeldRequests {
  /** How many requests it picked so far (answered or not). */
  readonly count: number;
  /** How many of them are still unanswered. */
  readonly waiting: number;
  /** Answer the waiting ones as the mock server would. */
  release(): void;
  /** Answer the waiting ones with 500, as a server that broke would (see {@link failRequests}). */
  fail(): void;
}

/**
 * After {@link useMockApi}: the requests `match` picks stay unanswered until the test answers them with `release()` or
 * `fail()` — to see a button while its own request is on its way (busy, keeping focus, taking no second press). Every
 * later request it picks waits too, until the next `release()` or `fail()`. A held request reaches the mock server (and
 * `useMockApi`'s `calls`) only when it is released; `count` counts it from the start.
 */
export function holdRequests(match: (call: FetchCall) => boolean): HeldRequests {
  const mocked = globalThis.fetch;
  const waiting: ((answer: "ok" | "fail") => void)[] = [];
  let count = 0;
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) => {
    if (!match(request(input, init))) return mocked(input, init);
    count += 1;
    return new Promise<Response>((resolve, reject) => {
      waiting.push((answer) => {
        if (answer === "fail") resolve(new Response(JSON.stringify({ detail: "Failed on purpose." }), { status: 500, headers: { "Content-Type": "application/json" } }));
        else mocked(input, init).then(resolve, reject);
      });
    });
  });
  const answer = (how: "ok" | "fail") => waiting.splice(0).forEach((reply) => reply(how));
  return {
    get count() {
      return count;
    },
    get waiting() {
      return waiting.length;
    },
    release: () => answer("ok"),
    fail: () => answer("fail"),
  };
}
