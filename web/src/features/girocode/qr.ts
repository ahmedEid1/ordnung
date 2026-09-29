/**
 * A GiroCode's QR code, drawn in the browser — the payload never leaves the app for an online QR
 * service. Encoded with `uqr` (MIT, no dependencies) at error correction level M and at most
 * version 13, as EPC069-12 asks, with the four-module light margin (quiet zone) scanners need.
 */
import { encode } from "uqr";

/** Light modules around the code (ISO/IEC 18004 asks for four). */
export const QUIET_ZONE = 4;
/** EPC069-12: "Maximum QR code version 13" (331 bytes at level M). */
export const MAX_VERSION = 13;

export interface QrMatrix {
  /** Modules per side, quiet zone included. */
  size: number;
  version: number;
  /** Rows of modules, quiet zone included; `true` is dark. */
  modules: boolean[][];
}

/** The QR code of `payload` (UTF-8 bytes, level M). Throws when it doesn't fit version 13. */
export function qrMatrix(payload: string): QrMatrix {
  const qr = encode(payload, { ecc: "M", border: QUIET_ZONE, maxVersion: MAX_VERSION });
  return { size: qr.size, version: qr.version, modules: qr.data };
}

/** An SVG path of the dark modules, one rectangle per horizontal run (a module is 1×1). */
export function qrPath(modules: boolean[][]): string {
  const parts: string[] = [];
  modules.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      if (!row[x]) {
        x += 1;
        continue;
      }
      const start = x;
      while (x < row.length && row[x]) x += 1;
      parts.push(`M${start} ${y}h${x - start}v1h-${x - start}z`);
    }
  });
  return parts.join("");
}

/** The transfer a GiroCode payload carries (EPC069-12 element order), for labels and tests. */
export interface GiroTransfer {
  name: string;
  iban: string;
  /** In euro, `null` when the code leaves it to the payer. */
  amount: number | null;
  /** The structured (RF) or unstructured reference, whichever is filled. */
  reference: string;
}

export function readPayload(payload: string): GiroTransfer {
  const lines = payload.split(/\r?\n/);
  const at = (i: number) => lines[i] ?? "";
  const amount = at(7).startsWith("EUR") ? Number(at(7).slice(3)) : null;
  return { name: at(5), iban: at(6), amount: amount != null && Number.isFinite(amount) ? amount : null, reference: at(9) || at(10) };
}
