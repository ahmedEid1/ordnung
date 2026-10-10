/**
 * Export letters on the real app (`ordnung serve` with the fake Claude): Settings → Data → Export letters downloads a
 * real ZIP — the letter's original file, byte for byte, in its year and sender folders, and `index.csv` for a
 * spreadsheet — only when the person clicks Download, and nothing in Ordnung changes. The letter it adds is deleted
 * for good afterwards (the other real-app specs add the same file).
 */
import { readFileSync } from "node:fs";
import { inflateRawSync } from "node:zlib";
import type { Page } from "@playwright/test";
import { REAL_LETTER } from "./env";
import { apiGet, apiSend, expect, open, test, type Letter } from "./helpers";

const FILE = "19_bank_preisaenderung.pdf";
const INDEX_HEADER = "file;letter_date;arrived;sender;title;kind;for_taxes;tax_note;direction;private;pages;original_name;ordnung_id;note";

/** The letter once the API lists it as read (it is read in the background). */
async function readLetter(page: Page): Promise<Letter> {
  let found: (Letter & { status: string }) | undefined;
  await expect
    .poll(
      async () => {
        found = (await apiGet<(Letter & { status: string })[]>(page, "/api/documents")).find((d) => d.filename === FILE);
        return found?.status;
      },
      { message: `${FILE} is read`, timeout: 30_000 },
    )
    .toBe("processed");
  return found!;
}

/** What Ordnung holds, as its API shows it: the letters, the privacy log (where any write would show), dates and senders. */
async function everything(page: Page): Promise<string> {
  const paths = ["/api/documents", "/api/activity?limit=500", "/api/items?include_undated=true", "/api/contracts", "/api/parties", "/api/drafts"];
  return JSON.stringify(await Promise.all(paths.map((path) => apiGet<unknown>(page, path))));
}

/** The entries of a ZIP (its central directory), each with its bytes: STORED as they are, DEFLATED inflated. */
function unzip(zip: Buffer): Map<string, Buffer> {
  const end = zip.lastIndexOf(Buffer.from("PK\x05\x06", "latin1"));
  expect(end, "the ZIP has its end record").toBeGreaterThan(0);
  const count = zip.readUInt16LE(end + 10);
  let at = zip.readUInt32LE(end + 16);
  const entries = new Map<string, Buffer>();
  for (let i = 0; i < count; i++) {
    expect(zip.readUInt32LE(at), "a central directory entry").toBe(0x02014b50);
    const method = zip.readUInt16LE(at + 10);
    const size = zip.readUInt32LE(at + 20);
    const nameLength = zip.readUInt16LE(at + 28);
    const extraLength = zip.readUInt16LE(at + 30);
    const commentLength = zip.readUInt16LE(at + 32);
    const local = zip.readUInt32LE(at + 42);
    const name = zip.subarray(at + 46, at + 46 + nameLength).toString("utf8");
    const start = local + 30 + zip.readUInt16LE(local + 26) + zip.readUInt16LE(local + 28);
    const data = zip.subarray(start, start + size);
    entries.set(name, method === 8 ? inflateRawSync(data) : Buffer.from(data));
    at += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

test("Export letters downloads a real ZIP of the originals, only on a click, and changes nothing", async ({ page }) => {
  try {
    const upload = await page.request.post("/api/documents", {
      headers: { "X-Ordnung-Client": "web" },
      multipart: { files: { name: FILE, mimeType: "application/pdf", buffer: readFileSync(REAL_LETTER) }, combine: "false" },
    });
    expect(upload.status(), await upload.text()).toBe(201);
    const letter = await readLetter(page);

    await open(page, "/settings?section=data", "Settings");
    const card = page.getByRole("region", { name: "Export your letters" });
    await expect(card.getByText(/The ZIP isn't encrypted/)).toBeVisible();
    await card.getByRole("button", { name: "Export letters…" }).click();
    const dialog = page.getByRole("dialog", { name: "Export letters" });
    await expect(dialog.getByRole("status")).toHaveText(/^\d+ letters? will be in the ZIP\.$/);
    await expect(dialog.getByText(/The ZIP isn't encrypted\. Anyone who has it can read these letters/)).toBeVisible();
    // the dialog asked for nothing yet: only the click downloads
    const before = await everything(page);

    const [download] = await Promise.all([page.waitForEvent("download"), dialog.getByRole("link", { name: "Download ZIP" }).click()]);
    expect(download.suggestedFilename()).toMatch(/^ordnung-letters-\d{4}-\d{2}-\d{2}\.zip$/);
    await expect(dialog).toBeHidden();
    await expect(page.getByText("Your letters are downloading").first()).toBeVisible();

    const zip = readFileSync((await download.path())!);
    expect(zip.subarray(0, 4).toString("latin1"), "a ZIP").toBe("PK\x03\x04");
    const entries = unzip(zip);
    const names = [...entries.keys()];
    expect(names).toContain("index.csv");
    for (const name of names) expect(name === "index.csv" || /^(\d{4}|Undated)\/[^/]+\/[^/]+$/.test(name), `${name}: year/sender/file`).toBe(true);
    // the letter's own file, byte for byte, under its date
    const original = readFileSync(REAL_LETTER);
    const mine = names.filter((name) => name.endsWith(".pdf") && entries.get(name)!.equals(original));
    expect(mine, "the letter's original is in the ZIP").toHaveLength(1);
    expect(mine[0]).toMatch(/^\d{4}\/[^/]+\/\d{4}-\d{2}-\d{2} .+\.pdf$/);
    const index = entries.get("index.csv")!;
    expect(index.subarray(0, 3).toString("hex"), "index.csv starts with a BOM").toBe("efbbbf");
    const lines = index.subarray(3).toString("utf8").split("\r\n");
    expect(lines[0]).toBe(INDEX_HEADER);
    expect(lines.some((line) => line.includes(mine[0]!) && line.includes(FILE) && line.includes(letter.id)), "the letter's row in index.csv").toBe(true);

    // an export only reads: Ordnung holds exactly what it held
    expect(await everything(page), "Ordnung changed").toBe(before);
  } finally {
    for (const added of (await apiGet<Letter[]>(page, "/api/documents")).filter((d) => d.filename === FILE)) {
      await apiSend(page, "DELETE", `/api/documents/${added.id}?purge=true`);
    }
  }
  expect((await apiGet<Letter[]>(page, "/api/documents")).map((d) => d.filename)).not.toContain(FILE);
});
