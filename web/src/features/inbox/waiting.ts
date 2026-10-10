/**
 * The Inbox's "From your folder — not read yet" group (pure, unit-tested): which letters wait,
 * in what order, and how they are described. A letter waits (`held`) when the watched folder brought
 * it in and the person hasn't said yet whether Claude may read it (docs/privacy.md).
 */
import type { Document } from "@/api/types";
import { isHeld } from "./filters";

export interface WaitingRow {
  doc: Document;
  /** The e-mail this letter came attached to, when that e-mail is known here. */
  email: Document | null;
  /** Listed right under that e-mail (it waits too). */
  nested: boolean;
}

const EMAIL_SOURCE = "email:";

/** The id of the e-mail a letter came attached to (`source: "email:<id>"`), else null. */
export function emailIdOf(doc: Pick<Document, "source">): string | null {
  return doc.source.startsWith(EMAIL_SOURCE) ? doc.source.slice(EMAIL_SOURCE.length) : null;
}

const newestFirst = (a: Document, b: Document) => (a.created_at === b.created_at ? (a.id < b.id ? -1 : 1) : a.created_at < b.created_at ? 1 : -1);
const oldestFirst = (a: Document, b: Document) => -newestFirst(a, b);

/**
 * The waiting letters: the newest first, an e-mail's waiting attachments right under it (in the
 * order they came). An attachment whose e-mail doesn't wait (any more) stands on its own, still
 * naming its e-mail. `only`: just these letters (the ones a search found); an attachment found
 * without its e-mail stands on its own too. A found e-mail keeps its waiting attachments under it:
 * an answer for the e-mail is for them as well (the server answers for them together).
 */
export function waitingRows(docs: readonly Document[], only?: Pick<ReadonlySet<string>, "has">): WaitingRow[] {
  const byId = new Map(docs.map((d) => [d.id, d]));
  const waiting = docs.filter(isHeld);
  const waitingIds = new Set(waiting.map((d) => d.id));
  const found = (d: Document) => {
    const parent = emailIdOf(d);
    return !only || only.has(d.id) || (parent !== null && waitingIds.has(parent) && only.has(parent));
  };
  const held = waiting.filter(found);
  const heldIds = new Set(held.map((d) => d.id));
  const under = new Map<string, Document[]>();
  const roots: Document[] = [];
  for (const d of held) {
    const parent = emailIdOf(d);
    if (parent && heldIds.has(parent)) under.set(parent, [...(under.get(parent) ?? []), d]);
    else roots.push(d);
  }
  return roots.sort(newestFirst).flatMap((root) => [
    {
      doc: root,
      email: byId.get(emailIdOf(root) ?? "") ?? null,
      nested: false,
    },
    ...(under.get(root.id) ?? []).sort(oldestFirst).map((doc) => ({ doc, email: root, nested: true })),
  ]);
}

/** "Read it" · "Read these 3" — the main button of the group (the letters on screen, no more). */
export function readLabel(count: number): string {
  return count === 1 ? "Read it" : `Read these ${count}`;
}

/** What kind of file it is, in words: "PDF", "Photo", "E-mail", "Text". */
export function fileKindLabel(mime: string): string {
  if (mime === "application/pdf") return "PDF";
  if (mime.startsWith("image/")) return "Photo";
  if (mime === "message/rfc822") return "E-mail";
  return "Text";
}

/** Where a waiting letter came from, as a sentence (the document page and the group say the same). */
export function heldOrigin(doc: Pick<Document, "source">, email: Pick<Document, "title" | "filename"> | null): string {
  if (emailIdOf(doc))
    return email ? `It came attached to the e-mail “${email.title ?? email.filename}” from your watched folder.` : "It came attached to an e-mail from your watched folder.";
  return doc.source === "folder" ? "It came from your watched folder." : "It came in without a click from you.";
}
