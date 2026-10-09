# Changelog

What changed in each version of Ordnung, newest first. `ordnung --version` shows the one you have, and
[Updating](README.md#updating) says how to get the newest.

## Unreleased

### Added

- **Ordnung suggests a sender's state from the postcode on their letter.** A sender's state decides which
  public holidays move the dates of their letters; until you set it, Ordnung counts only nationwide
  holidays, so a date can come out a day or two early, or a day late when it is counted backwards from an
  event (its *Why this date?* then says to act a working day before it). Now it asks *Is X in Bavaria?*
  with the postcode it read, in the sender's details, and on the letter and in Today's Ideas when one of
  their dates may change. It never sets the state without you: *Yes* sets it (with Undo), *Don't know*
  leaves their dates as counted without it
  ([ADR 0019](docs/decisions/0019-a-sender-s-land-is-suggested-never-set.md)). The lookup runs on your
  computer. Postcode data © GeoNames, CC BY 4.0.

### Fixed

- When Claude's usage limit is reached, the time Ordnung says it continues at is in your profile's time zone,
  not the computer's.
- The app no longer has a design-system page at `/dev/ui`; it stays in the demos and in development.
- Windows: the message that another Ordnung process is using the data folder names that process ("pid N:
  ordnung serve"), as on Linux and macOS, and so does restore's.
- Windows: stopping Ordnung, and hand-off sync from the command line when it ends, now wait up to 20 seconds
  for a running sync operation before closing the database, instead of leaving it open. An operation still
  running after that (on a share that stopped answering) may still hold it.

### Upgrading

- A computer still on 0.2.0 that receives the new question by hand-off sync shows it among its Ideas but
  never takes it away once it no longer applies. Update both computers.

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

- Updates install: the version now goes up with each release (the Python package reads it from
  `src/ordnung/__init__.py`; tests check that the web app and the demo say the same), and
  [Updating](README.md#updating) says how to update.
- Claude Code setup advice follows Anthropic's installer for each system and names the Claude plans that
  include it. A Claude Code older than 2.1.0 no longer counts as ready: letters wait, and nothing is sent,
  until it is updated.
- *Read again* no longer starts two paid readings of the same letter: while one waits or runs, it gets
  that one.
- Phone access on Windows no longer offers VPN addresses, nor a virtual machine's unless the router is on
  its network; it recommends the address on the router's network, and learns the router later when it
  couldn't read it at turn-on.
- A phone is no longer signed out when two page loads cross the hourly sign-in change.
- A sync folder that stops answering no longer leaves a thread behind on each look: a file that hangs
  is skipped at once until it answers, other files (this computer's own saves too) go on, and at most 4
  calls wait at a time. Until the folder answers, Ordnung looks at it every 3 minutes instead of every
  15 seconds.
- Kept sync copies: forgetting a computer on a full disk is refused for lack of space instead of failing
  with an internal error, and the record of kept copies reaches the disk before it counts. Both now have
  direct tests.
- Backups: a new backup's passphrase must be as strong as a new sync folder's (about 70 bits: five or more
  unrelated words; one Ordnung 0.1.0 suggested still counts), and new backups use sync's key stretching
  (scrypt 2^18, 256 MiB). Older backups still open.
- macOS and Windows: CI runs the code that differs there (the lock, durable writes, sync, phone access,
  autostart, backups) weekly and on main. On macOS a durable write now flushes the drive's cache
  (`F_FULLFSYNC`; it was a plain fsync), and a Windows checkout, also the one `pipx install git+…` makes,
  keeps every file byte for byte, so `ordnung demo` uses its prebuilt database there instead of rebuilding
  it.

### Upgrading

- Follow [Updating](README.md#updating): `pipx reinstall ordnung` (or `uv tool upgrade ordnung`), then
  `ordnung doctor`. With hand-off sync, update both computers.
- Ordnung now needs Claude Code 2.1.0 or newer; `claude update` updates it. Until then letters wait.
- `ordnung backup` and the download in Settings → Data refuse a passphrase under about 70 bits by
  Ordnung's estimate and suggest five made-up words instead. The estimate counts words, so many random
  passwords from a password manager fall short too (symbols don't count); a passphrase Ordnung 0.1.0
  suggested still counts as strong. One a script gives in `ORDNUNG_BACKUP_PASSPHRASE` that falls short only
  gets a warning, so a scheduled backup is still made; change it when you can. Backups made before still
  restore.
- Phone access turned on at a VPN's or a virtual machine's address before keeps listening there: turn it
  off and on again in Settings → Phone, which now offers only home-network addresses (your phones pair
  again).
- A letter keeps the reading it was given. One read before extraction prompt version 9 or 12 lacks what
  those versions added; *Read again* on its page reads it with the current prompt
  ([Limitations](README.md#limitations)).
