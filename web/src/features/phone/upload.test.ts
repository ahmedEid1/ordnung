/**
 * A phone's upload with progress (`XMLHttpRequest`): the same request as `api.uploadDocuments`, the same answers
 * and errors as `fetch` gives the app, an abort that is an abort — and with the mock API installed (`?mock=1`),
 * the mock's own upload.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, PHONE_UNREACHABLE, UNREADABLE_CODE } from "@/api/client";
import { isAbort, uploadForm, uploadWithProgress } from "./upload";

class FakeXhr {
  static last: FakeXhr;
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  statusText = "";
  responseText = "";
  withCredentials = false;
  type = "";
  opened: [string, string] | null = null;
  headers: Record<string, string> = {};
  body: FormData | null = null;
  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.opened = [method, url];
  }
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v;
  }
  getResponseHeader(k: string) {
    return k.toLowerCase() === "content-type" ? this.type || null : null;
  }
  send(body: FormData) {
    this.body = body;
  }
  abort() {
    this.onabort?.();
  }
  answer(status: number, text: string, type = "application/json", statusText = "") {
    this.status = status;
    this.statusText = statusText;
    this.responseText = text;
    this.type = type;
    this.onload?.();
  }
}

const RESULT = { documents: [], jobs: [], duplicates: [], errors: [] };
const files = [new File(["a"], "photo-p1.jpg", { type: "image/jpeg" }), new File(["bb"], "photo-p2.jpg", { type: "image/jpeg" })];

beforeEach(() => vi.stubGlobal("XMLHttpRequest", FakeXhr));
afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window, "__ordnungMock");
});

describe("uploadWithProgress", () => {
  it("sends the form api.uploadDocuments sends, signed in, with the client header", async () => {
    const progress = vi.fn();
    const done = uploadWithProgress(files, { combine: true, private: false }, progress);
    const xhr = FakeXhr.last;
    expect(xhr.opened).toEqual(["POST", "/api/documents"]);
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.headers).toEqual({ Accept: "application/json", "X-Ordnung-Client": "web" });
    expect([...xhr.body!.entries()].map(([k, v]) => [k, typeof v === "string" ? v : v.name])).toEqual([
      ["files", "photo-p1.jpg"],
      ["files", "photo-p2.jpg"],
      ["combine", "true"],
      ["private", "false"],
    ]);
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 30, total: 120 });
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 60, total: 0 });
    expect(progress.mock.calls).toEqual([[0.25]]);
    xhr.answer(201, JSON.stringify(RESULT));
    await expect(done).resolves.toEqual(RESULT);
    expect(progress).toHaveBeenLastCalledWith(1);
    expect(uploadForm(files, {}).get("combine")).toBe("false");
  });

  it("a refusal is an ApiError in the API's words, with its code", async () => {
    const done = uploadWithProgress(files, {}, () => {});
    FakeXhr.last.answer(413, JSON.stringify({ detail: "Too large.", code: "too_large" }), "application/json", "Payload Too Large");
    await expect(done).rejects.toMatchObject({ status: 413, message: "Too large.", code: "too_large" });
  });

  it("an answer that isn't Ordnung's is said plainly", async () => {
    const done = uploadWithProgress(files, {}, () => {});
    FakeXhr.last.answer(201, "<html>proxy</html>", "text/html");
    const err = await done.catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 201, code: UNREADABLE_CODE, technical: "<html>proxy</html>" });
  });

  it("no answer: the computer isn't reachable (the phone's words)", async () => {
    const done = uploadWithProgress(files, {}, () => {});
    FakeXhr.last.onerror?.();
    await expect(done).rejects.toMatchObject({ status: 0, message: PHONE_UNREACHABLE });
  });

  it("stopped on purpose: an AbortError, not a failure — also when stopped before it started", async () => {
    const controller = new AbortController();
    const done = uploadWithProgress(files, {}, () => {}, controller.signal);
    controller.abort();
    const err = await done.catch((e: unknown) => e);
    expect(isAbort(err)).toBe(true);
    expect(isAbort(new ApiError(0, "x"))).toBe(false);
    await expect(uploadWithProgress(files, {}, () => {}, controller.signal).catch((e: unknown) => isAbort(e))).resolves.toBe(true);
  });

  it("with the mock API installed it is the mock's upload (which answers fetch only)", async () => {
    Object.assign(window, { __ordnungMock: {} });
    const fetchSpy = vi.fn(async () => new Response(JSON.stringify(RESULT), { status: 201, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchSpy);
    const progress = vi.fn();
    await expect(uploadWithProgress(files, { combine: true }, progress)).resolves.toEqual(RESULT);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(progress).toHaveBeenCalledWith(1);
  });
});
