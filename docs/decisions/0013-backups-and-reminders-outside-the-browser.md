# ADR 0013 — Backups and reminders that work while Ordnung is closed

**Status:** accepted · **Date:** 2026-09-27 · **Updated:** 2026-10-08 (a new backup's passphrase and key
costs are a new sync folder's), 2026-10-09 (Ordnung says when the last copy is old)

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
which events were Ordnung's. A digest records what was sent, not what the calendar still holds,
so once a day (and on "Sync now") Ordnung asks — with a `calendar-multiget` of its own resource
names only — which are still there, and sends missing ones again: an event deleted in the calendar
app, or by another copy of Ordnung, comes back instead of staying lost while Settings says
"synced". A backup carries the connection (address, mode) but it belongs to its data folder: the
keyring account names the folder's connection id, and a restored copy gets a new one and starts
paused without a password or any claim on the original's events — so a copy restored next to the
running Ordnung (or on a new computer while the old one still syncs) can't remove the original's
events or delete its password. Discovery (well-known URI, principal, calendar
home) makes "iCloud with an app password" work without hunting for a calendar URL. Chosen over
publishing a feed URL (a public link to the ledger) and over the `caldav` library (a large
dependency for four requests). Policy: `ordnung/calendar/caldav.py`.

**The backup is one authenticated, versioned file.** AES-256-GCM in the STREAM construction (1 MiB
chunks; nonce = random prefix ‖ counter ‖ last flag; the header as associated data), a key from
scrypt (N = 2¹⁸, r = 8, p = 1: 256 MiB, as for a sync folder's key file) split by HKDF into a data key and
a header-MAC key, and a header that starts with a magic and a version byte. Chosen over one-shot
AES-GCM (the whole backup in memory), over a zip with a password (weak or unauthenticated in common
tools) and over a new dependency (`cryptography` already ships with `pdfminer.six`). What it buys: a
wrong passphrase is told apart from a changed file before anything is decrypted; a newer format is
refused before a key is derived; every changed, cut, reordered or appended byte fails; and a crafted
header can't make scrypt use more than 256 MiB of memory (128·r·N) or p > 2 — the key is derived
before the header MAC can reject anything, so the reader caps the cost, not only each parameter. The database snapshot is SQLite's online backup, taken in memory, so the copy
is consistent while Ordnung runs and no plaintext touches the disk. Policy: `ordnung/backup/`.

**A new backup's passphrase is as strong as a new sync folder's.** A backup goes where a sync folder's key
file goes — another drive, a cloud folder — and whoever copies it can guess at it offline for years, so
the rule is the same (ADR 0018). A new backup's passphrase must reach about 70 bits by the estimator a new
sync folder's meets (`ordnung/passphrase.py`), besides 12–1024 characters, and the CLI and the web app
suggest five random made-up words. It is checked where a passphrase is chosen (`ordnung backup`, the
download); a kept copy of hand-off sync uses the sync passphrase, judged when its folder was set up. Two
exceptions keep backups that worked before the rule working: what Ordnung 0.1.0's dialog suggested (four
random groups of five letters and digits, about 99 bits) still counts as strong, and a passphrase a script
gives in `ORDNUNG_BACKUP_PASSPHRASE` that falls short gets a warning, not a refusal, so a scheduled backup
is still made (12 characters are still required). The key costs went from 2¹⁷ to sync's 2¹⁸ with the same
change: the header records them, so a backup made with the earlier ones opens as before.

**Restore proves everything before it replaces anything.** It extracts into a staging folder next to
the target under a name policy (regular files: `ordnung.db`, `manifest.json`, paths under `files/`,
`derived/`, `drafts/`), reads the encrypted file to its authenticated end even after the archive's
end marker, checks every file against the manifest's sizes and hashes and the database's integrity,
schema version and row counts, and only then swaps the folder in. It never replaces a folder with
data unless asked (`--force`), and then moves it aside; it never runs under a held lock. A restored
copy doesn't take over the watched folder's consent either: which files were already in the folder
when it was chosen, and which were picked up, belong to the computer the backup came from — a folder of
the same path elsewhere holds other files. So the restored copy forgets both (everything in the folder
waits for the person) and starts with reading new arrivals at once switched off until the person turns
it on again — also when a crafted backup switched it on.

**Ordnung says when the last copy is old, in its own words.** A backup only helps when it is recent, and
for a local-first app the data folder may be the person's only copy. So Ordnung notes every backup it
knows of: a privacy-log row for one made from Settings or with `ordnung backup` (a scheduled one too), and
one for the backup a restored copy came from, dated by that backup's own manifest. Hand-off sync's last
save counts as a copy while this computer saves into the sync folder or stands by while another one does:
the sync tool copies that folder off this computer, which Ordnung can't check, so the docs say so. A backup
made from Settings is noted once the server has sent it; whether the browser saved the file can't be known.
Kept copies don't (they are on the same disk), nor do backups of the whole computer such as Time Machine or
File History, which Ordnung can't see. When there are letters and the newest copy is more than 30 days old,
or there is none, Settings → Data says so in the warning tone and the weekly review ends with a reminder
(never in the demo, nor on a computer standing by); `ordnung doctor` warns too. The reminder is code's
words on those three places and never an Idea: Ideas' titles go to the model in the daily note and the
weekly Ideas review, travel with hand-off sync while backups are per computer, and reach paired phones,
which can't make a backup. Both privacy-log rows stay on their computer (`sync.LOCAL_ACTIVITY_KINDS`).
The CLI writes its row with plain SQLite, never into a database newer than it knows, and a failure to write
it never fails the backup. The doctor also says, on macOS and Linux and as a best effort, whether the disk
under the data folder is encrypted, only reading what the system reports (`ordnung/encryption.py`); on
Windows that answer would rest on values Microsoft doesn't document, so there is no check and the docs say
where BitLocker is. Both checks only ever warn. Policy: `ordnung/backup/reminder.py`.

## Consequences
- Reminders reach the person with the browser closed, and the backup is something they can put on
  another drive or in the cloud without trusting it.
- A lost passphrase loses the backup — stated before a passphrase is asked for (the dialog's
  description, the CLI's line before the prompt); Ordnung never stores it. The web app offers a
  random one, with a Copy button, to put into a password manager; the CLI prints one before the prompt.
- A passphrase that is long but easy to guess (a short sentence of common words) is refused for a new
  backup; from `ORDNUNG_BACKUP_PASSPHRASE` in a script it gets a warning. A password manager's random
  password with capital and small letters passes: the estimator counts words, or random characters by the
  alphabet they use (14 random letters and digits are about 83 bits) unless they show a pattern people
  make (a common word, a year or a date, a run, a keyboard walk also typed with Shift, a repeat, words also
  in capitals, caps lock's or alternating case), and Apple's strong passwords by their shape. When every
  letter is in a word, only the other characters count as random ones. Random small letters alone look
  like one long word and count as one. In 0.2.0 it counted words only, so symbols and capitals counted
  nothing and many such passwords were refused.
- The browser download holds the whole backup in memory before saving it (a Blob); very large data
  folders are better backed up with `ordnung backup`.
- Someone who backs up only with Time Machine or File History sees the reminder at the end of each weekly
  review once 30 days have passed: Ordnung can't tell those backups exist. A scheduled `ordnung backup`
  quiets it.
- Calendar sync overwrites an event of Ordnung's that the person edited in their calendar app at
  the next change in Ordnung, and puts back one they deleted there at the next daily check —
  Ordnung's dates are changed in Ordnung. Two Ordnungs syncing one calendar (both connected by
  hand) still change each other's events; the restore says to disconnect the original first.
  Events the original sent after the backup was made stay in the calendar when it disconnects
  without removing them. Servers that only accept
  Digest authentication or OAuth (Google Calendar) are not supported; Google users keep the `.ics`
  download.
