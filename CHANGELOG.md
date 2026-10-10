# Changelog

What changed in each version of Ordnung, newest first. `ordnung --version` shows the one you have, and
[Updating](README.md#updating) says how to get the newest.

## Unreleased

### Added

- **Dates you add yourself can repeat.** *Add a date* has a *Repeats* choice: every month on its day, every
  month on a working day (the 3rd, the last …), every 3 or 6 months, or every year. A repeating date shows its
  next day, moves on when you mark it done or once its day has passed, and is never overdue because a month
  went by. Your own dates can be edited later: choose *Edit* on the letter's page, or open one without a
  letter from Timeline. When you change the day of one that repeats, you choose whether only that one moves
  or every one after it (one on a working day moves alone); *Remove* stops it, with Undo.
- **A letter addressed to someone else says so.** When a letter names someone other than you (your partner,
  your child, "Familie …"), its page shows *Addressed to …* under its title. A reply, objection, template
  letter or cancellation you write from it still starts in your name: its *From* field says who the letter
  was addressed to, and one press (*Reply in Alex Rivera's name*) fills in that name; *Use my name* goes
  back. The letter's sender block, signature, PDF and proof of sending then use it, and so does a name you
  type into the letter's *From* later. Ordnung doesn't add the name to what it sends Claude, but the related
  letter's title and summary, sent as read, often name the person it was addressed to. Everything else about
  the letter stays yours: its dates, reminders and numbers.
- **Ordnung reminds you to back up, and says what to do if your computer is lost.** It now notes every
  encrypted backup — from Settings → Data, from `ordnung backup` (a scheduled one too) and the backup a
  restored copy came from — and Settings → Data says when the last one was made. When it is more than 30 days
  old, or there is none, the weekly review ends by saying so. A backup from Settings counts once your
  browser has received it, also if you then cancel saving the file. While hand-off sync is connected, its
  copy in your sync folder counts too, because your sync tool copies that folder elsewhere (Ordnung can't
  check that it does); backups of the whole computer (Time Machine, File History) don't, because Ordnung
  can't see them. `ordnung doctor` (and *Run check* in Settings) adds two checks that only ever warn:
  your last backup and, on macOS and Linux, whether the disk under the data folder is encrypted (FileVault,
  LUKS, as a best effort). [docs/privacy.md](docs/privacy.md#if-your-computer-is-lost-or-stolen) has a
  checklist for a lost or stolen computer: before, a backup and disk encryption (BitLocker or Device
  encryption on Windows); after, restore your backup, a new sync folder with a new passphrase, sign out of
  Claude, your phones and the calendar.
- **Ordnung suggests a sender's state from the postcode on their letter.** A sender's state decides which
  public holidays move the dates of their letters; until you set it, Ordnung counts only nationwide
  holidays, so a date can come out a day or two early, or a day late when it is counted backwards from an
  event (its *Why this date?* then says to act a working day before it). Now it asks *Is X in Bavaria?*
  with the postcode it read, in the sender's details, and on the letter and in Today's Ideas when one of
  their dates may change. It never sets the state without you: *Yes* sets it (with Undo), *Don't know*
  leaves their dates as counted without it
  ([ADR 0019](docs/decisions/0019-a-sender-s-land-is-suggested-never-set.md)). The lookup runs on your
  computer. Postcode data © GeoNames, CC BY 4.0.
- **Your tax year, and your letters as files.** *Inbox → Letters for taxes* lists the letters that could
  matter for a year's tax return, by the date on the letter (else the day it arrived) and grouped by kind,
  each with Claude's note on why, then the ones dated January–May of the next year, when yearly statements
  such as the *Lohnsteuerbescheinigung* usually arrive: check which year each is for. Today's tax-season
  Idea (*Your 2025 tax documents are ready to collect*) now opens it, and so does a letter's tax note.
  *Export letters* (Settings → Data, or *Export these letters…* on a tax year) downloads your letters'
  original files as one ZIP, in folders by year and sender
  (`2025/Finanzamt Musterstadt/2025-03-14 Steuerbescheid 2025.pdf`), with `index.csv` for a spreadsheet.
  It runs only when you click it, on your computer, never from a phone, and it writes and sends nothing.
  The ZIP isn't encrypted: anyone who has it can read the letters, so keep it safe.
- **Scans you keep private, or add while Claude isn't connected, can be found by their words.** Many
  scanners and phone apps save a "searchable PDF": a picture of the page with the scanner's own reading of
  it as hidden text. Ordnung never takes that text for the letter's words (it reads the picture, and checks
  what it read against the paper), and until now it threw the text away, so such a scan was found only by
  its file name. Now the scanner's text is kept with the letter's page images for search only: a letter
  found that way says *Found in your scanner's text — not checked*, and its page says what that text is
  for. It is never shown as the letter's words, never used to check a date or an amount, and never sent to
  Claude; Ask doesn't search it. Once Claude has read a page, that page's scanner text is removed. Scans
  you added before are caught up in the background after the update
  ([ADR 0020](docs/decisions/0020-a-scanner-s-text-is-for-finding-not-reading.md)).
- **A moving checklist.** When you change your address in Settings → Profile and tick *I moved*, Today
  lists who needs your new address: first, registering at the citizens' office (Bürgeramt) within two
  weeks of moving in (§ 17 Abs. 1 BMG); then the organisations Ordnung knows from your contracts and
  letters — your bank, insurers, employer, landlord, utilities and others — each with the new-address
  letter one click away (your old address and the day filled in); and the broadcasting fee office, when
  it isn't among them. Tick a row off, or mark it *Not needed*, with Undo; a sender's row goes by itself
  once you mark a new-address letter to them as sent. The checklist is for a move in the last six months
  or the next three, ends six months after the move, and *Stop the checklist* ends it at once. Nothing is
  sent for you, and no row names an address
  ([ADR 0021](docs/decisions/0021-a-move-is-said-never-guessed.md)).
- **Open Ordnung from your app menu.** `ordnung shortcut` adds Ordnung to your app menu on Linux, to your
  Applications folder on a Mac (Launchpad and Spotlight find it), or to the Start menu on Windows. Opening
  it signs your browser in. When Ordnung isn't running, it starts in a window of its own, and closing that
  window stops it. Ordnung is never started without a window you can see. When it already runs (for
  example from start at login), only the browser opens. `ordnung shortcut` prints what it writes before
  writing, needs no admin rights and never replaces or removes a file it didn't write; `--dry-run` only
  prints, and `ordnung shortcut --remove` takes it out again. Settings → Reminders shows whether it is
  there, and for which data folder. The demo isn't added: it opens with `ordnung demo`.
- **Releases.** A version tag builds the wheel and the source package, checks them, and publishes a GitHub
  Release with this changelog's section. Publishing to PyPI waits until the owner has set it up
  ([docs/releasing.md](docs/releasing.md)): until then a release goes to GitHub only. It uses PyPI's
  Trusted Publishing, so no token is stored anywhere, and a pull request never publishes. On PyPI the
  README's links and pictures point to GitHub.
- **CI checks more.** It replays the holdout, holdout2 and dev splits too, and the numbers without the
  sender's Land, each gated at the published number (no model calls); its slow checks run in a job of their
  own. Coverage now counts branches and has floors for the whole package, hand-off sync and phone access.
  Weekly, it fails once the rules were last checked against the law more than 90 days ago, and checks that a
  freshly installed Claude Code (the newest, and 2.1.0) still takes every flag Ordnung passes, without
  signing in.
- **The benchmark page pools the three held-out splits** into one table with tighter intervals, and each
  held-out split now also shows how the rest of each letter was read, the adversarial letters and what its one
  recording cost ([docs/evals.md](docs/evals.md)). Scam letters are scored as the app decides too, beside the
  benchmark's looser rule: in the app, an IBAN that only fails its checksum is no scam sign on its own.
- README's Limitations now say that the app's own text is in English only, that Google Calendar and Outlook.com
  get the calendar file rather than live sync, and how much one hand-off sync save can upload on a large library.
- The web app's licence notices ship with it: `THIRD-PARTY-NOTICES.txt`, next to the built app and among
  the package's licence files, names every package and font the app bundles (the Inter and Fraunces
  fonts are under the SIL Open Font License) with its licence text. The package's licence expression now
  names every licence it ships: `MIT AND ISC AND OFL-1.1 AND Bitstream-Vera AND CC-BY-4.0`.
- [SECURITY.md](SECURITY.md) says how to report a security problem privately (where GitHub's private
  reporting is off, a *Security contact* issue form asks for nothing about the problem). A bug report now
  goes through a form that asks for `ordnung --version` and `ordnung doctor` and warns never to attach a
  real letter, and [CONTRIBUTING.md](CONTRIBUTING.md) says how to work on Ordnung.

### Changed

- The sign-in page and the *isn't running* screen say to open Ordnung from your apps if you added it there
  with `ordnung shortcut`, before the commands that start it.
- `ordnung serve` in a terminal suggests `ordnung shortcut` while Ordnung isn't in your app menu, and
  `ordnung autostart enable` says you can open the app from there too.

### Fixed

- A to-do added through the API with a working-day rule stayed on the day it was given until that day passed;
  it is now dated by its rule at once.
- A to-do that repeats on a working day ("bis zum 3. Werktag") says so on its letter's page and in the
  sender's details; it said only "every month".
- A letter added while Claude isn't installed, isn't signed in or is too old is found by the words in its
  PDF straight away. Before, only the first such letter was; the others were found by name until Claude
  read them.
- A password manager's strong random password with capital and small letters now protects a new backup or
  a new sync folder. 0.2.0 counted only words, so symbols and capitals counted nothing and many such
  passwords were refused. Now random characters count by the alphabet they use (14 random letters and
  digits are about 83 bits), unless they show a pattern people make: a common word, also in leetspeak; a
  year or a date, also with `_`, `#` or the like between its parts; a run or a keyboard walk, also typed
  with Shift; a repeat; or words, also in capitals, with caps lock on, in alternating case or in another
  script. A name or a word with digits and symbols ("Max#Richter#94"), also with a stray letter or two
  ("Andreas!88#Xy"), counts as its words and digits, and so does a word spelled in leetspeak
  ("Schm3tt3rl1ng!"). Random small letters alone look like one long word, so they still count as one.
  Apple's strong passwords ("xxxxxx-xxxxxx-xxxxxx") count too. Five unrelated words, and everything that
  passed before, still pass, except words typed with a dotless ı for an i ("Dıe"): they now count as the
  words they are, as the web app already counted them.
- When Claude's usage limit is reached, the time Ordnung says it continues at is in your profile's time zone,
  not the computer's.
- When the weekly review can't write Ideas (Claude didn't answer, or its limit is reached), Settings → Privacy
  & AI usage says so and that Ordnung tries again tomorrow; before, only Ordnung's log did.
