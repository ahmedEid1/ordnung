# ADR 0013 — Backups and reminders that work while Ordnung is closed

**Status:** accepted · **Date:** 2026-09-27

## Context
Until now reminders were a calendar file and browser notifications that only appear while a tab is
open, and the daily tick ran only inside `ordnung serve`. The data export was JSON without the
original letters — for a local-first app, whose folder is the person's only copy, that is no
backup. Both gaps sit where Ordnung touches the rest of the computer: the login session, the
notification system, files that leave for another drive or a cloud. Mistakes there are hard to see
and hard to undo, so each gets a short written policy (ADR 0007) rather than cleverness.

## Decision

**Start at login writes one file and runs nothing.** `ordnung autostart enable` writes the system's
own kind of entry (a systemd user unit and the link `systemctl --user enable` would make, a
LaunchAgent, a Startup-folder `.cmd`), prints exactly what it wrote where and the one command that
starts it now; it never runs a service manager, and `disable` removes only that entry. The entry
discards the server's standard output — the sign-in link carries the session token, which must not
land in a system journal readable by administrators. Policy: `ordnung/autostart.py`.

**The desktop notification is code's words, discreet by default.** It is built from the
deterministic agenda (`build_agenda`), never by a model, so it can't say anything the ledger doesn't
(ADR 0002) and costs no tokens. A notification is seen on lock screens and kept in notification
histories, so the web app switches it on as *discreet* — a count only — and *full* (titles, amounts,
days) is a choice with a stated consequence. Letters' words reach the system tool as arguments of a
fixed script or in environment variables, never a shell line. Once a day, at or after the chosen
time; the attempt uses the day up, so a missing tool is not retried every 15 minutes. Policy:
`ordnung/notify/desktop.py`.

**The backup is one authenticated, versioned file.** AES-256-GCM in the STREAM construction (1 MiB
chunks; nonce = random prefix ‖ counter ‖ last flag; the header as associated data), a key from
scrypt (N = 2¹⁷, r = 8, p = 1) split by HKDF into a data key and a header-MAC key, and a header that
starts with a magic and a version byte. Chosen over one-shot AES-GCM (the whole backup in memory),
over a zip with a password (weak or unauthenticated in common tools) and over a new dependency
(`cryptography` already ships with `pdfminer.six`). What it buys: a wrong passphrase is told apart
from a changed file before anything is decrypted; a newer format is refused before a key is
derived; every changed, cut, reordered or appended byte fails; and a crafted header can't make
scrypt use gigabytes. The database snapshot is SQLite's online backup, taken in memory, so the copy
is consistent while Ordnung runs and no plaintext touches the disk. Policy: `ordnung/backup/`.

**Restore proves everything before it replaces anything.** It extracts into a staging folder next to
the target under a name policy (regular files: `ordnung.db`, `manifest.json`, paths under `files/`,
`derived/`, `drafts/`), reads the encrypted file to its authenticated end even after the archive's
end marker, checks every file against the manifest's sizes and hashes and the database's integrity,
schema version and row counts, and only then swaps the folder in. It never replaces a folder with
data unless asked (`--force`), and then moves it aside; it never runs under a held lock.

## Consequences
- Reminders reach the person with the browser closed, and the backup is something they can put on
  another drive or in the cloud without trusting it.
- A lost passphrase loses the backup — stated wherever a passphrase is asked for; Ordnung never
  stores it. The web app offers a random one to put into a password manager.
- The browser download holds the whole backup in memory before saving it (a Blob); very large data
  folders are better backed up with `ordnung backup`.
- Not decided here, left as a follow-up: pushing events to the person's own calendar over CalDAV
  (credentials in the OS keyring, a discreet event text, an event-by-event preview). It sends event
  text to a third party, so it needs its own opt-in design and a fake CalDAV server in the tests.
