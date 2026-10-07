/**
 * A phone's upload with progress: photos go over the home Wi‑Fi to the computer, which takes a few seconds, so the
 * phone says how far it got ("Sending 3 pages… 45%") and can stop it. `fetch` reports no upload progress, so this is
 * `XMLHttpRequest` with the same request `api.uploadDocuments` makes: the same multipart form (`files` repeated,
 * `combine`, `private`), `X-Ordnung-Client: web`, the same cookies, the same answers and errors ({@link toApiError}).
 *
 * With the mock API installed (`?mock=1`, which answers `fetch` only) it is `api.uploadDocuments`, without progress.
 */
import { ApiError, apiPath, PHONE_UNREACHABLE, toApiError, UNREADABLE_ANSWER, UNREADABLE_CODE } from "@/api/client";
import { api, type UploadOptions } from "@/api/endpoints";
import type { UploadResult } from "@/api/types";

/** How far an upload got, 0 to 1 (the request's body; the server's answer comes after 1). */
export type OnProgress = (fraction: number) => void;

/** The mock API answers `fetch`, never `XMLHttpRequest` (`mocks/install.ts`). */
function mocked(): boolean {
  return typeof window !== "undefined" && "__ordnungMock" in window;
}

/** The form `api.uploadDocuments` sends. */
export function uploadForm(files: readonly File[], opts: UploadOptions): FormData {
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  form.append("combine", String(Boolean(opts.combine)));
  form.append("private", String(Boolean(opts.private)));
  return form;
}

/** The abort an upload ends with when `signal` stops it (as `fetch` rejects). */
function aborted(): DOMException {
  return new DOMException("The upload was stopped.", "AbortError");
}

/**
 * `POST /api/documents` with progress: resolves with the answer (201), rejects with an {@link ApiError} (a refusal,
 * the computer not answering) or an `AbortError` when `signal` stops it.
 */
export function uploadWithProgress(files: readonly File[], opts: UploadOptions, onProgress: OnProgress, signal?: AbortSignal): Promise<UploadResult> {
  if (mocked()) {
    return api.uploadDocuments([...files], opts).then((result) => {
      onProgress(1);
      return result;
    });
  }
  return new Promise<UploadResult>((resolve, reject) => {
    if (signal?.aborted) {
      reject(aborted());
      return;
    }
    const xhr = new XMLHttpRequest();
    const stop = () => xhr.abort();
    const done = () => signal?.removeEventListener("abort", stop);
    xhr.open("POST", apiPath("/documents"));
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    xhr.setRequestHeader("X-Ordnung-Client", "web");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress(Math.min(1, e.loaded / e.total));
    };
    xhr.onload = () => {
      done();
      const text = typeof xhr.responseText === "string" ? xhr.responseText : "";
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(1);
        try {
          resolve(JSON.parse(text) as UploadResult);
        } catch {
          // a body that isn't Ordnung's JSON, said as `request` says it
          reject(new ApiError(xhr.status, UNREADABLE_ANSWER, text, UNREADABLE_CODE, text.replace(/\s+/g, " ").trim().slice(0, 300)));
        }
        return;
      }
      if (xhr.status < 200 || xhr.status > 599) {
        reject(new ApiError(0, PHONE_UNREACHABLE));
        return;
      }
      const headers = new Headers();
      const type = xhr.getResponseHeader("Content-Type");
      if (type) headers.set("Content-Type", type);
      void toApiError(new Response(text || null, { status: xhr.status, statusText: xhr.statusText, headers })).then(reject);
    };
    xhr.onerror = () => {
      done();
      reject(new ApiError(0, PHONE_UNREACHABLE));
    };
    xhr.onabort = () => {
      done();
      reject(aborted());
    };
    signal?.addEventListener("abort", stop, { once: true });
    xhr.send(uploadForm(files, opts));
  });
}

/** True for the end of an upload that was stopped on purpose ("Cancel"), not a failure. */
export function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}