- The app no longer has a design-system page at `/dev/ui`; it stays in the demos and in development.
- macOS: backups, and the copies hand-off sync keeps, are flushed to the disk itself before Ordnung goes on,
  as its other files are; before, they could still sit in the drive's cache.
- A big library stays quick: the weekly review, and the Ideas worked out again after each letter is read,
  no longer slow down with the square of the number of letters and senders.
- A PDF that hides a decompression bomb behind ASCII85 or ASCIIHex data with a stray character in it is
  refused at upload, as other bombs are. The check read such data strictly and counted nothing, while
  PDFium, which shows the letter, reads it up to (ASCII85) or past (ASCIIHex) that character. The check's
  LZW, RunLength, ASCII85 and ASCIIHex decoding now has tests of its own, compared with PDFium's.
- Windows: the message that another Ordnung process is using the data folder names that process ("pid N:
  ordnung serve"), as on Linux and macOS, and so does restore's.
- Windows: stopping Ordnung, and hand-off sync from the command line when it ends, now wait up to 20 seconds
  for a running sync operation before closing the database, instead of leaving it open. An operation still
  running after that (on a share that stopped answering) may still hold it.
- Windows: once Ordnung has stopped, its database is closed. Hand-off sync's thread, which ends as Ordnung
  stops, could still be closing its connection a moment later, so the data folder couldn't be deleted or
  replaced right away.

### Upgrading

- A computer still on 0.2.0 that receives the new question by hand-off sync shows it among its Ideas but
  never takes it away once it no longer applies. Update both computers.
- A computer still on 0.2.0 shows the repeating dates you add on a newer one and moves them on, but can't
  change how they repeat.
- On a computer still on 0.2.0, a letter written in someone else's name prints your name under its signature
  until it is marked as sent. Print such letters on an updated computer.
- A computer still on 0.2.0 shows its own tax-season Idea, whose *See the documents* opens one letter rather
  than the tax year (and it may count the year's letters slightly differently).
- A computer still on 0.2.0 finds a scan only by its name, as before, and deletes its scanner's text with the
  letter. A scan Claude reads there keeps its scanner's text until an updated computer receives it by hand-off
  sync and removes it.
- A computer still on 0.2.0 that receives the moving checklist by hand-off sync shows its rows among its Ideas
  and never takes them away, and saving the profile there forgets the move. Update both computers.
- Backups made with `ordnung backup` before this version left no note, so Ordnung has no record of them and
  says so until the next one, which counts.

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
