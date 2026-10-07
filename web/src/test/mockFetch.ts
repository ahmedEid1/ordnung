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
