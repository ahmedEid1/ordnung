# ADR 0020 — A scanner's text is for finding, not reading

**Status:** accepted · **Date:** 2026-10-09

## Context
Many scanners and phone apps save a "searchable PDF": a picture of each page, with the scanner's own reading
of it drawn over the picture as invisible text. Ordnung never took that text for the letter's words. It is
somebody's reading of a picture, so a scan is read from its picture like a photo, and what is read from it
is compared with the paper ([ADR 0003](0003-grounding-levels.md),
[ADR 0012](0012-girocode-only-for-grounded-transfers.md)). The text stage told such an OCR layer apart from
hidden text and threw it away.

That left three kinds of scan findable only by their file name: a scan kept private (*Keep private — no
AI*), one waiting from the watched folder, and one added while Claude isn't installed or signed in. Checking
this also showed that a letter waiting for Claude behind the first one never had even its own PDF text read,
so it too was found only by its name until Claude read it.

## Principle
A scanner's text may help the person find a letter. It is never the letter's words: it is not shown, not
checked against, not sent to Claude and not evidence for anything.

## Decision
- **Kept apart, in a file of its own.** The text stage returns the scanner's text apart from the pages'
  text (`PdfText.scan_text`; `PageText` has no field for it) and keeps it in `derived/<doc>/scan-text.json`
  (`{"version": 1, "pages": {"<n>": "<text>"}}`, at most 20,000 characters a page, private and written
  atomically). An empty map means "looked, nothing there". It is removed once every page has text of its
  own, when Claude has read the scan.
- **One reader.** Only `Store` reads and writes it (`ordnung.db.scan_text`; a test holds that no other
  module imports it). It is never in the `pages` table, the search indexes, `Document`, Ask's tools, a
  prompt, the reading's evidence checks, the hidden-text scam sign or the ledger fingerprint Ask's
  recordings are keyed by.
- **Search only, on pages nobody has read.** `GET /api/documents?q=` adds the letters whose scanner text
  matches on a page without text of its own, by the same word and substring rules as the index. A letter
  found only that way carries `found_in="scanner_text"`, and the app says *Found in your scanner's text —
  not checked*. Ask's `search` never sees it.
- **Never shown.** The API says only *that* a search found a letter in it, and on which pages it is kept
  (`DocumentDetail.scan_text_pages`). The letter's page says: "Your scanner added its own text to this file.
  Ordnung keeps it only so search can find the letter: it isn't checked, isn't shown as the letter's words
  and is never sent to Claude."
- **Where it lives.** With the page images: hand-off sync and backups carry it, and deleting the letter for
  good deletes it, on older versions of Ordnung too. So the docs never say it stays on this computer.
- **Waiting letters and older scans.** A letter put back to wait for Claude first gets its own text read
  by Ordnung's own code (no model, once per run of Ordnung), so search finds it by its words while it waits.
  Scans stored before this version are caught up in the background, 30 seconds after Ordnung starts, one
  letter at a time and never while hand-off sync stands this computer by; no database row changes.
- **No migration, no route.** Two existing responses gain a field each.

## Rejected
- **A field on `Document`**, even one worked out on read: Ask's ledger fingerprint hashes every field, so
  every recording of the demo and the Ask benchmark would stop replaying.
- **The `pages` table** (its text, or a new column): page text feeds the evidence checks, the payment
  details and Ask's `get_document`; a column needs a migration.
- **The search indexes:** they are Ask's search too, so Ask could match and quote scanner text; and an
  older computer's purge would leave a shadow row of a deleted letter behind.
- **Showing the text, or a snippet of it:** it would invite reading it as the letter's words.
- **Ordnung's own OCR for photos:** a new dependency, and the same unchecked text for every photo. A photo
  stays findable by its name.

## Consequences and known limits
- A private, waiting or offline scan is found by its words, and marked as not checked.
- Ask still can't find a private letter (by design), nor a waiting one by its scanner text.
- A PDF that passes its invisible text off as a scan's now has those words kept for search, marked not
  checked, instead of thrown away; they still never reach the model, and the hidden-text sign is unchanged.
- The benchmark's input (the pages' text) is the same as before, and no demo letter has an OCR layer, so
  the demo writes no such file.
- A computer still on 0.2.0 finds such scans by name only, and deletes the file with the letter.
