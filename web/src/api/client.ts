/**
 * Minimal typed fetch wrapper for the Ordnung API.
 *
 * - Base path `/api`, JSON in and out, `credentials: "same-origin"` (session cookie).
 * - Every non-GET request carries `X-Ordnung-Client: web` (required by the API's CSRF defence).
 * - Errors become {@link ApiError} with the HTTP status and the message from FastAPI's `{detail}` — or, when
 *   the answer has no words for a person (a server error that says no more than its status, a body that isn't
 *   Ordnung's JSON), a plain sentence, the server's own words kept as `technical` (UX audit U9: a toast said
 *   "Internal Server Error").
 */

import { clientKind } from "./clientKind";

export const API_BASE = "/api";

/** The sentence for a server error that brings no words for a person (what it said is kept as `technical`). */
export const SERVER_PROBLEM = "Ordnung ran into a problem it didn't expect. Your letters are safe — try again, and restart Ordnung if it keeps happening.";
/** The sentence for an answer the page can't read (not Ordnung's JSON: a proxy's page, a cut-off body). */
export const UNREADABLE_ANSWER = "Ordnung's answer couldn't be read. Your letters are safe — try again, and restart Ordnung if it keeps happening.";
/** Ordnung didn't answer (a network error): the computer's own tab says where it should be running. */
export const UNREACHABLE = "Ordnung isn't reachable. Is it still running on this computer?";
/**
 * Ordnung didn't answer a paired phone: the computer may be off or asleep, Ordnung stopped, or the phone left the
 * home Wi‑Fi ("Wi‑Fi" with a non-breaking hyphen, U+2011).
 */
export const PHONE_UNREACHABLE = "Can't reach your computer. Is it on, with Ordnung running, and is this phone on the same Wi‑Fi?";
/** The `code` of an answer the page couldn't read ({@link UNREADABLE_ANSWER}). */
export const UNREADABLE_CODE = "unreadable_answer";
/** How much of a body that isn't JSON is kept for "Technical details". */
const TECHNICAL_MAX = 300;
/** A server error's status said in words — no sentence for a person. */
const REASON_PHRASE = /^(internal server error|bad gateway|service unavailable|gateway timeout)$/i;

/** Error thrown for any non-2xx API response (or network failure, status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  /** Optional machine-readable code from the body (e.g. `static_demo`, `llm_paused`). */
  readonly code: string | null;
  /**
   * What the server said in its own words when the message is a plain sentence instead ("Internal Server Error",
   * "database is locked", an unexpected error's name) — shown under "Technical details", never as the sentence.
   */
  readonly technical: string | null;

  constructor(status: number, message: string, detail?: unknown, code?: string | null, technical?: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code ?? null;
    this.technical = technical ?? null;
  }

  /** True for the zero-install hosted demo's "needs Claude" refusal. */
  get isStaticDemo(): boolean {
    return this.code === "static_demo";
  }

  /**
   * True for something a demo can't do: the hosted demo's refusal, or `ordnung demo` (recorded
   * answers only) asked to read a letter it has no recording for (`demo_replay`). Said as a limit of
   * the demo, not as a failure.
   */
  get isDemoLimit(): boolean {
    return this.code === "static_demo" || this.code === "demo_replay";
  }
}

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** JSON-serialisable body, or FormData for uploads. */
  body?: unknown;
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

/** Build `/api<path>?query` skipping empty values. */
export function apiPath(path: string, query?: Record<string, QueryValue>): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  let url = `${API_BASE}${p}`;
  if (query) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === "") continue;
      qs.set(k, String(v));
    }
    const s = qs.toString();
    if (s) url += `?${s}`;
  }
  return url;
}

/** Extract a human message from a FastAPI error body (`{detail: string | [{msg}] | {message}}`). */
export function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : null))
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return fallback;
}

function buildInit(opts: RequestOptions): RequestInit {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
  if (method !== "GET") headers["X-Ordnung-Client"] = "web";
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  return { method, headers, body, credentials: "same-origin", signal: opts.signal };
}

/** A body's words on one line, cut to {@link TECHNICAL_MAX} characters (an HTML error page can be long). */
function clip(text: string): string {
  const line = text.replace(/\s+/g, " ").trim();
  return line.length > TECHNICAL_MAX ? `${line.slice(0, TECHNICAL_MAX)}…` : line;
}

/**
 * An answer that isn't 2xx as an {@link ApiError}: Ordnung's `{detail, code}` in its own words, anything else as a
 * plain sentence with the raw words kept for "Technical details". Exported for requests made without `fetch` (a
 * phone's upload with progress, `features/phone/upload.ts`).
 */
export async function toApiError(res: Response): Promise<ApiError> {
  let detail: unknown = undefined;
  let code: string | null = null;
  let technical: string | null = null;
  let json = false;
  try {
    const text = await res.text();
    if (text) {
      try {
        const body = JSON.parse(text) as { detail?: unknown; code?: unknown; error?: unknown };
        json = true;
        detail = body?.detail ?? body;
        if (typeof body?.code === "string") code = body.code;
        // an unexpected error's name (`app.py`), for "Technical details"
        if (typeof body?.error === "string") technical = body.error;
      } catch {
        detail = text;
      }
    }
  } catch {
    /* body unreadable */
  }
  const fallback = res.statusText || `Request failed (${res.status})`;
  const words = json ? messageFromDetail(detail, "") : "";
  // Ordnung's own words for the person (a refusal, Claude signed out, the sentence for an unexpected error) — unless
  // a server error says no more than its status ("Internal Server Error")
  if (json && !(res.status >= 500 && (!words || words === res.statusText || REASON_PHRASE.test(words)))) {
    return new ApiError(res.status, words || fallback, detail, code, technical);
  }
  // a server error without words for the person, or an answer that isn't Ordnung's JSON: a plain sentence, the raw words kept
  const raw = clip(typeof detail === "string" ? detail : words);
  if (res.status >= 500) return new ApiError(res.status, SERVER_PROBLEM, detail, code, technical ?? (raw || fallback));
  return new ApiError(res.status, UNREADABLE_ANSWER, detail, UNREADABLE_CODE, raw || fallback);
}

/** Perform a request and return the raw Response (throws {@link ApiError} on non-2xx). */
export async function requestRaw(path: string, opts: RequestOptions = {}): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(apiPath(path, opts.query), buildInit(opts));
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, clientKind() === "phone" ? PHONE_UNREACHABLE : UNREACHABLE, err);
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

/** Perform a JSON request. 204 / empty bodies resolve to `undefined`. */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await requestRaw(path, opts);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    // not Ordnung's JSON (a proxy's page, a cut-off answer): said plainly, never as a parser's message
    throw new ApiError(res.status, UNREADABLE_ANSWER, text, UNREADABLE_CODE, clip(text));
  }
}

// ------------------------------------------------------------------------------------------------
// Asset URLs (page images, thumbnails, PDFs, .ics). In mock/static-demo mode a resolver swaps
// them for data: URLs because <img>/<a href> requests bypass the fetch interceptor.
// ------------------------------------------------------------------------------------------------

type AssetResolver = (path: string) => string | null;
let assetResolver: AssetResolver | null = null;

/** Install (or clear with null) a resolver that maps API asset paths to other URLs. */
export function setAssetResolver(resolver: AssetResolver | null): void {
  assetResolver = resolver;
}

/** URL for an API-served asset such as `/documents/doc_x/pages/1.jpg`. */
export function assetUrl(path: string, query?: Record<string, QueryValue>): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const resolved = assetResolver?.(p);
  return resolved ?? apiPath(p, query);
}
