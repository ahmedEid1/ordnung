# ADR 0018 — Hand-off sync through a folder you already sync

**Status:** accepted · **Date:** 2026-10-07 · revised after an attack review of the design (36 findings,
all adopted)

## Context
Ordnung is local-first: one data folder, served on 127.0.0.1, with the claude CLI on each computer.
People with a laptop and a desktop want the same Ordnung on both. Most already run a file-sync tool
(Nextcloud, Syncthing, Dropbox, iCloud Drive, a NAS share). Such a tool delivers files late, in any order,
sometimes in pieces, sometimes as online-only placeholders, and keeps conflicting copies side by side; the
two computers' clocks differ; either computer can lose power, be restored from an OS backup or be closed
mid-reading. Ordnung must not run a server, must not merge a person's records, and must not hand that tool
plaintext. Like backups and calendar sync (ADR 0013), this is where Ordnung touches the rest of the
person's world and mistakes are hard to undo, so it gets a short written policy (ADR 0007) rather than
cleverness.

## Principle
No change the person made is ever lost without their say: local data is replaced only when the incoming
copy provably contains every change of the person's it has, or when the person chose, or when the local
data went back in time — and in the last two cases it is saved as an encrypted copy on that computer
first.

## Decision

**One computer is in use at a time; the others stand by.** A computer standing by runs no background
work (readings, the day change, the brief, the watched folder, calendar sync, desktop reminders) and
refuses every write before a handler runs (409 `standby`), on the computer's listener and the phone's
alike; a backup and phone access, which change nothing that travels, stay allowed. "Use Ordnung here"
brings everything over and makes that computer the one in use, with one click and no "are you sure?" — a
take-over loses nothing. A computer in use never stops being in use because the other went quiet: silence
ends no lease. Chosen over merging records (dates, suggestions and drafts of one letter have no right
answer a program can pick) and over syncing the live database file (a sync tool copying SQLite mid-write
corrupts it). Policy: `ordnung/sync/__init__.py`.

**The folder holds only ciphertext under names that mean nothing.** A random vault key, wrapped by scrypt
of the passphrase (2^18, r 8, p 1: 256 MiB, the most a backup reader allows), keys everything through
HKDF subkeys; every file is AES-256-GCM STREAM in 1 MiB chunks bound to its name, kind and vault; names
are keyed hashes; sizes are padded (Padmé, at most 12 %, at least 4 KiB); the 92-byte key file has no
plaintext byte, so the folder holds none at all. Objects named by their content get their salt and nonce
prefix from a keyed hash of the name, so two computers writing the same object write the same bytes and
the sync tool never makes a conflict copy of it. A new folder's passphrase must reach about 70 bits by a
simple, documented estimator (distinct words and digit runs, each at most 14 bits; one character again and
again, a run in order, a keyboard walk or one of a few hundred very common words counts little; a password
manager's random password counts its length × log2 of the alphabet it uses, unless it shows such a pattern
or reads as words), and setup — in the web app and the CLI — suggests five random made-up words: the key
file sits at the provider indefinitely, open to offline guessing. Ordnung suggests a neutral name for the
folder ("Vault"): the provider sees the folder's name. Chosen over
one encrypted backup file per push (every push would re-send every letter, and the backup header names
the app) and over plain content hashes as names (they would let anyone confirm that a known PDF is
there).

**Every file in the folder has one writer.** Each computer rewrites only its own head; objects are
write-once and named by their content; a computer deletes only its own temporary files and objects no head
has referenced for 7 days of its clock and 7 × 24 hours of its own running time (a database slice that
every computer has moved past goes after a day: a reading rewrites many). Names that aren't
Ordnung's — the tool's conflict copies, `.stfolder`, `desktop.ini`, the person's own files — are ignored
and never deleted. The sync tool never has to merge a file.

**A version counts the person's changes, not the computer's.** Every write the person makes — through the
web app, a phone, the CLI or the watched folder — bumps a counter in the same SQLite transaction, so a save
knows exactly which person changes its snapshot holds. Readings, the day change and calendar runs never
make one computer's copy "newer"; only the person's own edits, uploads, chats and scans do. So a laptop
that wakes up and finishes its work after the desktop took over is never a conflict, and a change the
person made there is never dropped: it is brought in by itself when it arrives late, or asked about when
both computers changed. A head may claim another computer's changes only up to the highest number that
computer published, so a bug or a stale head can't claim everything.

**Order comes from counters, never from clocks.** Lineage decides content; an epoch decides which computer
is in use; timers are each computer's own monotonic clock. At start a computer raises its counters to what
the folder shows, so a data folder put back from an OS backup (Time Machine, File History, rsync) never
reuses a number; if its database is older than what it last saved, it is a rollback, not a change: a kept
copy, then its own last save is brought back, with a notice — fenced like any replacement, so a write that
lands meanwhile is in the kept copy. That start waits until the folder shows this computer's own head
(a share not mounted yet, files online only): until then nothing is saved and no head is written, and a
command-line write saves only after the same start.

