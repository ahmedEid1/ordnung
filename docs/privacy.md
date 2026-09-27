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
| Your ledger (letters, to-dos, contracts, ideas, drafts) | `<data dir>/ordnung.db` (SQLite) | Excerpts, when you use *Ask*, *Ideas review* or *Letters* |
| Profile (name, address, region, the IBAN you may add for refunds) | `ordnung.db` | Name, language and region in prompts; the address and IBAN you enter here are never put into a prompt (a letter you add is read as printed, with the address in its window; letters Ordnung drafts that contain them reach Claude with placeholders, also when translated again, and get the real values back in the translation) |
| Model responses | `ordnung.db` (`llm_cache`) | — (they came from Anthropic) |
| Usage log (tokens, cost, which document) | `ordnung.db` (`llm_calls`) — **no prompt or response bodies** | Never |
| Fonts, UI, rules engine | bundled in the package | Never (no CDN, no web fonts) |

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
- **The watched folder waits for you** — files your scanner or phone app saves into the watched folder
  are stored and read on this computer only, and wait in the Inbox ("From your folder — waiting for
  you") until you choose *Read these* or *Keep private* ([details](#the-watched-folder)). *Keep
  private* can be undone (the toast's *Undo*, or *Undo "Keep private"* on the letter — for an e-mail,
  its attachments kept private with it wait again too).
- **E-mail attachments follow the e-mail** — each PDF or photo attached to an e-mail you add becomes
  a letter of its own with the e-mail's choice: attachments of a private e-mail stay private, those of
  a waiting e-mail wait with it.
- **Delete means delete** — deleting a letter removes it for good: the original, page images,
  everything read from it, its to-dos and Ideas, its search-index entries, its entries in the
  activity log, quotes from it in contracts you keep, and the cached model responses of every call
  that carried it (a secretary's note or review built from several letters included). The usage log
  keeps only anonymous numbers, and deleted database rows are overwritten rather than left behind.
  Contracts and letters you drafted stay, without the link to it; your *Ask* conversations stay as
  they are. *Settings → Delete everything* wipes the whole database.
- **Models** — choose which Claude model handles each purpose.
- **Nothing is sent or paid automatically** — Ordnung drafts letters and suggests actions; you send
  them yourself.

## The watched folder

In *Settings → Watched folder* you can point Ordnung at a folder your scanner or phone app saves
into — best a folder just for letters. It is off until you choose one.

- **Nothing is sent until you say so.** A new file is copied into Ordnung's data folder like an
  upload and read on this computer only (its text layer, for search and the page images; an e-mail is
  named by its subject and sender) — then it waits. *Read these* sends it to Claude like any letter you
  add; *Keep private* keeps it as if you had added it with "Keep private — no AI". Waiting letters are
  private in every other way too: *Ask*, the weekly review, the daily note and drafting never see them.
  Today tells you they wait (it can't know their dates), and so does the Inbox's count.
- **"Read new files with Claude straight away"** skips the waiting for files that **arrive** in the
  folder from then on: each one is sent to Claude as soon as it appears. The files that were already in
  the folder when you chose it always wait — choosing a busy folder like *Downloads* never sends what
  is already there, also when you choose it again after *Stop watching* (what landed in it meanwhile
  waits too) — and so do files already waiting: a copy of a waiting file arriving in the folder
  never answers for it. Only you do, by choosing *Read* or *Keep private*, or by adding the same file by
  hand.
- **Ordnung's own drafts are not letters you received.** A letter Ordnung drafted for you (with your
  address and IBAN from the profile) that you download into the watched folder is recognised and not
  added — so it is never sent to Claude that way.
- **A cloud-synced folder is already shared with its cloud provider.** If the folder is inside
  Dropbox, iCloud Drive, OneDrive or Google Drive, that provider has copies of every file in it,
  whatever Ordnung does. Choose a folder on this computer only (for example Ordnung's own inbox
  folder, offered in Settings) if that matters to you.
- **Read-only.** Ordnung only lists and reads the folder: it never writes, moves, renames or deletes
  anything there, never follows a symbolic link, never enters a sub-folder, and ignores partial and
  temporary files.
- **What Ordnung remembers.** To pick up each file once, it keeps a hash of the folder, the file's
  name, size and date — not the name itself — while the file is in the folder, and the fingerprints
  (SHA-256) of the drafts it made for you. The activity log lists the files the folder brought in;
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
