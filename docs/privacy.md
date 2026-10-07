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
| Your ledger (letters, to-dos, contracts, ideas, drafts) | `<data dir>/ordnung.db` (SQLite) | Excerpts, when you use *Ask*, *Weekly Ideas* or *Letters* |
| Profile (name, address, region, the IBAN you may add for refunds) | `ordnung.db` | Name, language and region in prompts; the address and IBAN you enter here are never put into a prompt (a letter you add is read as printed, with the address in its window; letters Ordnung drafts that contain them reach Claude with placeholders, also when translated again, and get the real values back in the translation) |
| Model responses | `ordnung.db` (`llm_cache`) | — (they came from Anthropic) |
| Usage log (tokens, cost, which document, the prompt's name and version, how the answer turned out) | `ordnung.db` (`llm_calls`) — **no prompt or response bodies** | Never |
| How each letter was read (its steps: counts, scores, computed dates, ids of records) | `ordnung.db` (`trace_spans`) — **no letter text**, the newest five readings per letter | Never (unless you export one with `ordnung trace`) |
| Fonts, UI, rules engine | bundled in the package | Never (no CDN, no web fonts) |
| Encrypted backups (`ordnung backup`, Settings → Data) | wherever you save the file | Only where you put it — encrypted, so without your passphrase nobody can read it |
| The morning desktop notification | your system's notification area | Never — Ordnung writes it on this computer from your dates |
| Calendar sync (only if you connect a calendar) | the calendar you connect (Nextcloud, iCloud, mailbox.org, …); the app password in your system's password store | To that calendar's provider: dates, times and alarms (discreet, the default) — or the events' titles, what to do, amounts and who it is with (with details) |
| Phone access (only if you turn it on) | the certificates in `<data dir>/phone/`; the paired phones (their names, when and from which address they were last used, a hash of each sign-in) in `ordnung.db` | Only to phones you paired, encrypted, on your home network — they show what is on the computer and keep no copy ([below](#phone-access-optional)) |

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
| **Letters** | the related letter's title, date, summary and reference numbers, the contract's name and customer number, the letter's fixed wording (with your addresses and IBAN replaced by placeholders), the recipient's name (first line only) and your instructions — including facts you typed for a template letter, such as a defect's description. *Translate again* sends the letter's subject and text as they stand, with your profile's address and IBAN, the sender block's address, every IBAN and the addresses a template letter wrote replaced by placeholders; other text you typed into the letter yourself is sent as you wrote it |

Reading a letter can send its text more than once, never anything more: when Claude's answer doesn't fit
the form it is asked once more with the problems listed, and when its reading comes back incomplete (almost
blank, or without the deadline to object the letter's instructions state) it is asked once more for what it
left out ([ADR 0016](decisions/0016-an-incomplete-reading-is-asked-for-once-more.md)). A letter you
delete while it is being read is not sent again.

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
  Claude. It is stored, searchable by its text layer, and you can add dates by hand. A letter you
  delete while it still waits to be read is never sent either.
- **The watched folder waits for you** — files your scanner or phone app saves into the watched folder
  are stored and read on this computer only, and wait in the Inbox ("From your folder — not read
  yet") until you choose *Read these* or *Keep private* ([details](#the-watched-folder)). *Keep
  private* can be undone (the toast's *Undo*, or *Undo "Keep private"* on the letter — for an e-mail,
  its attachments kept private with it wait again too).
- **E-mail attachments follow the e-mail** — each PDF or photo attached to an e-mail you add becomes
  a letter of its own with the e-mail's choice: attachments of a private e-mail stay private, those of
  a waiting e-mail wait with it.
- **Delete means delete** — deleting a letter removes it for good: the original, page images,
  everything read from it, its to-dos and Ideas, its search-index entries, its entries in the
  activity log, quotes from it in contracts you keep, the record of how it was read, and the cached
  model responses of every call that carried it (a secretary's note or review built from several
  letters included). The usage log keeps only anonymous numbers (its calls' replay keys, which hash the
  letter's content, and their error texts, which may quote Claude's answer, are cleared too), and deleted
  database rows are overwritten rather than left behind. Originals and page images are never kept in the
  browser's cache, and deleting a letter for good or deleting everything also tells the browser to empty
  its cache. A paired phone keeps no copy either: every answer it gets is marked not to be stored, it
  can't download originals or letter PDFs, and a phone you removed is told to empty its cache and storage
  the next time it reaches Ordnung (a tab still open there shows what it last showed until it is closed).
  Contracts and letters you drafted stay, without the link to it; your *Ask* conversations stay as
  they are. *Settings → Delete everything* wipes the whole database — and, when a calendar is
  connected for calendar sync, first removes Ordnung's events from it and the app password from your
  system's password store (if that can't be done, nothing is deleted and Ordnung says what to do).
  Encrypted backups you made earlier are files of your own: they still hold what was in Ordnung
  when you made them, deleted letters included, until you delete them.
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
- **Nothing is sent or paid automatically** — Ordnung drafts letters and suggests actions; you send
  them yourself. A GiroCode only pre-fills your banking app; you check and confirm the transfer
  there. (The one thing that keeps itself current is calendar sync, and only after you
  connect a calendar: it updates Ordnung's own events there — see below.)
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
  remove Ordnung's events first; "Delete everything" always removes them (and forgets the password)
  before it deletes anything.
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
  anything, download originals, letter PDFs or your records, change settings, your profile, phone
  access, calendar sync, the watched folder or backups, decide about letters waiting from your watched
  folder, let Claude read a letter you kept private, or start the weekly Ideas. The exact list is checked
  before a request reaches the rest of Ordnung, and anything not on it is refused.
- **Your letters stay on the computer.** Photos taken on the phone go straight to the computer, every
  answer the phone gets is marked not to be stored, and the phone keeps no copy. On the phone, *My
  numbers* and your profile's IBAN show only their last 4 characters ([above](#my-numbers)). A single
  photo is kept on the computer as the phone sent it, with what the camera wrote into it (the time, and
  the place if the camera records it); Claude only ever sees the page image Ordnung makes from it.
- **Home network only.** Phone access listens on one address of your computer on your home network and
  answers only devices on that network — never through a VPN, a tunnel, a container or a virtual
  machine. Nothing goes over the internet; there is no relay. When Ordnung can read your router's
  identity (not every system lets it) and your computer wakes up on another network that gives it the
  same address — many routers use the same addresses — phone access pauses until you choose *This is my
  home network*. When your computer's address changes, phone access pauses too; moving it to the new
  address means pairing every phone again. Reserving the address in your router avoids that (on a
  FRITZ!Box: Heimnetz → Netzwerk → the computer → "Diesem Netzwerkgerät immer die gleiche IPv4-Adresse
  zuweisen").
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
  hour: an old one used again means it was copied, so that phone is signed out and Settings says why.
  *Remove* in Settings → Phone signs a phone out at once (what it was sending when you removed it, other
  than an upload, still arrives). A phone not used for 30 days is forgotten; pairing again is one scan. At
  most 10 phones can be paired.
- **Claude from the phone.** A phone uses Claude as your computer does — reading a letter it
  photographed, *Ask*, writing a letter — through your account on the computer, and the usage log shows
  it. Each phone may ask 30 questions, start 20 other things that ask Claude and send 30 uploads an hour.
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

## Encrypted backups

`ordnung backup` (and Settings → Data → *Download encrypted backup*) makes one file with everything
Ordnung keeps: the database (letters' text and what was read from them, to-dos, contracts, drafts,
your *Ask* conversations, the usage log and cached model answers), your original files, the page
images and the letter PDFs. Not in it: the watched folder (those files are your own; what Ordnung
took from them is), the lock, the running server's session file and phone access — neither its
certificates nor the paired phones (they are taken out of the backup's copy of the database).

- **Encrypted before it is written.** AES-256-GCM in authenticated chunks, the key derived from your
  passphrase with scrypt (N = 2¹⁷, r = 8); the file starts with a versioned header and nothing else
  in plain text. A backup file someone hands you can't make restoring use more than 256 MiB of
  memory for the key. The database snapshot is made in memory, so no unencrypted copy is written to disk.
- **Your passphrase stays yours.** At least 12 characters; Ordnung never stores or logs it and
  can't recover it — without it the backup can't be opened, by anyone. In the browser the
  passphrase goes only to the Ordnung on this computer (in the request body, never in a web address).
- **Restoring checks everything.** `ordnung restore` refuses a wrong passphrase, a file that was
  changed, cut short or reordered, a newer format, and anything in the archive Ordnung never writes;
  every file must match the backup's own list of hashes and row counts. It never replaces a data
  folder that holds data unless you add `--force`, and then moves the old folder aside instead of
  deleting it. `ordnung restore FILE --check` verifies a backup without restoring anything.
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
  removed before it reaches the model (a scan's invisible OCR layer is not read at all: the page is read
  from its picture, and what was read from it is compared with the paper), and every extracted fact is checked
  against the page before it is shown as "found in the letter".
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
