/**
 * The GiroCode's QR matrix: level M within version 13 (EPC069-12), a four-module quiet zone, a path
 * that draws exactly the dark modules — and a round trip: an independent decoder (`qr`, MIT) reads
 * the rendered matrix back to the payload, byte for byte, umlauts included.
 */
import { describe, expect, it } from "vitest";
import decodeQR from "qr/decode.js";
import { GIROCODES, GIROCODES_CHECKED } from "@/mocks/data/girocodes";
import { MAX_VERSION, QUIET_ZONE, qrMatrix, qrPath, readPayload, type QrMatrix } from "./qr";

const NEBENKOSTEN = "BCD\n002\n1\nSCT\n\nWohnbau Musterstadt eG\nDE05123456000004455660\nEUR184.3\n\n\nMV-2025-0412 NK 2025";
// EPC069-12 v3.1, section 2.3, "V1" (UTF-8, 96 bytes)
const EPC_V1 = "BCD\n001\n1\nSCT\nBHBLDEHHXXX\nFranz Mustermänn\nDE71110220330123456789\nEUR12.3\nGDDS\nRF18539007547034";
// the standard's limit: 70-character name, 140-character reference (331 bytes at most)
const LONGEST = `BCD\n002\n1\nSCT\n\n${"Ä".repeat(35)}${"x".repeat(35)}\nDE05123456000004455660\nEUR999999999.99\n\n\n${"R".repeat(140)}`;

/** The matrix as an RGBA picture, `scale` pixels per module (dark = black). */
function picture(qr: QrMatrix, scale = 4) {
  const width = qr.size * scale;
  const data = new Uint8ClampedArray(width * width * 4);
  for (let y = 0; y < width; y++) {
    for (let x = 0; x < width; x++) {
      const dark = qr.modules[Math.floor(y / scale)]![Math.floor(x / scale)];
      const at = (y * width + x) * 4;
      data.fill(dark ? 0 : 255, at, at + 3);
      data[at + 3] = 255;
    }
  }
  return { width, height: width, data };
}

describe("the QR matrix", () => {
  it.each([
    ["the utility statement", NEBENKOSTEN],
    ["the standard's first example (UTF-8 umlaut)", EPC_V1],
    ["the longest payload the standard allows", LONGEST],
  ])("reads back to the payload: %s", (_name, payload) => {
    expect(new TextEncoder().encode(LONGEST).length).toBeLessThanOrEqual(331);
    const qr = qrMatrix(payload);
    expect(decodeQR(picture(qr))).toBe(payload);
  });

  it("stays within version 13 at level M and keeps a four-module quiet zone", () => {
    const small = qrMatrix(NEBENKOSTEN);
    expect(small.version).toBeLessThanOrEqual(7);
    expect(qrMatrix(LONGEST).version).toBeLessThanOrEqual(MAX_VERSION);
    for (const qr of [small, qrMatrix(LONGEST)]) {
      expect(qr.size).toBe(4 * qr.version + 17 + 2 * QUIET_ZONE);
      const inZone = (i: number) => i < QUIET_ZONE || i >= qr.size - QUIET_ZONE;
      qr.modules.forEach((row, y) => row.forEach((dark, x) => (inZone(x) || inZone(y) ? expect(dark).toBe(false) : null)));
      // the finder pattern's corner starts right inside the quiet zone
      expect(qr.modules[QUIET_ZONE]![QUIET_ZONE]).toBe(true);
    }
  });

  it("refuses what doesn't fit version 13 rather than drawing a bigger code", () => {
    expect(() => qrMatrix("x".repeat(400))).toThrow();
  });

  it("draws exactly the dark modules", () => {
    const qr = qrMatrix(NEBENKOSTEN);
    const dark = qr.modules.flat().filter(Boolean).length;
    const runs = [...qrPath(qr.modules).matchAll(/M(\d+) (\d+)h(\d+)v1h-\3z/g)];
    expect(runs.reduce((sum, m) => sum + Number(m[3]), 0)).toBe(dark);
    for (const [, x, y, length] of runs) {
      for (let i = 0; i < Number(length); i++) expect(qr.modules[Number(y)]![Number(x) + i]).toBe(true);
    }
  });

  it("every code the static demo shows is readable and says what its payload says", () => {
    const ready = [...Object.values(GIROCODES), ...Object.values(GIROCODES_CHECKED)].filter((g) => g.status === "ready");
    expect(ready.length).toBeGreaterThanOrEqual(5);
    for (const code of ready) expect(decodeQR(picture(qrMatrix(code.payload), 3))).toBe(code.payload);
  });
});

describe("reading a payload", () => {
  it("names the payee, account, amount and reference", () => {
    expect(readPayload(NEBENKOSTEN)).toEqual({ name: "Wohnbau Musterstadt eG", iban: "DE05123456000004455660", amount: 184.3, reference: "MV-2025-0412 NK 2025" });
    expect(readPayload(EPC_V1)).toEqual({ name: "Franz Mustermänn", iban: "DE71110220330123456789", amount: 12.3, reference: "RF18539007547034" });
    expect(readPayload("BCD\n002\n1\nSCT\n\nA\nDE05123456000004455660")).toEqual({ name: "A", iban: "DE05123456000004455660", amount: null, reference: "" });
  });
});
