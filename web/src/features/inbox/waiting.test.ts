/**
 * The Inbox's "From your folder — not read yet" (pure logic): which letters wait and in what order
 * (an e-mail's attachments right under it), that they are in no other group or filter, and the words.
 */
import { describe, expect, it } from "vitest";
import { makeDoc } from "@/features/document/fixtures";
import { filterCounts, filterDocuments, heldMatches, isHeld } from "./filters";
import { emailIdOf, fileKindLabel, heldOrigin, readLabel, waitingRows } from "./waiting";

const held = (id: string, created: string, extra: Parameters<typeof makeDoc>[0] = {}) =>
  makeDoc({ id, filename: `${id}.pdf`, title: `${id}.pdf`, status: "held", ai_private: true, source: "folder", created_at: created, ...extra });

describe("the letters waiting from the folder", () => {
  const mail = held("mail", "2026-09-27T16:02:00Z", { mime: "message/rfc822", filename: "Rechnung.eml" });
  const bill = held("bill", "2026-09-27T16:02:01Z", { source: "email:mail" });
  const terms = held("terms", "2026-09-27T16:02:02Z", { source: "email:mail" });
  const scan = held("scan", "2026-09-28T07:14:00Z");
  const read = makeDoc({ id: "read", status: "processed" });

  it("are listed newest first, an e-mail's attachments right under it in the order they came", () => {
    const rows = waitingRows([terms, read, bill, scan, mail]);
    expect(rows.map((r) => [r.doc.id, r.email?.id ?? null, r.nested])).toEqual([
      ["scan", null, false],
      ["mail", null, false],
      ["bill", "mail", true],
      ["terms", "mail", true],
    ]);
  });

  it("an attachment whose e-mail was answered stands on its own, still naming the e-mail", () => {
    const answered = { ...mail, status: "processed" as const };
    const rows = waitingRows([answered, bill]);
    expect(rows.map((r) => [r.doc.id, r.email?.id, r.nested])).toEqual([["bill", "mail", false]]);
    expect(waitingRows([bill])[0]!.email).toBeNull(); // the e-mail isn't known here
  });

  it("while the Inbox is searched, only the ones it found are listed; an attachment found without its e-mail stands on its own", () => {
    const rows = waitingRows([terms, read, bill, scan, mail], new Set(["bill", "scan", "read"]));
    expect(rows.map((r) => [r.doc.id, r.email?.id ?? null, r.nested])).toEqual([
      ["scan", null, false],
      ["bill", "mail", false],
    ]);
    expect(waitingRows([terms, bill, scan, mail], new Set())).toEqual([]);
  });

  it("a search's waiting letters: those the live list still holds as waiting, with where the search found each", () => {
    const answered = { ...mail, status: "processed" as const };
    const found = heldMatches(
      [scan, bill, read, answered],
      [
        { ...read, found_in: "letter" },
        { ...mail, found_in: "letter" }, // answered since the search ran
        { ...scan, found_in: "scanner_text" },
        { ...bill, found_in: "letter" },
      ],
    );
    expect([...found]).toEqual([
      ["scan", "scanner_text"],
      ["bill", "letter"],
    ]);
  });

  it("are in no group, filter or count of the letters list", () => {
    const docs = [scan, read, makeDoc({ id: "private", status: "processed", ai_private: true })];
    expect(docs.filter(isHeld).map((d) => d.id)).toEqual(["scan"]);
    expect(filterDocuments(docs, { filter: "all" }).map((d) => d.id)).toEqual(["read", "private"]);
    expect(filterDocuments(docs, { filter: "private" }).map((d) => d.id)).toEqual(["private"]);
    expect(filterCounts(docs)).toEqual({ all: 2, check: 0, private: 1 });
    expect(isHeld({ ...scan, deleted_at: "2026-09-28T08:00:00Z" })).toBe(false);
  });

  it("say what they are and where they came from", () => {
    expect(readLabel(1)).toBe("Read it");
    expect(readLabel(3)).toBe("Read these 3");
    expect(["application/pdf", "image/jpeg", "message/rfc822", "text/plain"].map(fileKindLabel)).toEqual(["PDF", "Photo", "E-mail", "Text"]);
    expect(emailIdOf(bill)).toBe("mail");
    expect(emailIdOf(scan)).toBeNull();
    expect(heldOrigin(scan, null)).toBe("It came from your watched folder.");
    expect(heldOrigin(bill, mail)).toBe("It came attached to the e-mail “mail.pdf” from your watched folder.");
    expect(heldOrigin(bill, null)).toBe("It came attached to an e-mail from your watched folder.");
  });
});