**Wait, verify, keep, then apply in one transaction.** A take-over waits until every object of the
version has arrived and authenticated with its expected SHA-256 — a short file, an online-only placeholder
(iCloud, a File Provider's dataless file, a Windows recall file), a read error or timeout counts as "not
arrived yet", never as damage — and a computer standing by says "has it" only for versions it verified
completely. The version is staged and verified outside the live data with writes still allowed; then
writes are fenced and the requests already admitted on both listeners finish, background work stops and
its threads drain, and the decision is taken again on what the database holds now. Only then a kept copy
when the person's data would be replaced, a journal, the files, the database replaced with SQLite's backup
API in one transaction, and pruning last. The data folder is never renamed: the lock, the server's
session file, the watched folder and the phone's keys live there, and read-only readers may hold the
database open. While sync is on the database is written with `synchronous=FULL`.

**Leaving keeps the last version for the others.** Disconnect and Delete everything save what isn't
saved, then mark the computer's head as having left with its version kept, so another computer's next
take-over still brings that version over; while no other computer has received it — worked out against
the version just saved, again after that last save — both ask a second time. A computer that sets sync up
again with exactly the data it left with is asked nothing, keeps its name, and its former self is no
longer listed. When another computer sends to the same calendar, Delete everything leaves Ordnung's events in it.

**What describes a computer stays on it.** The calendar connection (its "already sent" record travels and
is merged), the watched folder and what it already picked up, phone access, the Claude pause, the desktop
notification's bookkeeping, the lock and the session file never travel; nor do the privacy-log rows of a
backup made there, of its phone access and of its watched folder. The demo never syncs.

**The passphrase lives in each computer's password store only.** It is typed once per computer, kept in
the OS keyring (service "Ordnung sync", an account per data folder), and never in the folder, the
database, `sync/state.json`, a log, an answer or a backup; the status never reads it. Without a usable
keyring sync is unavailable on that computer; there is no file fallback.

**Kept copies are ordinary encrypted backups.** A kept copy is a backup file (format v1, the sync
passphrase) in `<data>/sync/kept/`, opened with `ordnung restore`. It is the one backup file Ordnung writes
inside the data folder it backs up — it exists to undo a replacement on this computer, not to survive the
disk — so it is never synced, never pruned by itself, and lost with this computer's disk and with Delete
everything. Why and when each was kept is written next to them, so they stay listed — downloadable and
deletable — after Disconnect and after sync is set up again.

## Consequences and known limits
- Nothing is merged: changes made on two computers that couldn't see each other mean a choice, asked once.
  The other computer's Ordnung stays there as a kept copy once that computer next starts or takes over.
- "In use" is only as fresh as the sync tool. A folder that withholds files can delay a switch or make a
  computer take over an older copy (the person chooses that); it can never get a forged, partial or
  older-than-seen state applied.
- The folder's provider sees the folder's own name (and someone who knows the open format recognises its
  layout), how many encrypted files there are, their approximate sizes, how many computers take part, and
  when things change — and from bursts of new objects roughly how many letters and
  pages are added; never their names, dates, senders, content or the computers' names. Its version history
  and trash may keep old ciphertext.
- A computer standing by sends no reminders, reads no letters and updates no calendar. A take-over re-reads
  letters that were mid-reading on the other computer, so those Claude tokens are spent twice.
- All computers need an Ordnung that can read each other's database; a newer one makes the older wait.
- Calendar sync is connected on each computer; what was sent travels with the data.
- Forgetting a lost computer removes it from the folder's list but does not lock it out: it still knows the
  passphrase. To lock it out, set up a new sync folder with a new passphrase — changing the passphrase is
  not in this version (the format is ready for it). At most 8 computers share one folder.
- The passphrase estimator is simple: it knows a few hundred very common words, runs and keyboard rows,
  not a dictionary, so a passphrase of ordinary words that belong together (a line of a song) can still
  pass. The suggested five made-up words are the safe choice.
- A folder of the layout (`h/`, `o/`, a shard) that turns into a link stops saving — shown as "the sync
  folder doesn't answer" — until the link is removed; the check and the write are separate steps, so a
  link swapped in between them isn't caught (someone with that timing could delete the folder anyway).
- Setting sync up again after Disconnect asks nothing only while the data is exactly what it left with;
  once this computer's own work changed something (the day changed, a reading finished), joining asks which
  Ordnung to keep, as for any computer that joins with letters of its own. If what it left with hasn't
  arrived yet when it joins, its former self stays listed (as having left) until it is forgotten by hand.
- A computer standing by whose computer in use left shows "No computer is using Ordnung now" until it
  uses Ordnung here; nothing is brought over or saved before that.
- Tested with a simulated sync tool — late, out of order, in pieces, with conflict copies and dataless
  files — through crash and power-cut harnesses, a two-computer model, and two data folders served by two
  real `ordnung serve` processes on one machine in the browser tests. A pass with a real Nextcloud,
  Syncthing or iCloud Drive folder on two physical computers is still to be done by the person.
