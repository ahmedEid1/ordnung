/**
 * Minimal typed fetch wrapper for the Ordnung API.
 *
 * - Base path `/api`, JSON in and out, `credentials: "same-origin"` (session cookie).
 * - Every non-GET request carries `X-Ordnung-Client: web` (required by the API's CSRF defence).
 * - Errors become {@link ApiError} with the HTTP status and the message from FastAPI's `{detail}`.
 */

export const API_BASE = "/api";

/** Error thrown for any non-2xx API response (or network failure, status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  /** Optional machine-readable code from the body (e.g. `static_demo`, `llm_paused`). */
  readonly code: string | null;

  constructor(status: number, message: string, detail?: unknown, code?: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code ?? null;
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

async function toApiError(res: Response): Promise<ApiError> {
  let detail: unknown = undefined;
  let code: string | null = null;
  try {
    const text = await res.text();
    if (text) {
      try {
        const json = JSON.parse(text) as { detail?: unknown; code?: unknown };
        detail = json?.detail ?? json;
        if (typeof json?.code === "string") code = json.code;
      } catch {
        detail = text;
      }
    }
  } catch {
    /* body unreadable */
  }
  const fallback = res.statusText || `Request failed (${res.status})`;
  return new ApiError(res.status, messageFromDetail(detail, fallback), detail, code);
}

/** Perform a request and return the raw Response (throws {@link ApiError} on non-2xx). */
export async function requestRaw(path: string, opts: RequestOptions = {}): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(apiPath(path, opts.query), buildInit(opts));
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Ordnung isn't reachable. Is it still running on this computer?", err);
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
  return JSON.parse(text) as T;
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
