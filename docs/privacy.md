# Privacy & data flow

Ordnung is a **local app**. It has no server, no account, no telemetry, and it never sees your
Claude credentials. But it is not "offline AI": when Claude reads a letter, the content of that
letter is sent to Anthropic **through your own Claude account**. This page explains exactly what
goes where.

## At a glance

| Data | Where it lives | Leaves your computer? |
|---|---|---|
| Original files (PDFs, photos) | `<data dir>/files/` | Never by Ordnung itself |
| Page images, thumbnails | `<data dir>/derived/` | Only as part of a *Read* call (see below) |
| Your ledger (letters, to-dos, contracts, ideas, drafts) | `<data dir>/ordnung.db` (SQLite) | Excerpts, when you use *Ask*, *Ideas review* or *Letters* |
| Profile (name, address, region, the IBAN you may add for refunds) | `ordnung.db` | Name, language and region in prompts; the address and IBAN you enter here are never put into a prompt (a letter you add is read as printed, with the address in its window; letters Ordnung drafts that contain them reach Claude with placeholders, also when translated again, and get the real values back in the translation) |
| Model responses | `ordnung.db` (`llm_cache`) | — (they came from Anthropic) |
| Usage log (tokens, cost, which document) | `ordnung.db` (`llm_calls`) — **no prompt or response bodies** | Never |
| Fonts, UI, rules engine | bundled in the package | Never (no CDN, no web fonts) |
| Encrypted backups (`ordnung backup`, Settings → Data) | wherever you save the file | Only where you put it — encrypted, so without your passphrase nobody can read it |
| The morning desktop notification | your system's notification area | Never — Ordnung writes it on this computer from your dates |
| Calendar sync (only if you connect a calendar) | the calendar you connect (Nextcloud, iCloud, mailbox.org, …); the app password in your system's password store | To that calendar's provider: dates, times and alarms (discreet, the default) — or the events' titles, what to do, amounts and who it is with (with details) |

`<data dir>` defaults to your platform's user data folder (e.g. `~/.local/share/ordnung`,
`~/Library/Application Support/ordnung`, `%LOCALAPPDATA%\ordnung`) and can be changed with
`--data-dir` or `ORDNUNG_HOME`. On Linux and macOS the folder is private to your account (`0700`,
files `0600`), so other accounts on a shared computer can't read your letters or your ledger.

## What is sent to Claude, per feature

