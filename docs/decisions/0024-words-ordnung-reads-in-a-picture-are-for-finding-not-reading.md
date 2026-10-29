# ADR 0024 — Words Ordnung reads in a picture are for finding, not reading

**Status:** accepted · **Date:** 2026-10-28 · **Amended:** in 0.4.0 (a switch in Settings, info rows in the
doctor; [below](#amended-in-040))

## Context
[ADR 0020](0020-a-scanner-s-text-is-for-finding-not-reading.md) kept a scanner's text for search, so a scan
nobody has read can be found by its words. It rejected Ordnung's own text recognition for photos as "a new
dependency", so a photo Claude isn't reading — kept private, waiting from the watched folder or for Claude, or
one that couldn't be read — was still found only by its file name. A phone photo is how many letters come in.

Tesseract is a free text-recognition program (Apache-2.0, with Apache-2.0 language data for German and
English), packaged for Linux, Homebrew and Windows. Run as a program the person installs, it adds no Python
dependency, nothing to the wheel and no licence to ship.

## Principle
The same as ADR 0020: words a program read from a picture may help the person find a letter. They are never
the letter's words: not shown, not checked against, not sent to Claude and not evidence for anything.

## Decision
- **Optional, looked for, never installed.** Ordnung uses Tesseract 4.1 or newer with German and/or English
  language data (`ingest/ocr.py`, `find`). It looks in the `PATH` first, skipping empty, `.` and relative
  entries, so a program in the current folder never runs, then in each system's install folders. It installs
  nothing. The worker looks once when it starts; `ordnung doctor` looks on every run.
- **Which pages.** Only those of a letter Claude isn't reading: kept private or held, waiting for Claude (not
  ready, or a usage limit) or failed; a photo or a PDF, not in the trash, not a proof file and never read by
  Claude (once it has, a page without text is one it found illegible). And of those,
  only a page that (1) has no text of its own, (2) has no scanner's text, (3) wasn't looked at yet, and (4) for
  a PDF, whose own text was looked for already. Newest letter first, one page at a time.
- **Read from a picture Ordnung made.** Tesseract never sees the uploaded file. Ordnung draws the page as a
  grayscale PNG, at most 2400 px on its long side and 300 dpi, never enlarged (a photo through intake's bounded
  decoder, a PDF page through PDFium under its lock), and passes it on stdin: `tesseract stdin stdout -l
  deu+eng` with the languages installed (`-l deu+eng` when both are), a fixed argument list and no shell. It
  runs with one thread (`OMP_THREAD_LIMIT=1`), nice 10 (`BELOW_NORMAL_PRIORITY_CLASS` on Windows) and no console
  window, in a private temporary folder removed afterwards, with 120 seconds a page; it is killed at that limit
  or when the worker stops. An error names the exit code, never what Tesseract printed.
- **Kept apart, in a file of its own.** The words go into `derived/<doc>/picture-text.json`, the scanner
  text's format (`db/scan_text.py`, `PICTURE_NAME`): at most 20,000 characters a page, private and written
  atomically; `""` means "looked, no words". Only `Store` reads and writes it. It is never in the `pages`
  table, the search indexes, `Document`, Ask's tools, a prompt, the reading's evidence checks or the ledger
  fingerprint, and no database row is written for it.
- **Search only, marked.** `GET /api/documents?q=` adds the letters whose picture text matches on a page
  without text of its own, by the scanner text's rules. A letter found only that way carries
  `found_in="picture_text"`, and the app says *Found in text Ordnung read from the picture — not checked*. When
  the scanner's text matches too, `scanner_text` wins. The letter's page names the pages
  (`LetterDetail.picture_text_pages`) and says, for a photo: "Ordnung read the words in this photo itself, only
  so search can find the letter: they aren't checked, aren't shown as the letter's words and are never sent to
  Claude." The same words on a phone: the file travels with the page images.
- **It goes with the page.** `forget_scan_text_once_read`, which the text stage calls after Claude's reading,
  removes a page's picture text with its scanner text. Once Claude has read the letter, search and its page
  ignore what is left (a page Claude found illegible keeps no text of its own), and the worker removes it, as it
  tidies a file that Claude's reading on another computer made out of date. Deleting the letter for good deletes
  it with `derived/<doc>/`.
- **When it runs.** The worker's loop waits 30 seconds after the worker starts, as the scanner text's catch-up
  does, and stops with the worker (never while hand-off sync stands this computer by). It is woken when a
  reading ends, because a letter may just have become one Claude isn't reading, and looks again every five
  minutes. A page Tesseract fails on waits for the next start.
- **The off switch.** `ORDNUNG_OCR=off` (also `0`, `false` or `no`, in any case), read on every call: Tesseract
  is never started, the letter routes ignore the file at once, and the worker removes every
  `picture-text.json` when it starts. Start at login and the Linux and macOS launchers record it when it is set;
  on Windows it is set with `setx`.
- **The doctor's row.** *Text in pictures* (`ocr`, right after the web app) never fails: the version and
  languages found; *Not installed (optional)*, ok, with the install line for this system as its fix; a warning
  for one older than 4.1, without German, or that didn't answer; *Turned off (ORDNUNG_OCR=off)*. An ok row
  with a fix is new: `models.DoctorCheck` says a fix is for a row that isn't ok, and the CLI prints this one as
  an *Optional —* tip.
- **Only `ingest/worker.py` and `doctor.py` import the engine.** The wider `found_in` is the route's own
  `LetterFoundIn`, and `LetterDetail.picture_text_pages` is a route-local field.

## Rejected
- **A Settings switch or a Health field:** both need `models.py`, which the benchmark's code digest covers.
  The environment variable and the doctor's row do the job. (Built in 0.4.0: see below.)
- **macOS Vision or Windows.Media.Ocr:** each works on one system only.
- **Bundling Tesseract, or `pytesseract` or `tesserocr`:** a dependency, platform wheels and licences to ship,
  for an optional feature.
- **Reading every letter, or giving Claude the words to save tokens:** the words would become an input to
  the reading, unchecked text where only the picture and the paper count.
- **The `pages` table or the search indexes:** ADR 0020's reasons — evidence, payment details and Ask's
  `get_document` read page text, and the indexes are Ask's search too.
- **Showing the words, or a snippet of them:** it would invite reading them as the letter's words.

## Consequences and known limits
- A photo kept private, waiting or that couldn't be read is found by the words in it, marked as not checked,
  once Tesseract is installed. Without it nothing changes.
- Quality depends on the photo: Tesseract often misreads handwriting, creased paper, skewed pages and small
  print, so a letter may not be found by every word on it. A missed word costs a search, never a wrong date.
- A first large backlog takes a while: a few seconds a page on one thread at low priority, and it stops with
  Ordnung.
- A page looked at stays as read until Claude reads it; adding German later doesn't read it again.
- Search needs every word in one text: the letter's own, the scanner's or the picture's.
- Two computers with the variable set differently, joined by hand-off sync, remove and read again each other's
  words. The docs say to set it the same way on both.
- A computer still on 0.2.0 ignores the file, finds such a photo by its name, and deletes the file with the
  letter.
- The benchmark's inputs and Ask's are unchanged: no digest file changes, no database row is written, and the
  demo has no letter that qualifies, so it writes no such file.

## Amended in 0.4.0
- **A switch in Settings.** Settings → Data → *Text in pictures* (`AppSettings.read_picture_text`, on by default)
  turns it off and on while Ordnung runs. It is off when the switch is off or `ORDNUNG_OCR=off`
  (`config.picture_text_off`): the letter routes ask on every call, and a save that names the switch tells the
  worker (`IngestWorker.picture_text_changed`, one change at a time). Off stops a reading under way, ends the
  loop and deletes every `picture-text.json`; on starts the loop at once and looks for Tesseract afresh.
  `ORDNUNG_OCR=off` still wins, whatever the switch says, and `ocr.recognise` still refuses on the variable
  alone. The card's line is this computer's state in the doctor's words (`Health.picture_text`; none for a
  phone).
- **It travels with hand-off sync**, as a setting (`sync.SYNCED_SETTINGS`). A settings row written by 0.3.0,
  which drops the fields it doesn't know, comes in without it: `KEPT_WHEN_ABSENT` keeps this computer's choice
  then, so a choice to stop reading private photos isn't lost in a round trip. The variable stays per computer.
- **Info rows.** `models.CheckStatus` gained `info`: neither ok nor a problem, and it never fails the doctor.
  *Not installed (optional)*, *Turned off (ORDNUNG_OCR=off)* and *Off (Settings → Data → Text in pictures)* are
  info rows, and the CLI prints an info row's fix as an *Optional —* tip; no ok row has a fix any more.
- **Why `models.py` could change after all.** Its code digest keys only the local prediction cache and the
  fingerprint of a new results file. Comparing every benchmark request before and after the change found the
  same content, so nothing had to be recorded again (#36).
