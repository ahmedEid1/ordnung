/**
 * A GiroCode as a picture, for a paired phone: a phone can't scan its own screen, but many banking apps read a
 * GiroCode from a photo in the gallery. The code is drawn in the browser (dark modules on white, with the quiet
 * zone) and handed to the phone's share sheet ("Save image"), or downloaded where there is none. Nothing leaves the
 * phone but to where the person sends it.
 */
import { qrMatrix } from "./qr";

/** The picture's file name. */
export const GIROCODE_FILE = "GiroCode.png";
/** Pixels per module: a version-13 code (77 modules with its quiet zone) is 770 px wide, sharp for any camera. */
export const PICTURE_MODULE_PX = 10;

/** The code of `payload` as a PNG: white, with each dark module a {@link PICTURE_MODULE_PX}-pixel black square. */
export function giroCodePicture(payload: string, modulePx = PICTURE_MODULE_PX): Promise<Blob> {
  const { size, modules } = qrMatrix(payload);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size * modulePx;
  const ctx = canvas.getContext("2d");
  if (!ctx) return Promise.reject(new Error("This browser can't draw the picture."));
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#000000";
  modules.forEach((row, y) => {
    row.forEach((dark, x) => {
      if (dark) ctx.fillRect(x * modulePx, y * modulePx, modulePx, modulePx);
    });
  });
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("This browser can't draw the picture."))), "image/png");
  });
}

/** How saving went: the share sheet took it, it was downloaded, or the person closed the share sheet. */
export type SaveOutcome = "shared" | "downloaded" | "cancelled";

/**
 * Hand the picture to the phone: its share sheet when it can share files (`navigator.canShare`), so it goes to
 * Photos or straight to the banking app; otherwise a download. Call it from the tap itself: a share sheet opens
 * only in answer to one.
 */
export async function savePicture(blob: Blob, filename = GIROCODE_FILE): Promise<SaveOutcome> {
  const file = new File([blob], filename, { type: blob.type || "image/png" });
  const nav = typeof navigator === "undefined" ? undefined : navigator;
  if (nav?.share && nav.canShare?.({ files: [file] })) {
    try {
      await nav.share({ files: [file], title: "GiroCode" });
      return "shared";
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return "cancelled";
      // a share sheet that refused (no tap left to answer, a type it won't take): the download still works
    }
  }
  download(blob, filename);
  return "downloaded";
}

/** Save `blob` as a file (a blob: URL — the page's CSP allows it — revoked once the click has used it). */
function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