Every model call goes through the `claude` CLI you installed and signed in to. Anthropic's
handling of that data (retention, training use) is governed by **your** account type and settings —
see Anthropic's [consumer terms & privacy settings](https://www.anthropic.com/legal/privacy) or, if
you use an API key, the [commercial terms](https://www.anthropic.com/legal/commercial-terms).
Check your Claude privacy settings before processing sensitive documents.

| Feature | Sent to Claude | Model (default) |
|---|---|---|
| **Read a letter** — text PDFs | the page text of that document, today's date, your country and region, your name, and the names and kinds of organisations you already have (no numbers from other letters) | Sonnet |
| **Read a letter** — photos/scans | each page image (JPEG, ≤ 1600 px) for transcription, then the transcribed text as above | Sonnet |
| **Ideas review** (weekly; can be switched off in Settings) | a compact summary of open to-dos, contracts, recent letter summaries and warnings, the organisations involved, and your language, region and whether you are on a student visa | Sonnet |
| **Secretary's note** (optional) | today's agenda (titles, dates, amounts, organisations) and your first name | Haiku |
| **Ask** | your question and the last few messages of the conversation; the assistant then reads what it needs through Ordnung's **read-only** tools (search results, document excerpts) | Sonnet |
| **Letters** | the related letter's title, date, summary and reference numbers, the contract's name and customer number, the letter's fixed wording (with your addresses and IBAN replaced by placeholders), the recipient's name (first line only) and your instructions — including facts you typed for a template letter, such as a defect's description. *Translate again* sends the letter's subject and text as they stand, with your profile's address and IBAN, the sender block's address, every IBAN and the addresses a template letter wrote replaced by placeholders; other text you typed into the letter yourself is sent as you wrote it | Sonnet |

You can inspect every call in **Settings → Privacy & AI usage**: purpose, which documents, how many
pages and bytes were sent, tokens, API-equivalent cost, and whether it came from cache.

## Your controls

- **Keep private (no AI)** — every upload asks first: switch it on and the document is never sent to
  Claude. It is stored, searchable by its text layer, and you can add dates by hand. A letter you
  delete while it still waits to be read is never sent either.
- **Delete means delete** — deleting a letter removes it for good: the original, page images,
  everything read from it, its to-dos and Ideas, its search-index entries, its entries in the
  activity log, quotes from it in contracts you keep, and the cached model responses of every call
  that carried it (a secretary's note or review built from several letters included). The usage log
  keeps only anonymous numbers, and deleted database rows are overwritten rather than left behind.
  Contracts and letters you drafted stay, without the link to it; your *Ask* conversations stay as
  they are. *Settings → Delete everything* wipes the whole database — and, when a calendar is
  connected for calendar sync, first removes Ordnung's events from it and the app password from your
  system's password store (if that can't be done, nothing is deleted and Ordnung says what to do).
  Encrypted backups you made earlier are files of your own: they still hold what was in Ordnung
  when you made them, deleted letters included, until you delete them.
- **Models** — choose which Claude model handles each purpose.
- **Nothing is sent or paid automatically** — Ordnung drafts letters and suggests actions; you send
  them yourself. (The one thing that keeps itself current is calendar sync, and only after you
  connect a calendar: it updates Ordnung's own events there — see below.)

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

## Encrypted backups

`ordnung backup` (and Settings → Data → *Download encrypted backup*) makes one file with everything
Ordnung keeps: the database (letters' text and what was read from them, to-dos, contracts, drafts,
your *Ask* conversations, the usage log and cached model answers), your original files, the page
images and the letter PDFs. Not in it: the watched folder (those files are your own; what Ordnung
took from them is), the lock and the running server's session file.

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
- **Links are never followed — and never silently.** A folder inside the data folder that is a link
  to somewhere else (originals moved to a bigger drive) is not in the backup; `ordnung backup` and
  Settings name it before the backup is made, so you can back it up separately.

## Hardening built into every model call

- The document is passed to the CLI over **stdin** (never the command line, so it doesn't appear in
  `ps`), and **no tools** are enabled while reading documents — the model can only answer.
- `--setting-sources ""` and `--strict-mcp-config` keep your own Claude Code hooks, settings and MCP
  servers out of Ordnung's calls; `--no-session-persistence` keeps them out of your Claude history.
- Document text is treated as **untrusted**: it is wrapped in `<untrusted_document>` markers, hidden
  (invisible) text is removed before it reaches the model, and every extracted fact is checked
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
- Uploads are checked before anything decodes them: PDFs whose compressed streams expand too far,
  photos with too many pixels and texts over 60 pages are refused, so a hostile file can't exhaust
  your computer's memory.
- The local web server listens on `127.0.0.1` by default (another `--host` prints a warning and still
  needs the token) and requires a session token, same-origin
  requests and a custom header for any change (CSRF/DNS-rebinding protection), with a strict
  Content-Security-Policy. `ordnung serve` opens your browser through a private local page, so the
  token never appears on a command line other accounts could see.

## Using Ordnung from Claude Desktop or Claude Code

`ordnung mcp install` can add Ordnung's MCP server to another Claude client. What that client can
then see depends on which server you add:

| You add | The client can see | Leaves your computer? |
|---|---|---|
| **The rules tools** (the default) | Nothing of yours. The tools open no data folder: they compute dates, holidays, working days and IBAN checks from what the client passes them (the dates and words of a letter you shared there yourself). | Only what you type or share in that client, as always |
| **The full server** (`--with-ledger`) | Your ledger, read-only, as *Ask* sees it: letters' titles, summaries, page text and quotes, to-dos, contracts, people and organisations, money, and your profile's name, language and Land. For letters you marked *Keep private (no AI)* the text is withheld, but the letter's date and the to-dos you added for it (their titles, dates and amounts, which can name the subject) are still listed. | Whatever Claude reads through it becomes part of that conversation, sent to Anthropic under that client's account and settings |

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
