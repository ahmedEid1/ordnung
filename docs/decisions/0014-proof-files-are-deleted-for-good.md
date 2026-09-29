# ADR 0014 — Proof files are deleted for good, after a confirmation that names them

**Status:** accepted · **Date:** 2026-09-27

## Context
ADR 0006 says "deleting goes to trash first". In the web app, though, deleting a letter has always
deleted it for good after a confirmation (`DELETE /api/documents/{id}?purge=true`), because the
privacy promise is "delete means delete" (docs/privacy.md): the original, its page images, what was
read from it and the cached model answers go at once. There is no Trash page to restore from.

Proof files (SPEC § 11) are private documents that belong to a sent letter: a photo of the posting
receipt, a delivery record, a fax report. The final review asked whether removing one — or deleting
its letter without "Keep the proof files" — should go to a trash with Undo instead, since the paper
receipt is often thrown away once photographed and a slip loses the evidence.

## Decision
Proof files follow "delete means delete", like letters:

- Removing a proof deletes its file for good when it was added as proof and no other proof uses it;
  a letter that was already in Ordnung and only linked as proof stays (only the link goes).
- The confirmation names the proof and the file ("Remove the posting receipt?", "“IMG_2231.jpg” is
  deleted from Ordnung for good — this can't be undone") and offers **download it first**, so the
  only copy can be kept outside Ordnung before it goes.
- Deleting a sent letter names its proof files and offers **Keep the proof files** (they become
  private documents of their own).
- Small, reversible changes keep their Undo (the tracking number, "I got an answer", "It arrived").

A trash for proof files alone was rejected: nothing else in the app has a restorable trash to find
them in, files lingering after "Remove" would break the privacy promise, and an Undo that restores
a deleted file needs the bytes kept anyway.

## Consequences
One more click (download) keeps a copy when it matters; nothing a person removed lingers on disk. If
Ordnung ever gets a Trash page, proof files should move there together with letters.
