# ADR 0022 — Compressed answers and a lighter letter list

**Status:** accepted · **Date:** 2026-10-11

## Context
Every page that shows letters loads the whole letter list (`GET /api/documents`), and each row was the whole
`Document`: the explanation Claude wrote, every key fact, the references, the bank details and the file hash.
No list view shows any of it; the letter's own page loads it again. Nothing was compressed either, neither the
JSON answers nor the web app's files. On a big library that is a lot of data for every page, and on the phone
it all travels over Wi-Fi and TLS.

## Decision
- **Our own compression, JSON only.** `api/compress.py` (`CompressMiddleware`, plain ASGI, the standard
  library's gzip) is the outermost of Ordnung's middlewares, on the computer's listener and the phone's. It
  compresses an answer only when the request is a `GET` that takes gzip and the answer is a `200` JSON body of
  at least 1 KiB, sent as one message, with no `Set-Cookie`, `Content-Disposition`, `ETag`, `Accept-Ranges`,
  `Content-Range` or `Content-Encoding` and no `Cache-Control: no-transform`, and gzip makes it smaller. It
  runs at level 6, in a thread from 128 KiB. Anything else passes at once, as it came: live updates
  (`/api/events`) never wait for it, a range request keeps its 206, and downloads, pages and writes are never
  touched. A JSON answer it could compress says `Vary: Accept-Encoding`. Request bodies are never decompressed.
- **The web app's files gzipped once, in memory.** The web app's `.js`, `.css`, `.svg`, `.txt` and `.json`
  files are answered gzipped (level 9) from a cache kept per file and version, with fixed media types (never
  the system's registry). `index.html`, `HEAD` and range requests are answered as they are.
- **TLS's own compression is off** on the phone's listener (`OP_NO_COMPRESSION`), whatever the OpenSSL build
  would choose.
- **The list leaves out the reading.** `GET /api/documents` answers `DocumentRow`: every `Document` field but
  `LEFT_OUT_OF_LIST` (`key_facts`, `explanation`, `references`, `payment`, `sha256`), plus `found_in`. The model
  lives in `api/routes/documents.py` and copies its fields from `Document` by name, so a field the letter gains
  reaches the list by itself. The letter's own page (`GET /api/documents/{id}`) has everything, as before.
- **The copy of your records keeps every letter whole.** *Download a copy of your records* takes its letters
  from a new `GET /api/documents.json`: every letter as stored, newest first, without trash and proof files.
  It is computer-only, like the other records that leave the computer.
- **`models.py` is untouched on purpose.** It is part of the benchmark's code digest, and `Document` is what
  Ask's ledger fingerprint hashes: changing either would stop the recordings from replaying. So
  `models.DocumentListEntry` stays, unused, until `models.py` next changes for a reason that pays for new
  recordings.

## Why compression is safe here (BREACH)
An attack that reads a secret out of compressed HTTPS (BREACH) needs all of these: someone who can watch the
encrypted traffic, a secret in an answer's body, text the attacker chose in the same body, and many requests
the attacker can make the victim's browser send with its sign-in.

- The computer's listener is plain HTTP on `127.0.0.1`: whoever can watch it reads it anyway.
- On the phone's listener the gate refuses what another site sends (Fetch-Metadata and `Origin`) before
  routing, and the phone's sign-in cookie is `SameSite=Strict`, so a website the phone visits can't make it
  send Ordnung signed-in requests.
- No compressed answer carries a credential today. The session token and a phone's sign-in travel only in
  cookies, and an answer that sets one is never compressed. A pairing code is only in the answer to a `POST`.
  The passwords of calendar sync and hand-off sync are never sent back. Ordnung's guard against cross-site
  changes is a header without a secret value, so no token sits in a body either.

**The rule for later:** a new `GET` route whose JSON answer carries a secret (a code, a token, a password or a
key) gets a test that proves its answer is never compressed, or it isn't a `GET`.

## Measured
On a copy of the demo (22 letters), by the rules above: the letter list went from about 91 KB of JSON to about
25 KB as `DocumentRow`s, and to about 5.7 KB gzipped, 94 % less on the wire; the five fields left out were
nearly three quarters of its bytes. The JSON answers to the app's `GET`s without parameters went from about
840 KB to about 140 KB, about 6 times less, and the web app's text files from about 2.9 MB to about 0.89 MB,
about 3 times less. These are bytes; how much faster a page feels on a real phone over home Wi-Fi wasn't
measured.

## Rejected
- **Starlette's `GZipMiddleware`:** at the oldest Starlette Ordnung supports, it compresses 206 answers, PDFs
  and pictures with no way to leave them out, holds every answer's headers until its first body message (a
  live stream would wait for its first ping), and its rules changed between versions.
- **Pre-compressed files in the committed build, or brotli:** close to 1 MB more in git and in the wheel at
  every rebuild, or a new dependency to compress at run time, to save work done once per process.
- **A cursor and paged loading for the list:** the Inbox works out its counts and groups over every letter in
  the browser, so pages would carry the same bytes in all, and paging adds a restart when the list changes
  while it loads. The slim rows and gzip carry nearly all of the saving. Revisit when the filters move to the
  server.
- **Leaving out more fields:** the five are most of the list's bytes and no list view reads them; the small
  ones stay for scripts.
- **One detail call per letter for the records copy:** with 500 letters it would take seconds, and far more
  work per letter.

## Consequences and known limits
- A script that read those five fields from the list reads them from the letter, or every letter whole from
  `documents.json` on the computer.
- Bank details, payees and key facts no longer sit in every browser's and phone's cache of the list; they load
  per letter.
- Antivirus or proxies that rewrite traffic on `localhost` are rare; `Vary` is set for them.
- No test can prove that a later route won't put a secret into a compressed `GET` answer: the rule above, and a
  test for each such route, do.
