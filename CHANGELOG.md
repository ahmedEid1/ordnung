# Changelog

What changed in each version of Ordnung, newest first. `ordnung --version` shows the one you have, and
[Updating](README.md#updating) says how to get the newest.

## 0.2.0 — 2026-10-08

The first numbered release. Every install before it reports 0.1.0, the version of the first commit
(2026-09-25), and pip, so also `pipx upgrade`, only replaces an install whose version went up: hence
0.2.0, not 0.1.0.

### Since the first commit

- **Reading letters.** Claude reads a letter, a scan or a photo; tested rules compute every deadline
  (delivery fictions, §§ 187–193 BGB, the holidays of each Land, contract terms, high-stakes letters) with
  citations and *Why this date?*. Code checks quotes and digits, and a check of its own files a to-do when a
  reading left a date out. *How it was read* shows every step.
- **Ask** answers questions about your letters with a citation for each claim, checked against the record.
- **Your secretary:** Today's note, Ideas, the weekly review, Waiting for, My numbers, scam signs, and
  paying by GiroCode behind a safety check.
- **Letters you send:** template letters and bilingual drafts as DIN 5008 PDFs, sending advice, proof of
  sending.
- **One inbox** (a watched folder, e-mail attachments), reminders with a morning notification and
  autostart, calendar export and CalDAV sync, encrypted backups.
- **Your phone at home:** pair it, photograph letters and tick off to-dos over your home Wi-Fi.
- **Hand-off sync** between your computers through a folder you already sync.
- **The rules engine as MCP tools** for Claude Desktop and Claude Code.
- **The demo** (recorded answers, zero tokens) and two benchmarks replayed in CI: reading letters, on a
  test split and three held-out splits, and Ask.

### Fixed

- Updates install: the version now goes up with each release and is stated once, in
  `src/ordnung/__init__.py`.
- Claude Code setup advice is up to date, and an outdated Claude Code no longer counts as ready.
- *Read again* no longer starts two paid readings of the same letter.
- Phone access no longer offers VPN or virtual-machine addresses on Windows, and learns the router later
  when it couldn't read it at turn-on.
- A phone is no longer signed out when two page loads cross the hourly sign-in change.
- A hanging sync folder no longer leaks a thread per scan.
- Kept sync copies are tested and written safely.
- Backups use sync's passphrase strength check and key stretching.
- macOS and Windows: CI runs the code that differs there (the lock, durable writes, sync, phone access,
  autostart, backups) weekly and on main. On macOS a durable write now flushes the drive's cache
  (`F_FULLFSYNC`; it was a plain fsync), and a Windows checkout, also the one `pipx install git+…` makes,
  keeps every file byte for byte, so `ordnung demo` uses its prebuilt database there instead of rebuilding
  it.

### Upgrading

- Follow [Updating](README.md#updating): `pipx reinstall ordnung` (or `uv tool upgrade ordnung`), then
  `ordnung doctor`. With hand-off sync, update both computers.
- A letter keeps the reading it was given. One read before extraction prompt version 9 or 12 lacks what
  those versions added; *Read again* on its page reads it with the current prompt
  ([Limitations](README.md#limitations)).
