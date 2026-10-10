# Privacy & data flow

Ordnung is a **local app**. It has no server, no account, no telemetry, and it never sees your
Claude credentials. But it is not "offline AI": when Claude reads a letter, the content of that
letter is sent to Anthropic **through your own Claude account**. This page explains exactly what
goes where.

## At a glance

| Data | Where it lives | Leaves your computer? |
|---|---|---|
| Original files (PDFs, photos) | `<data dir>/files/` | Never by Ordnung itself |
| Your watched folder (optional) | wherever you chose | Ordnung only lists and reads it; a file there is copied in and **waits for you** before anything of it goes to Claude, unless you let new arrivals be read at once ([below](#the-watched-folder)) |
| Page images, thumbnails | `<data dir>/derived/` | Only as part of a *Read* call (see below) |
| A scanner's text (the hidden text a scanner adds to a "searchable PDF") | `<data dir>/derived/` (`scan-text.json`): kept with the letter's page images (so also in backups and hand-off sync), only for search | Only inside your encrypted backups and hand-off sync's encrypted copy, like the page images — never to Claude, and never shown ([below](#searchable-scans)) |
| Your ledger (letters, to-dos, contracts, ideas, drafts) | `<data dir>/ordnung.db` (SQLite) | Excerpts, when you use *Ask*, *Weekly Ideas* or *Letters* |
| Profile (name, address, region, the IBAN you may add for refunds; after you say you moved, the day you moved in and your old address) | `ordnung.db` | Name, language and region in prompts; the address and IBAN you enter here, and your old address, are never put into a prompt (a letter you add is read as printed, with the address in its window; letters Ordnung drafts that contain them reach Claude with placeholders, also when translated again, and get the real values back in the translation); the day you moved in reaches Claude only as the day to register by (two weeks later) in the moving checklist's first row, whose title and date *Weekly Ideas* and the daily note send like every Idea's, and as a new-address letter you write states it |
| Model responses | `ordnung.db` (`llm_cache`) | — (they came from Anthropic) |
| Usage log (tokens, cost, which document, the prompt's name and version, how the answer turned out) | `ordnung.db` (`llm_calls`) — **no prompt or response bodies** | Never |
| How each letter was read (its steps: counts, scores, computed dates, ids of records) | `ordnung.db` (`trace_spans`) — **no letter text**, the newest five readings per letter | Never (unless you export one with `ordnung trace`) |
| Fonts, UI, rules engine | bundled in the package | Never (no CDN, no web fonts) |
| Encrypted backups (`ordnung backup`, Settings → Data) | wherever you save the file | Only where you put it — encrypted, so without your passphrase nobody can read it |
| Exported letters (Settings → Data → *Export letters*, or *Export these letters…* on a tax year) | wherever you save the ZIP | Only as the ZIP you save, where you put it — **not encrypted**: your letters' original files and a list of them (`index.csv`) ([below](#your-controls)) |
| The morning desktop notification | your system's notification area | Never — Ordnung writes it on this computer from your dates |
| Calendar sync (only if you connect a calendar) | the calendar you connect (Nextcloud, iCloud, mailbox.org, …); the app password in your system's password store | To that calendar's provider: dates, times and alarms (discreet, the default) — or the events' titles, what to do, amounts and who it is with (with details) |
| Phone access (only if you turn it on) | the certificates in `<data dir>/phone/`; the paired phones (their names, when and from which address they were last used, a hash of each sign-in) in `ordnung.db` | Only to phones you paired, encrypted, on your home network — they show what is on the computer and keep no copy ([below](#phone-access-optional)) |
| Hand-off sync between your computers (only if you set it up) | an encrypted copy in the folder you choose; this computer's sync state in `<data dir>/sync/`; the passphrase in each computer's password store | Only where your own sync tool takes that folder: encrypted, under names that reveal nothing ([below](#hand-off-sync-between-your-computers-optional)) |

`<data dir>` defaults to your platform's user data folder (e.g. `~/.local/share/ordnung`,
`~/Library/Application Support/ordnung`, `%LOCALAPPDATA%\ordnung`) and can be changed with
`--data-dir` or `ORDNUNG_HOME`. On Linux and macOS the folder is private to your account (`0700`,
files `0600`), so other accounts on a shared computer can't read your letters or your ledger.

## What is sent to Claude, per feature

Every model call goes through the `claude` CLI you installed and signed in to, and names the
model it runs on: Sonnet 5 (`claude-sonnet-5`) unless you choose another under **Settings →
Claude** (`ORDNUNG_CLAUDE_MODEL`, while it is set, overrides both for every call). Anthropic's
handling of that data (retention, training use) is governed by **your** account
type and settings — see Anthropic's
[consumer terms & privacy settings](https://www.anthropic.com/legal/privacy) or, if you use an API
key, the [commercial terms](https://www.anthropic.com/legal/commercial-terms). Check your Claude
privacy settings before processing sensitive documents.

| Feature | Sent to Claude |
|---|---|
| **Read a letter** — text PDFs | the page text of that document, today's date, your country and region, your name, and the names and kinds of organisations you already have (no numbers from other letters) |
| **Read a letter** — photos/scans | each page image (JPEG, ≤ 1600 px) for transcription, then the transcribed text as above |
| **Weekly Ideas** (weekly; can be switched off in Settings) | a compact summary of open to-dos, contracts, recent letter summaries and warnings, the organisations involved, and your language, region and whether you are on a student visa |
| **Secretary's note** (optional) | today's agenda (titles, dates, amounts, organisations) and your first name |
| **Ask** | your question and the last few messages of the conversation; the assistant then reads what it needs through Ordnung's **read-only** tools (search results, document excerpts) |
| **Letters** | the related letter's title, date, summary and reference numbers, the contract's name and customer number, the letter's fixed wording (with your addresses and IBAN replaced by placeholders), the recipient's name (first line only) and your instructions — including facts you typed for a template letter, such as a defect's description. *Translate again* sends the letter's subject and text as they stand, with your profile's address and IBAN, the sender block's address, every IBAN and the addresses a template letter wrote replaced by placeholders; other text you typed into the letter yourself is sent as you wrote it. Ordnung doesn't add your name, or the name a letter goes out in, to the request. The related letter's title and summary are sent as they were read, though, and they often name you or the person the letter was addressed to |

Reading a letter can send its text more than once, never anything more: when Claude's answer doesn't fit
the form it is asked once more with the problems listed, and when its reading comes back incomplete (almost
blank, or without the deadline to object the letter's instructions state) it is asked once more for what it
left out ([ADR 0016](decisions/0016-an-incomplete-reading-is-asked-for-once-more.md)). A letter you
delete while it is being read is not sent again.

Ordnung's question about a sender's state (*Is X in Bavaria?*) comes from the postcode on their letter,
looked up on your computer in a table of German postcodes that ships with Ordnung (GeoNames); nothing is
sent or downloaded for it ([ADR 0019](decisions/0019-a-sender-s-land-is-suggested-never-set.md)). Like
every Idea's, its title (the sender's name and the state) is part of what *Weekly Ideas* sends.

The moving checklist, after you tick *I moved* in Settings → Profile, is worked out on your computer from your
contracts and letters; nothing is sent for it, and a letter you kept private, or a contract read from one,
never puts an organisation on it ([ADR 0021](decisions/0021-a-move-is-said-never-guessed.md)). Its rows never
contain an address: like every Idea's, their titles (an organisation's name, the day to register by) are part
of what *Weekly Ideas* and the daily note send.

You can inspect every call in **Settings → Privacy & AI usage**: purpose, which documents, how many
pages and bytes were sent, tokens, API-equivalent cost, and whether it came from cache. For Ask, that is
every letter whose text a tool result sent — a search hit's title and snippet, the letter a listed to-do
was read from, every letter a listed contract's terms were read from and a cancellation letter whose end
date it gives — not only the letters it opened. A call whose `claude` never started (Claude
not installed) sent nothing and lists no letter; a letter no call has carried says *Not sent to Claude*
on its page.

## My numbers

*My numbers* collects the numbers your letters already show — your Steuer-ID, social insurance and
health insurance numbers, student and passport numbers, customer and contract numbers, case references —
and sorts them on your computer. Nothing is sent anywhere to build the page, and its check-digit tests
run locally. On screen every number of yours is **hidden until you choose Show** (only its last few
characters stay visible), so someone looking over your shoulder doesn't read it; *Copy* works without
showing it. A case's reference — an invoice number, a Kassenzeichen, an Aktenzeichen — is shown as it is:
its letter and the Pay panel print it in full anyway. On a [paired phone](#phone-access-optional) the page
shows your own numbers with only their last 4 characters, also after *Show* or *Copy*, and so do the
IBAN in your profile and the numbers *Ask*'s numbers tool hands over for a question asked there: the full
numbers are on your computer. A letter itself still shows what is printed on it.

The numbers live in your ledger with the letters that show them. *My numbers* lists a number only
while a letter in your ledger shows it: delete that letter and the number leaves the page. One copy
outlives the letter: when a letter
is read, Ordnung notes the sender's customer, contract and membership numbers — and some document
numbers, such as a passport number on an authority's letter — on that organisation's record, so later
letters are matched to it. That copy stays after the letter is deleted, *Ask* can read it (the
`get_party` tool), and only *Settings → Delete everything* removes it.

The numbers reach Claude only when you use *Ask* and it looks them up (the `get_my_numbers` tool, like
every other ledger tool — it can hand over just one organisation's numbers or one part of the page, and
a letter you marked *Keep private — no AI* gives it nothing), when you draft a letter answering one of
your letters (its reference numbers — on a tax office's letter your Steuernummer or Steuer-ID — go with
it, see *Letters* above), or when you give another Claude client your ledger with
`ordnung mcp install --with-ledger` (see below).

A call sheet's phone, e-mail and website come from the organisation's letters without scam signs; a
letter with scam signs that imitates a known sender never puts its own phone number or address next to
your numbers.

The weekly session (*Weekly review*) stores only the moments you finished it or said "Not now".

## Your controls

- **Keep private — no AI** — every upload asks first: switch it on and the document is never sent to
  Claude. It is stored, search finds it by its name and by the text in the file — a PDF's own text, or
  the text a scanner added to a scan, kept for search only (a photo only by its name) — and you can add
  dates by hand. A letter you delete while it still waits to be read is never sent either.
- **The watched folder waits for you** — files your scanner or phone app saves into the watched folder
  are stored and read on this computer only, and wait in the Inbox ("From your folder — not read
  yet") until you choose *Read these* or *Keep private* ([details](#the-watched-folder)). *Keep
  private* can be undone (the toast's *Undo*, or *Undo "Keep private"* on the letter — for an e-mail,
  its attachments kept private with it wait again too).
- **E-mail attachments follow the e-mail** — each PDF or photo attached to an e-mail you add becomes
  a letter of its own with the e-mail's choice: attachments of a private e-mail stay private, those of
  a waiting e-mail wait with it.
- **Delete means delete** — deleting a letter removes it for good: the original, page images (and
  the text a scanner added to it), everything read from it, its to-dos and Ideas, its search-index
  entries, its entries in the activity log, quotes from it in contracts you keep, the record of how it
  was read, and the cached model responses of every call that carried it (a secretary's note or review
  built from several letters included). The usage log keeps only anonymous numbers (its calls' replay keys, which hash the
  letter's content, and their error texts, which may quote Claude's answer, are cleared too), and deleted
  database rows are overwritten rather than left behind. Originals and page images are never kept in the
  browser's cache, and deleting a letter for good or deleting everything also tells the browser to empty
  its cache. A paired phone keeps no copy either: every answer it gets is marked not to be stored, it
  can't download originals, letter PDFs or the calendar file, and a phone you removed is told to empty its cache and storage
  the next time it reaches Ordnung (a tab still open there shows what it last showed until it is closed).
  Contracts and letters you drafted stay, without the link to it; your *Ask* conversations stay as
  they are. *Settings → Delete everything* wipes the whole database — and, when a calendar is
  connected for calendar sync, first removes Ordnung's events from it and the app password from your
  system's password store (if that can't be done, nothing is deleted and Ordnung says what to do; when
  another of your computers sends to the same calendar through hand-off sync, the events stay there and
  only this computer's connection goes).
  Encrypted backups you made earlier are files of your own: they still hold what was in Ordnung
  when you made them, deleted letters included, until you delete them. With [hand-off
  sync](#hand-off-sync-between-your-computers-optional) on, a deleted letter's encrypted files leave the
  sync folder once nothing refers to them for 7 days (of Ordnung's clock and of its running time); your
  sync tool's version history or trash may keep them longer — empty it there too. A kept copy holds what it
  saved until you delete it. *Delete everything* takes this computer out of sync first; your other
  computers and the sync folder keep what they have.
- **Proof of sending stays private** — a receipt, delivery record, fax report or saved e-mail you
  add to a sent letter is stored like any upload with *Keep private — no AI* on: it is never sent to
  Claude, not even when you ask about the letter, and it isn't listed among your letters. One
  exception is said when it happens: a file that was already in Ordnung (the same bytes, e.g. you
  first added it to your Inbox) is linked as it is — made private then if it was never given to Claude,
  and otherwise Ordnung tells you it was given to Claude instead of calling it private (one still waiting
  from your watched folder is kept private then, so *Read these* never sends it; and a proof never
  waits again — *Undo "Keep private"* skips it, also for the e-mail it came attached to). A sent e-mail
  kept as proof is one file: its attachments never become letters, and the ones it brought while it
  waited in your Inbox (never read) are deleted when it becomes proof — the e-mail keeps them. "Given to Claude"
  counts every time a model had it, also when reading it failed or paused afterwards, and also
  when you switched *Keep private* on later. Its kind, day and note are what you chose — Ordnung
  doesn't read them from the file. The *Nachweis* PDF is made on your computer from the letter and
  these files. Removing a proof deletes its file for good (unless another proof uses it) — the
  confirmation names the file and offers to download it first, as a photographed receipt may be
  your only copy; deleting the letter deletes its proofs too, unless you choose to keep the files. Tracking numbers are checked on your computer; Ordnung never asks a tracking website. The
  name, e-mail and phone the letter showed when you marked it sent are kept with it, so its PDF shows
  what went out.
- **Call notes** — what you note about a phone call is kept as you typed it; no AI reads it.
- **How it was read** — each letter's page shows how it was read: every step, what Claude was
  asked (the prompt's name and version, tokens, API-equivalent cost), what code checked and what was
  filed. Only the steps' numbers, codes and the ids of what they found are kept — never the letter's
  text; the names shown are looked up when you open it. *Download a copy of your records* includes
  these traces. `ordnung trace <letter id> --otel` writes one reading as OpenTelemetry JSON for a
  tracing tool: no letter text, titles or names, and every id replaced by a code made for that file
  (Ordnung's own ids are hashes of a file, a sender's name or a sentence, so they could confirm a
  guess). It still shows the dates Ordnung computed and the letter's dates they came from, the rules
  that computed them (their public names, such as `zpo_692`), the holiday calendar each date used (a Bundesland's, or nationwide), how many pages, quotes and to-dos there were, match scores, and the
  prompts' versions and models — look it over before you share it.
- **A letter deleted while it is being read** — if a call to Claude about it is still under way,
  its answer is not cached and the usage log keeps only the anonymous numbers, as for a letter
  deleted afterwards.
- **Model** — choose the Claude model every call runs on (Settings → Claude connection; Sonnet 5 unless you
  change it). The demo and the benchmarks keep the model they were recorded with.
- **Export letters** — Settings → Data → *Export letters* (or *Export these letters…* on a tax year) saves
  your letters' original files as one ZIP, in folders by year and sender, with a list of them
  (`index.csv`) for a spreadsheet. It runs only when you click it, on the computer — a paired phone can't
  export — and it leaves the computer only as the ZIP you save: Ordnung writes nothing for it, sends nothing
  and keeps no copy. The ZIP isn't encrypted: anyone who has it can read the letters, so keep it safe and
  share it only with people you trust, like your tax adviser. Letters you kept private are in it too;
  letters you wrote in Ordnung aren't (download each one's PDF under Letters).
- **Nothing is sent or paid automatically** — Ordnung drafts letters and suggests actions; you send
  them yourself. A GiroCode only pre-fills your banking app; you check and confirm the transfer
  there. (Two things keep themselves current, each only after you turn it on: calendar sync updates
  Ordnung's own events in the calendar you connected, and hand-off sync keeps the encrypted copy in your
  sync folder up to date — see below.)
- **Signed in on this computer** — Ordnung's sign-in cookie is named after its port, so the demo and
  your own Ordnung on another port keep separate sign-ins. Browsers don't keep cookies apart by port,
  though: while you're signed in, your browser also sends Ordnung's sign-in cookie to other programs on
  this computer that serve pages on localhost, on any port. On a shared computer, only open local web
  pages you trust while Ordnung is open.
- **Signed in on your phone** — a paired phone signs in with a cookie of its own that only that
  phone's browser holds, never your computer's session token. It works only from your home network,
  changes by itself at most once an hour, and stops working the moment you remove the phone in
  Settings → Phone on your computer. Ordnung keeps only a hash of it. Cookies ignore ports here too: if
  that phone opens another HTTPS service on your computer's address, its browser sends the cookie along.

## GiroCode (payment QR codes)

The QR code in a Pay panel is made on your computer: the Ordnung server writes its text (payee,
IBAN, amount, reference — the details the panel shows anyway) and the web app draws the code with a
library bundled into the app. No online QR service is ever asked, nothing about the code is sent to
Claude or anywhere else, and the code is not stored — it is worked out again each time you open a
letter. When you confirm "These match the letter", the details you compared are written to the
activity log in your database (they are what the letter says), so the code stays unlocked until the
letter is read differently; deleting the letter deletes that entry too (also when you deleted the
to-do first). Scanning the code hands its
text to your banking app on your phone, like typing it would. On a [paired phone](#phone-access-optional),
which can't scan its own screen, the block offers to copy the details or to save the code as a picture
that many banking apps can read: the picture is drawn on the phone, shared with your banking app or
saved on the phone, and stays in your Photos until you delete it.

## The watched folder

In *Settings → Watched folder* you can point Ordnung at a folder your scanner or phone app saves
into — best a folder just for letters. It is off until you choose one.

- **Nothing is sent until you say so.** A new file is copied into Ordnung's data folder like an
  upload and read on this computer only (its text layer, for search and the page images; an e-mail is
  named by its subject and sender) — then it waits. *Read these* sends it to Claude like any letter you
  add; *Keep private* keeps it as if you had added it with "Keep private — no AI". Waiting letters are
  private in every other way too: *Ask*, *Weekly Ideas*, the daily note and drafting never see them.
  Today tells you they wait (it can't know their dates), and so does the Inbox's count.
- **"Read new files with Claude straight away"** skips the waiting for files that **arrive** in the
  folder from then on: each one is sent to Claude as soon as it appears. The files that were already in
  the folder when you chose it always wait — choosing a busy folder like *Downloads* never sends what
  is already there, also when you choose it again after *Stop watching* (what landed in it meanwhile
  waits too) — and so do files already waiting: a copy of a waiting file arriving in the folder
  never answers for it. Only you do, by choosing *Read* or *Keep private*, or by adding the same file by
  hand.
- **Ordnung's own drafts are not letters you received.** A letter Ordnung drafted for you (with your
  address and IBAN from the profile), or a sent letter's *Nachweis*, that you download into the watched
  folder is recognised and not added — nor when it comes attached to an e-mail (the one you sent it
  with, saved into the folder) — so it is never sent to Claude that way.
- **A cloud-synced folder is already shared with its cloud provider.** If the folder is inside
  Dropbox, iCloud Drive, OneDrive or Google Drive, that provider has copies of every file in it,
  whatever Ordnung does. Choose a folder on this computer only (for example Ordnung's own inbox
  folder, offered in Settings) if that matters to you.
- **Read-only.** Ordnung only lists and reads the folder: it never writes, moves, renames or deletes
  anything there, never follows a symbolic link, never enters a sub-folder, and ignores partial and
  temporary files.
- **What Ordnung remembers.** To pick up each file once, it keeps a hash of the folder, the file's
  name, size and date — not the name itself — while the file is in the folder, and the fingerprints
  (SHA-256) of the drafts and *Nachweis* PDFs it made for you. The activity log lists the files the folder brought in;
  deleting a letter removes those entries with it, while the name of a file the folder refused (too
  large, damaged, not readable) stays in the log until *Delete everything*. A folder with more than
  5,000 files Ordnung could read is not watched.
- ***Delete everything*** stops watching and clears the setting. Files in a folder you chose are never
  touched; Ordnung's own inbox folder lives inside its data folder and is deleted with it — every file
  in it, even ones Ordnung couldn't add (the Delete-everything dialog says so).

E-mails in the folder wait with their attachments, and *Read these* for an e-mail reads what it
brought as well. Pictures inside an e-mail (logos, tracking pixels, banners) are never read — a photo
of a letter pasted into an e-mail is read like an attached one — and nothing in an e-mail is ever
fetched from the internet.

## Searchable scans

Many scanners and phone apps save a "searchable PDF": a picture of the page with the scanner's own reading
of it as hidden text. That text is somebody's reading of the picture, not the letter's words, so it is never
a page's text: when Claude reads a scan, it reads the picture, and what it read is compared with the paper
([ADR 0012](decisions/0012-girocode-only-for-grounded-transfers.md)). The decision is in
[ADR 0020](decisions/0020-a-scanner-s-text-is-for-finding-not-reading.md).

- **Kept only for search.** The scanner's text is in `<data dir>/derived/<letter>/scan-text.json`, kept with
  the letter's page images (so also in backups and hand-off sync), only for search. Your letter search counts
  it on the pages that have no text of their own — a scan you kept private, one waiting from your watched
  folder or for Claude — and a letter found only that way says *Found in your scanner's text — not checked*.
- **Never shown, checked or sent.** It is never shown as the letter's words (search shows no snippet of
  it), never used to check a date or an amount, and never sent to Claude: *Ask*, *Weekly Ideas*, the daily
  note and drafting never read it, and it is not in the search index *Ask* uses. The letter's page says
  what it is kept for.
- **It goes with the letter.** Once Claude has read a page of the scan, that page's scanner text is removed
  (the file goes once every page is read); deleting the letter deletes it with the page images. A scan stored before Ordnung kept this text gets it
  in the background, read from the original by Ordnung's own code (no model).

## Reminders while Ordnung is closed

- **The morning desktop notification** (Settings → Reminders; off until you switch it on) is written
  by Ordnung's own code from the day's agenda — no model call, nothing sent anywhere — and shown by
  your system's notification tool (`notify-send`, macOS notifications, Windows toasts). A
  notification can be seen on a lock screen, a shared screen or in the system's notification
  history, so the app switches it on as **Discreet**: "Ordnung — 1 due today · 2 more this week",
  never a title, a name, an organisation or an amount. **With details** shows the first three things with
  their amounts and days; choose it only on a screen nobody else sees. Letters with scam signs are
  never in it. The activity log notes that it was sent to the system, with the count only. (That
  is all Ordnung can know: the system may still keep it back — on macOS until notifications are
  allowed for Script Editor, and under Focus or Do not disturb; Settings says where to look.)
- **Start at login** (`ordnung autostart enable`) writes one file that starts `ordnung serve` when you
  log in (a systemd user service, a LaunchAgent or a Startup-folder entry), and prints it before
  anything else. The server's sign-in link carries the session token, so the service throws away
  what `serve` prints: the token never lands in the system journal or a log file.
  It also records `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` when that is set (see Hardening below).
  `ordnung autostart disable` removes the file.

## Calendar sync (optional)

Settings → Calendar → *Sync with your own calendar* puts your dates into a calendar you already use,
so your phone reminds you. It is off until you connect a calendar, and it **sends event text to a
third party** — your calendar provider — so:

- **Discreet by default.** The events keep their date, time and alarms, and are titled "Ordnung:
  deadline" (or "… payment", "… appointment", "… money in") with a note to look in Ordnung — no
  letter's title, no name or organisation, no amount, no place. A date Ordnung couldn't confirm in
  the letter says "— check the date" (that reveals nothing private). *With details* sends what Ordnung's calendar file
  holds (the title, what to do, the amount, who it is with, why that date); choose it only if you
  are comfortable with your provider storing it. Settings shows every event exactly as it would be
  sent, in either mode, before you connect.
- **Your app password stays in your system's password store** (Keychain, Credential Locker, GNOME
  Keyring / KWallet), never in Ordnung's database, a log or a backup. A "password store" that
  doesn't keep it safely — Python keyring's `null` backend, or the plain-text and home-made files of
  `keyrings.alt` — is refused, not used. Ordnung reads the password only to connect, to send a change,
  to check once a day that its events are still in the calendar, and to disconnect — opening
  Settings never reads it, so it doesn't ask a locked keyring to unlock. Use an app password
  from your provider, not your main password. Ordnung talks to the calendar only over `https://`
  (or plain `http://` to a server on this computer) and checks its certificate.
- **Only Ordnung's own events.** Ordnung adds, updates and removes the events it created, and never
  reads or changes anything else in that calendar — a calendar of its own, named "Ordnung", keeps
  things tidy. Once a day (and on *Sync now*) it asks the server which of *its own* events are still
  there, by name, and puts back any that went missing. Disconnecting forgets the password and can
  remove Ordnung's events first; "Delete everything" removes them (and forgets the password) before it
  deletes anything — unless another of your computers sends to the same calendar through hand-off sync:
  then the events stay for that computer to keep current.
- **When.** When you connect, when you press *Sync now*, and every 15 minutes while `ordnung serve`
  runs — only what changed is sent. The activity log notes each sync that sent or removed events.
- **A restored backup doesn't take over the calendar.** The backup holds the calendar's address and
  mode, never the password. A restored copy starts with calendar sync waiting: it sends, changes and
  removes nothing, and never touches the password the original Ordnung keeps on the same computer,
  until you enter the app password in it. If the Ordnung the backup came from still syncs to that
  calendar, disconnect it there first — two copies would change each other's events.
- **Discreet events don't say what kind of date they are.** An event's name in the calendar and its
  UID are a keyed hash (the key stays in your data folder, and a backup carries it), not the to-do's or
  contract's id, which would tell a cancellation deadline from a payment.

## Phone access (optional)

Settings → Phone on your computer lets a phone use Ordnung in its browser over your home Wi-Fi. Your
letters stay on the computer: the phone shows them, and adds to them, while the computer is on and
Ordnung runs. Phone access is off until you turn it on, never available in the demo, and can't be turned
on while Ordnung runs without its session token (`--no-token`). The policy is in
`ordnung/phone/__init__.py`, the decision in [ADR 0017](decisions/0017-phone-access-over-the-home-network.md).

- **What a phone can do.** Look at everything the everyday pages show, add letters (photos or files)
  and to-dos, write letters, answer Ideas, ask, and correct or tick off what exists. It can't delete
  anything, download originals, letter PDFs, the calendar file or your records, export your letters,
  change settings, your profile, phone access, calendar sync, the watched folder or backups, decide
  about letters waiting from your watched folder, let Claude read a letter you kept private, or start
  the weekly Ideas. The exact list is checked before a request reaches the rest of Ordnung, and anything
  not on it is refused.
- **Your letters stay on the computer.** Photos taken on the phone go straight to the computer, every
  answer the phone gets is marked not to be stored, and the phone keeps no copy. On the phone, *My
  numbers* and your profile's IBAN show only their last 4 characters ([above](#my-numbers)). A letter
  shows what is printed on it, though — also a letter you write: one that asks for money back on your
  account (such as the deposit return) carries your IBAN in full, on the phone too. A single
  photo is kept on the computer as the phone sent it, with what the camera wrote into it (the time, and
  the place if the camera records it); Claude only ever sees the page image Ordnung makes from it.
- **Home network only.** Phone access listens on one address of your computer on your home network and
  answers only devices on that network — never through a VPN or a tunnel, nor through a container's or a
  virtual machine's network unless your router is on it (as with Hyper-V's external switch). Nothing goes
  over the internet; there is no relay. When Ordnung can read your router's identity (not every system lets
  it) and your computer wakes up on another network that gives it the same address — many routers use the
  same addresses — phone access pauses until you choose *This is my home network*. When your computer's
  address changes, phone access pauses too; moving it to the new address means pairing every phone again.
  Reserving the address in your router avoids that (on a FRITZ!Box: Heimnetz → Netzwerk → the computer →
  "Diesem Netzwerkgerät immer die gleiche IPv4-Adresse zuweisen").
- **Pairing.** *Pair a phone* shows a QR code whose address carries a one-time code after its `#`, the
  part of an address a browser never sends to a server, so no log or link preview sees it. The code has 10
  characters, works once, for 10 minutes, and closing the dialog cancels it. A wrong, expired or missing
  code all get the same answer. One device gets 5 wrong tries for a code and is then locked out of it; 100
  wrong tries from your network cancel the code, and Settings lists the addresses they came from. A code
  used twice means two devices had it — someone may have seen your screen — so neither stays paired, and
  Settings says so. Each new phone appears on your computer at once, with the address it paired from and
  two check words its own screen shows too ("amber tulip"): a phone showing other words isn't yours. Pair
  where nobody else can see your screen.
- **The certificate.** The connection is HTTPS with a certificate Ordnung makes on your computer: no
  company vouches for it, so the phone warns once that the connection isn't private. Settings shows the
  certificate's fingerprint, so you can check that it is your computer answering. Its names say nothing
  about you or Ordnung ("Home network certificate 7K3M"): anyone on your network who connects sees them.
  It lasts 397 days and is renewed by itself; a phone that clicked through the warning warns once more
  then. The certificates and their keys are in `<data dir>/phone/`, private to your account like the
  rest of the data folder and never in the database or a backup. The keys are not encrypted — whoever can
  read your data folder can read your letters anyway — and the authority's key can vouch for your
  computer's one address only (below).
- **Stopping the warning (optional).** On an iPhone or iPad, or an Android phone in Chrome, the phone's
  Settings page offers to trust the authority that issues the certificate. The phone then opens Ordnung
  without a warning — and **if it ever warns again, someone else is answering: don't continue**. The
  authority can vouch for your computer's one address only, never for your router, another device or a
  website — even for someone who copies its key from a backup of your computer's disk. A new address
  makes a new authority: install the new one and remove the old. Remove it from the phone, too, after
  *Start over*, *Delete everything* or removing the phone; the phone's Settings page has the steps. Other
  phones aren't offered this step and warn once per certificate. Whether each phone really keeps the
  authority to that one address is still to be checked on real devices.
- **Signed in.** A paired phone gets a sign-in of its own in a cookie only its browser holds; Ordnung
  keeps only a hash of it. It works only on your home network, and changes by itself at most once an
  hour: an old one used again means it was copied, so that phone is signed out, and Settings and the
  phone say why. *Remove* in Settings → Phone signs a phone out at once: what it was sending still
  arrives, except an upload still on its way (one that had arrived is filed, and the phone is told so).
  Turning phone access off does the same, and the phone is told phone access stopped, not that it was
  removed. A phone not used for 30 days is forgotten; pairing again is one scan. It is refused when it
  comes back after that, even right after Ordnung or phone access starts again. At most 10 phones can be
  paired.
- **Claude from the phone.** A phone uses Claude as your computer does — reading a letter it
  photographed, *Ask*, writing a letter — through your account on the computer, and the usage log shows
  it. Each phone may ask 30 questions, start 20 other things that ask Claude and add 30 letters an hour
  (each letter of an upload counts; photos of one letter count once).
- **What is logged.** The privacy log notes turning phone access on and off, pausing and resuming it,
  pairing and removing a phone (and why: by you, unused, a new address, starting over, a code or sign-in
  used twice), cancelled codes and new certificates. Everything a phone changes says so ("Changed a
  to-do on Anna's iPhone"; a letter it added comes "from your phone"), the log can be filtered by phone,
  and the Remove dialog counts a phone's changes of the last 30 days. What a phone only looks at isn't
  logged; Settings shows when and from which address each phone was last used. Codes, sign-ins and
  cookies are never logged.
- **The firewall.** Your computer's firewall may ask whether Python may accept connections. On macOS
  that rule is for the Python program Ordnung runs with. On Windows, make your Wi-Fi a private network
  first and allow private networks only, never public. The pairing dialog's *Phone can't connect?* shows
  the narrowest rule for Windows and for `ufw` on Linux: only this address and port, only from your home
  network.
- **Start over, Delete everything and backups.** *Start over* turns phone access off, removes every
  phone and deletes the certificates. *Delete everything* stops phone access first and removes it with
  everything else. Backups never carry phone access — no certificates, no paired phones — and a restored
  copy starts with it off ([below](#encrypted-backups)).

## Hand-off sync between your computers (optional)

Settings → Your computers lets you use the same Ordnung on your laptop and your desktop, one at a time,
through a folder your own sync tool already keeps in step (Nextcloud, Syncthing, Dropbox, iCloud Drive, a
network drive). It is off until you set it up, never available in the demo, and needs this computer's
password store. The policy is in `ordnung/sync/__init__.py`, the decision in
[ADR 0018](decisions/0018-hand-off-sync-through-a-folder-you-already-sync.md).

- **One computer at a time.** The computer in use saves an encrypted copy into the folder about 2 seconds
  after a change of yours, 10 seconds after Ordnung's own work (a reading, the day changing), at the latest
  60 seconds after the first change not yet saved, and again when Ordnung stops. Your other computers are
  *standing by*: they change nothing — every change there, a paired phone's too, is refused until you
  choose *Use Ordnung here* — and they read no letters, send no reminders and update no calendar. *Use Ordnung here* brings everything over once your sync tool has delivered it; the computer
  that was in use switches to standing by when its sync tool tells it.
- **Only ciphertext goes into the folder.** Every file there is encrypted with AES-256-GCM, under keys that
  come from a random key your passphrase locks (scrypt, N = 2^18, r = 8: 256 MiB of memory to try one
  passphrase); its name is a keyed hash, its size is rounded up (by at most 12 %, to at least 4 KiB), and
  the key file is 92 bytes with nothing readable in it. Not one byte in the folder is plain text: no name,
  date, sender, file type, the word "Ordnung" or a computer's name.
- **What your sync provider can see** — anyone with the folder but not the passphrase: that it is an
  encrypted store, and the name you gave its folder (Ordnung suggests a neutral one, "Vault": a folder
  called "Ordnung" would tell them which app wrote it — and someone who knows Ordnung's open format can
  recognise its layout anyway: a 92-byte key file, `h/` and `o/`); how many files there are and roughly
  how large; how many computers take part (one file each); when things change; and from bursts of new
  files, roughly how many letters and pages you add. Never
  your letters' content, their names, senders or dates, or which file is which, and a file it already
  knows can't be recognised in the folder (the names are keyed). Its version history and trash may keep
  old encrypted files after Ordnung has removed them.
- **The passphrase stays in each computer's password store.** You type it once on each computer, and
  Ordnung keeps it in the system's password store (service "Ordnung sync", an account for this data
  folder) — never in the folder, its database, `sync/state.json`, a log, a backup or an answer. Opening
  Settings never reads it; it is read when Ordnung needs the folder's keys (at start, or after you typed it
  again), to write a kept copy, and when you set sync up. A password store that doesn't keep it safely is
  refused, as for calendar sync, and there is no file to fall back on. A new sync folder's passphrase must
  reach about 70 bits by Ordnung's estimate — five unrelated words, like the five-word one Settings
  suggests, or a password manager's random password with capital and small letters — because the key
  file sits at your provider for years, open to guessing offline (and at least 12 characters, as for
  backups). Without it nobody can open the folder: not your sync provider, not Ordnung's makers, not
  you. Changing it isn't possible yet; a new sync folder with a new passphrase is.
- **What stays on each computer.** Only your ledger and your letters' files travel. Never: phone access and
  the paired phones; the calendar connection and its app password (connect calendar sync on each computer;
  which events were already sent travels, so nothing is sent twice); the watched folder, its path and what
  it remembers (only a fingerprint of each file it brought in travels, so a folder both computers watch
  never brings back a letter you deleted); Claude's pause; the morning notification's bookkeeping; the
  lock and the running server's session file; and the privacy-log entries of a backup made or restored on
  that computer, of its phone access and of its watched folder — they name local addresses and paths.
- **When both computers changed something.** Nothing is merged and nothing is thrown away: Ordnung asks
  once which computer's Ordnung to keep, and the other one is saved on its own computer as a *kept copy*
  before anything there is replaced. Work a computer did by itself (a reading finished after you closed
  the lid, the day changing) never makes it ask; a reading cut off that way is done again on the computer
  in use, so its Claude tokens are spent twice.
- **Kept copies** are encrypted backups — the sync passphrase opens them with `ordnung restore` — written to
  `<data dir>/sync/kept/` before this computer's data is replaced. They stay on this computer, are never
  synced or deleted by themselves (Settings warns once they take more than 2 GiB), and are lost with this
  computer's disk and with *Delete everything*.
- **Nothing half-arrived is used.** A version is brought over only once every file of it has arrived and
  passed its check: a file still arriving or cut short, an online-only placeholder (iCloud Drive's
  "Optimise storage", online-only files in Dropbox or OneDrive) and a file that can't be read all count as
  "not arrived yet", and Settings says what is still on its way. Keep the folder available offline on every
  computer.
- **A copied or restored data folder.** A data folder moved or copied to another computer pauses sync
  until you say *This is the same computer* or *Set up as a new computer*. One put back from an operating
  system's backup is never taken for new changes: Ordnung keeps it as a kept copy and brings back what it
  last saved.
- **Forgetting a lost computer** (Settings → Your computers) removes it from the folder's list, after a
  kept copy of any changes only it had. It doesn't lock that computer out — it still knows the passphrase.
  To shut out a lost or stolen computer, set up a new sync folder with a new passphrase
  ([what else to do](#if-your-computer-is-lost-or-stolen)).
- **What is logged.** The privacy log notes starting and stopping sync, joining, each switch ("Ordnung moved
  here from desktop (3 new letters)"), a late change brought in, a choice, a kept copy and a computer
  forgotten; only the computer in use writes it, and the entries travel with your data. Routine saves are
  not logged: Settings says when the last one was.
- **Disconnect, Delete everything and backups.** Disconnecting saves what isn't saved yet and leaves the
  folder and your other computers with everything (kept copies stay). *Delete everything* does the same
  first, then deletes `sync/` with the kept copies and the passphrase from this computer's password store;
  when another of your computers sends to the same calendar, Ordnung's events stay there. While no other
  computer has received this one's latest changes, both ask a second time. Backups never carry sync, so a
  restored copy starts without it.
- **Tested** with a simulated sync tool (files late, out of order, in pieces, conflict copies, online-only
  placeholders) and two data folders on one machine. A pass with a real Nextcloud, Syncthing or iCloud Drive
  folder on two physical computers is still to be done.

## Encrypted backups

`ordnung backup` (and Settings → Data → *Download encrypted backup*) makes one file with everything
Ordnung keeps: the database (letters' text and what was read from them, to-dos, contracts, drafts,
your *Ask* conversations, the usage log and cached model answers), your original files, the page
images (with the text a scanner added to a scan) and the letter PDFs. Not in it: the watched folder
(those files are your own; what Ordnung took from them is), the lock, the running server's session file,
phone access — neither its certificates nor the paired phones (they are taken out of the backup's copy of
the database) — and hand-off sync's state (its folder, the computers, the kept copies; the passphrase never was in the data
folder): a restored copy starts without sync.

- **Encrypted before it is written.** AES-256-GCM in authenticated chunks, the key derived from your
  passphrase with scrypt (N = 2¹⁸, r = 8: 256 MiB of memory to try one passphrase, as for a sync folder);
  the file starts with a versioned header and nothing else in plain text. Backups made with the earlier
  setting (N = 2¹⁷) still open: the header says which was used. A backup file someone hands you can't make
  restoring use more than 256 MiB of memory for the key. The database snapshot is made in memory, so no
  unencrypted copy is written to disk.
- **Your passphrase stays yours.** At least 12 characters and about 70 bits by Ordnung's estimate — five
  unrelated words, like the five-word one Ordnung suggests — the rule of a new sync folder, because a
  backup on another drive or in the cloud can be copied and guessed at offline for years. A password
  manager's random password counts by the characters it uses, unless it shows a pattern people make (a
  word and a year, a keyboard walk); one Ordnung 0.1.0 suggested still counts as strong, and one a script
  gives in `ORDNUNG_BACKUP_PASSPHRASE` that falls short gets a warning, so a scheduled backup is still
  made. Ordnung never stores or logs it and can't recover it — without it the backup can't be opened, by
  anyone. In the browser the passphrase goes only to the Ordnung on this computer (in the request body,
  never in a web address).
- **Restoring checks everything.** `ordnung restore` refuses a wrong passphrase, a file that was
  changed, cut short or reordered, a newer format, and anything in the archive Ordnung never writes;
  every file must match the backup's own list of hashes and row counts. It never replaces a data
  folder that holds data unless you add `--force`, and then moves the old folder aside instead of
  deleting it. `ordnung restore FILE --check` verifies a backup without restoring anything.
- **Ordnung notes each backup, and says when it's time for a new one.** Settings → Data says when the last
  one was made: from Settings, from `ordnung backup` (a scheduled one too), or the one a restored copy came
  from. When it is more than 30 days old, or there is none, the weekly review ends by saying so, and
  `ordnung doctor` warns. A backup from Settings counts once your browser has received it, also if you then
  cancel saving the file. While hand-off sync is connected, its copy in your sync folder counts too: it
  counts because your sync tool copies that folder off this computer, and Ordnung can't check that it does.
  Kept copies don't (they are on this disk), nor do Time Machine, File History or other backups of the whole
  computer: Ordnung can't see them. Backups made with `ordnung backup` before Ordnung noted them have no
  note, so they don't count. The note is a privacy-log entry that stays on this computer, and the
  reminder is Ordnung's own words, never sent to Claude. Nothing is backed up by itself.
- **A restored copy doesn't take over the watched folder.** The backup remembers which files of your
  watched folder were already there and which were picked up — on the computer it came from. A folder
  with the same path on another computer (the same `~/Downloads`) holds other files, so the restored
  copy forgets both: the files in the folder wait unread, and "Read new files with Claude straight
  away" is off until you turn it on again in Settings.
- **A restored copy doesn't take over phones.** A backup carries no phone access, and a restore
  removes it from one crafted to: the restored copy starts with phone access off and no paired phones.
- **Links are never followed — and never silently.** A folder inside the data folder that is a link
  to somewhere else (originals moved to a bigger drive) is not in the backup; `ordnung backup` and
  Settings name it before the backup is made, so you can back it up separately.

## If your computer is lost or stolen

Ordnung keeps your letters, the numbers in them (your tax ID, your IBAN) and your ledger in the data folder:
private to your account, but not encrypted by Ordnung. What a lost laptop costs you depends on two things
you set up before: a copy kept somewhere else, and an encrypted disk.

**Before:**

- **Back up** to another drive or to the cloud, and keep the passphrase in your password manager. A
  scheduled `ordnung backup` with `ORDNUNG_BACKUP_PASSPHRASE` keeps the copy current; Settings → Data and
  the weekly review say when the last one is more than 30 days old.
- **Encrypt the disk.** On a Mac, turn on FileVault (System Settings → Privacy & Security → FileVault). On
  Windows, turn on BitLocker, or Device encryption on Windows Home: Settings → Privacy & security → Device
  encryption, or BitLocker Drive Encryption in the Control Panel. On Linux, disk encryption (LUKS) is
  usually chosen when the system is installed. On a Mac and on Linux, `ordnung doctor` (and *Run check* in
  Settings) says what it found, as a best effort; on Windows it doesn't check, so look yourself.

**After**, from another computer:

1. **Get your letters back.** Install Ordnung on the new computer and run `ordnung restore FILE` with your
   newest backup. The restored copy starts without phone access, hand-off sync or the calendar's password,
   and notes which backup it came from. With hand-off sync, your other computer already has everything:
   choose *Use Ordnung here* there.
2. **Shut the lost computer out of hand-off sync.** *Forget* only takes it off the list: it still knows the
   passphrase. On the computer you use now, disconnect and set up a new sync folder with a new passphrase
   (Settings → Your computers); disconnect your other computers too and connect them to the new folder. Then
   delete the old folder, and its version history at your provider.
3. **Sign the lost computer out of Claude.** Claude Code on it stays signed in to your Claude account.
   Anthropic's help pages say how to sign out everywhere and remove Claude Code's sign-in
   ([How do I log out of all active sessions?](https://support.claude.com/en/articles/10310342-how-do-i-log-out-of-all-active-sessions)),
   and how to end one device's session
   ([Managing your active sessions](https://support.claude.com/en/articles/13124001-managing-your-active-sessions)).
   If Claude Code used an API key, revoke that key in the Claude Console.
4. **Your phones.** The restored copy has no paired phones. On a phone that trusts Ordnung's certificate
   authority (the optional step that stops the warning), remove it: the lost computer holds its key. Then
   pair the phone again from the new computer.
5. **Calendar sync.** Revoke the app password at your calendar provider (it was in the lost computer's
   password store), then connect again with a new one.
6. **If the disk wasn't encrypted,** whoever has it can read your letters, your IBAN and tax ID among them.
   Watch your account for direct debits you didn't agree to and tell your bank — it can take them back.

## Hardening built into every model call

- The document is passed to the CLI over **stdin** (never the command line, so it doesn't appear in
  `ps`), and **no tools** are enabled while reading documents — the model can only answer.
- `--setting-sources ""` and `--strict-mcp-config` keep your own Claude Code hooks, settings and MCP
  servers out of Ordnung's calls; `--no-session-persistence` keeps them out of your Claude history.
- Ordnung runs your own Claude Code CLI, so Claude Code's own telemetry and error reporting apply to its
  calls as they do when you use Claude Code yourself. Set `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` in
  the environment you start Ordnung from to turn them off. With start at login, set it before
  `ordnung autostart enable`, or run that again after setting it.
- Document text is treated as **untrusted**: it is wrapped in `<untrusted_document>` markers, hidden
  (invisible) text — white, tiny, off the page, or drawn invisibly (a PDF's text render mode 3) — is
  removed before it reaches the model (a scan's invisible OCR layer never reaches the model: the page is
  read from its picture, and what was read from it is compared with the paper; the OCR text is kept only for
  your letter search, [above](#searchable-scans)), and every extracted fact is checked against the page
  before it is shown as "found in the letter".
- *Ask* can only call Ordnung's **read-only** ledger tools; there are no write tools for a
  prompt-injected document to abuse, and no date calculator: the rules tools other clients can install
  are not on Ask's server ([ADR 0011](decisions/0011-ask-keeps-to-the-ledger.md)).
- *Ask*'s tool results (search snippets, summaries, quotes, page texts) reach the model inside
  `<untrusted_document>` markers too, apart from Ordnung's own record of dates and amounts; a
  date, time or amount of an answer that is not in Ordnung's record of what its sentence cites is shown
  only as a placeholder ("[date only in the letter]", "[date left out]") — except a cited to-do's or
  contract's own amount that Ordnung could not verify, which stays in quotation marks as the letter's,
  not confirmed — and no word of an answer is shown before that check; the tool trace shown meanwhile
  names the words the model searched for without any date, time or amount the check reads in them
  ([ADR 0008](decisions/0008-two-channels-and-claim-level-citations.md)). Text an HTML e-mail certainly hides from every reader (inline
  `display:none`, `visibility:hidden`, `opacity:0`, a font of at most 1 px, zero-height clipped or
  far off-screen boxes, text in its own inline background colour, simple hiding classes) is kept from
  the model like hidden text in PDFs. When that isn't certain (media queries, Outlook-only parts,
  responsive and dark-mode copies, stylesheet colours) the text stays visible and the other defences
  apply; see [ADR 0007](decisions/0007-short-written-policies-over-growing-heuristics.md).
- Uploads are checked before anything decodes them: PDFs whose compressed streams expand too far (an
  edit-protected PDF's measured decrypted), photos with too many pixels and texts over 60 pages are
  refused, so a hostile file can't exhaust your computer's memory or keep the check busy for minutes. A PDF whose protection or structure
  can't be checked this way is refused, with the hint to print it to a new PDF. A refused file leaves
  nothing behind, and a PDF whose objects refer to themselves can't hang the reading of its text: its
  pages are read from their images instead.
- The local web server listens on `127.0.0.1` and answers only requests addressed to this computer
  (`localhost` or `127.0.0.1`), and requires a session token, same-origin
  requests and a custom header for any change (CSRF/DNS-rebinding protection), with a strict
  Content-Security-Policy. `ordnung serve` opens your browser through a private local page, so the
  token never appears on a command line other accounts could see.
- Phone access's listener, while it is on, has checks of its own: HTTPS only, exactly
  `https://<address>:<port>` as the address asked for (no names, so DNS rebinding fails), only devices
  in your home network's subnet, `Origin` required on every change and Fetch-Metadata checked, no
  `.`, `..`, `//` or `\` in a path, no body without a stated length, and every body counted as it
  arrives. Before a phone is paired it answers only the pairing page, the app's own files and a pairing
  request of at most 1 KiB; afterwards only what the phone's allow-list names. It takes at most 128
  connections at once, and logs refusals as counts — never a code, sign-in or cookie
  ([ADR 0017](decisions/0017-phone-access-over-the-home-network.md)).

## Using Ordnung from Claude Desktop or Claude Code

`ordnung mcp install` can add Ordnung's MCP server to another Claude client. What that client can
then see depends on which server you add:

| You add | The client can see | Leaves your computer? |
|---|---|---|
| **The rules tools** (the default) | Nothing of yours. The tools open no data folder: they compute dates, holidays, working days and IBAN checks from what the client passes them (the dates and words of a letter you shared there yourself). | Only what you type or share in that client, as always |
| **The full server** (`--with-ledger`) | Your ledger, read-only, as *Ask* sees it: letters' titles, summaries, page text and quotes, to-dos, contracts, people and organisations, money, *My numbers* (your Steuer-ID, social insurance number and the like, as your letters show them), and your profile's name, language and Land. For letters you marked *Keep private — no AI* the text is withheld — also the quotes and wording behind a to-do's date — but the letter's date, the to-dos you added for it (their titles, dates and amounts, which can name the subject) and, when you linked the letter to a sender, that sender (its name and contact details, like any other person or organisation) are still listed. | Whatever Claude reads through it becomes part of that conversation, sent to Anthropic under that client's account and settings |

With the full server, **every other tool of that client can see what Claude read from your
ledger** through the model: another MCP server loaded there (web search, e-mail, files) and, in
Claude Code, its own shell and web tools could send it on, and a prompt-injected document elsewhere
could ask Claude to. Ordnung cannot control another client's tools or history. That is why
`ordnung mcp install` adds only the rules tools unless you ask for your ledger with
`--with-ledger`, and then shows this warning before it prints or writes anything. In Claude Code the
full server is added for you and the current project only (`claude mcp add --scope local`); Ordnung
never writes it into a project's `.mcp.json`, which is usually committed and shared. Neither server
can change, delete, send or pay anything.

`ordnung mcp install` prints the entry and the file it belongs in; only `--write` changes that file,
after saving a copy of it next to it, and it adds or replaces only Ordnung's own entry. The two
servers have different names (`ordnung` and `ordnung_rules`), so adding the rules tools does not
take the full server out: if the file still has it, the command says your ledger stays readable,
and `ordnung mcp install --client … --remove-ledger --write` removes that entry (backup first). To
remove Ordnung altogether, delete its entries from `mcpServers` (or restore the backup); for Claude
Code run `claude mcp remove --scope user ordnung_rules` or `claude mcp remove --scope local ordnung`
(the install command prints both).

## Demo fixtures

The repository ships recorded model outputs for the fictional sample documents so the demo runs
without tokens. The recorder refuses to record anything that is not one of those sample files, and
CI checks that fixtures only reference sample documents — your own letters can never end up in a
fixture by accident.
