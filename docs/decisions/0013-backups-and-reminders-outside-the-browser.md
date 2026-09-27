# ADR 0013 — Backups and reminders that work while Ordnung is closed

**Status:** accepted · **Date:** 2026-09-27

## Context
Until now reminders were a calendar file and browser notifications that only appear while a tab is
open, and the daily tick ran only inside `ordnung serve`. The data export was JSON without the
original letters — for a local-first app, whose folder is the person's only copy, that is no
backup. Both gaps sit where Ordnung touches the rest of the computer and beyond: the login
session, the notification system, the person's own calendar, files that leave for another drive or
a cloud. Mistakes there are hard to see
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
fixed script or in environment variables, never a shell line. It leads with what ends today — a
remedy whose last day is today outranks a small fee a week overdue — and discreet mode counts
today's apart. Once a day at the chosen time (the tick wakes up for it) or a minute after start-up
(at login the desktop's notification service may not be up yet); a notification the system
couldn't show is tried again at the next checks, three times a day at most, and the last failure is
kept for Settings; a missing tool uses the day up, so it is not retried every 15 minutes. Policy:
`ordnung/notify/desktop.py`.

**Calendar sync is opt-in, discreet, and touches only Ordnung's own events.** Pushing events to
the person's own calendar (CalDAV) is the one reminder that leaves the computer, so: nothing is
sent until a calendar is connected in Settings, after the person has seen every event exactly as
it would be sent; the default mode keeps only the date, the time and the alarms ("Ordnung:
deadline" — no titles, names or amounts); *with details* is a choice with a stated consequence.
It sends the `.ics` export's events, one resource per stable UID, so re-sending replaces instead
of duplicating; a digest per sent event means only changes are sent and only resources Ordnung
created are ever replaced or deleted. It keeps itself current from the tick of `ordnung serve` —
the person's own calendar, opted into, is not a counterparty, so this is not an automatic
"sending" in the sense of ADR 0006; a refused password pauses it (repeated failed logins lock
accounts). The app password goes to the OS keyring through the `keyring` package (a regular
dependency: an optional extra would have to be named in a pip command for a package that isn't on
PyPI, and would land in another environment than a pipx or uv tool install) — never the database —
and without a usable keyring calendar sync is unavailable rather than falling back to a file:
backends that don't keep secrets safely (`null`, `fail`, `keyrings.alt`, priority below 1) are
refused, and whether there is one is asked without reading a secret (reading can prompt to unlock
a keyring). While a calendar is connected, Ordnung doesn't also suggest importing the calendar file
(the same UIDs would clash), and "Delete everything" first removes Ordnung's events and the
password — refusing, with nothing deleted, when it can't: after the wipe nothing would remember
which events were Ordnung's. Discovery (well-known URI, principal, calendar
home) makes "iCloud with an app password" work without hunting for a calendar URL. Chosen over
publishing a feed URL (a public link to the ledger) and over the `caldav` library (a large
dependency for four requests). Policy: `ordnung/calendar/caldav.py`.

**The backup is one authenticated, versioned file.** AES-256-GCM in the STREAM construction (1 MiB
chunks; nonce = random prefix ‖ counter ‖ last flag; the header as associated data), a key from
scrypt (N = 2¹⁷, r = 8, p = 1) split by HKDF into a data key and a header-MAC key, and a header that
starts with a magic and a version byte. Chosen over one-shot AES-GCM (the whole backup in memory),
over a zip with a password (weak or unauthenticated in common tools) and over a new dependency
(`cryptography` already ships with `pdfminer.six`). What it buys: a wrong passphrase is told apart
from a changed file before anything is decrypted; a newer format is refused before a key is
derived; every changed, cut, reordered or appended byte fails; and a crafted header can't make
scrypt use more than 256 MiB of memory (128·r·N) or p > 2 — the key is derived before the header
MAC can reject anything, so the reader caps the cost, not only each parameter. The database snapshot is SQLite's online backup, taken in memory, so the copy
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
- A lost passphrase loses the backup — stated before a passphrase is asked for (the dialog's
  description, the CLI's line before the prompt); Ordnung never stores it. The web app offers a
  random one, with a Copy button, to put into a password manager.
- The browser download holds the whole backup in memory before saving it (a Blob); very large data
  folders are better backed up with `ordnung backup`.
- Calendar sync overwrites an event of Ordnung's that the person edited in their calendar app at
  the next change in Ordnung — Ordnung's dates are changed in Ordnung. Servers that only accept
  Digest authentication or OAuth (Google Calendar) are not supported; Google users keep the `.ics`
  download.
