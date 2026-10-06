# Architecture

Ordnung is a single Python package (`ordnung`) that serves a React single-page app on
`127.0.0.1`, keeps everything in one SQLite file, and talks to Claude only through the user's own
`claude` CLI. This page explains how the pieces fit together and why.

## Components and trust boundaries

```mermaid
flowchart LR
  subgraph untrusted["Untrusted input"]
    L["Letters · PDFs · phone photos · .eml"]
    WF["Watched folder<br/>(scanner, downloads)"]
  end

  subgraph local["Your computer (127.0.0.1)"]
    UI["React app<br/>(Vite · Tailwind)"]
    CLI["CLI (Typer)"]
    API["FastAPI<br/>token · same-origin · CSP"]
    subgraph core["ordnung core"]
      FW["Folder watcher<br/>read-only · files wait for you"]
      ING["Ingest pipeline<br/>intake (+ e-mail attachments) → text/transcribe<br/>→ extract → verify → compute → link → plan"]
      RUL["Rules engine<br/>(pure, 100% tested)<br/>+ high-stakes letter routing"]
      SEC["Secretary<br/>triggers · review · brief · daily tick"]
      ASK["Ask (agent loop)"]
      DRF["Letters<br/>templates · checks · DIN 5008 PDF"]
      ICS["Calendar (.ics)"]
    end
    DB[("SQLite<br/>WAL · FTS5 · trigram")]
    FS[("files/ · derived/")]
    MCP["Ordnung MCP server (--ledger-only)<br/>read-only ledger tools, no rules tools"]
  end

  subgraph account["Your Claude account"]
    CC["claude -p<br/>(your install & login)"]
  end

  L --> API
  WF -->|"listed and read only"| FW
  FW --> ING
  UI <-->|REST + SSE| API
  CLI --> API
  API --> ING & SEC & ASK & DRF & ICS
  ING --> RUL
  SEC --> RUL
  DRF --> RUL
  ING & SEC & DRF & ICS <--> DB
  ING <--> FS
  ING -->|"stdin: text or page images<br/>--tools '' · --json-schema"| CC
  SEC -->|"agenda / snapshot"| CC
  DRF -->|"context for free text + translation"| CC
  ASK -->|"question · only mcp__ordnung__* tools"| CC
  CC -->|tool calls| MCP
  MCP -->|"query_only"| DB
```

**Trust boundaries**

| Boundary | Defence |
|---|---|
| Document → model | Documents are untrusted: hidden text removed (white, tiny, off-page or drawn invisibly; a scan's invisible OCR layer is not read — the page is read from its picture), content wrapped in `<untrusted_document>`, **no tools** during reading, output forced through a JSON schema |
| Model → ledger | Schema validation, quote grounding with exact digits, `spec_consistency`, deterministic date computation, confidence rubric → "Please check"; high-stakes letter kinds (court orders, a dismissal …) are filed by a written code policy: the kind code reads from the reading wins, and the kind the model names is dropped when the reading rules it out (ADR 0010), and court deadlines — every date on a court's letter, whatever kind it is filed as — are never `high` and never use a delivery fiction |
| Model → user | Ideas and letters are suggestions; nothing is sent, paid, closed or deleted without a click; letters use fixed legal templates |
| Ledger → banking app | A GiroCode (EPC-QR) only pre-fills a transfer the person confirms with their TAN. Code decides, by a written policy (`secretary/girocode_gate.py`), which payment gets one: a transfer still to make (no debit named in its sentence), not one of several, no scam signs (nor its IBAN on another letter with them), every value grounded in the text layer (or known for the sender) — a value read from a photo, or an amount the person changed, waits until the person compares the exact details with the paper letter. The QR is drawn in the browser; the payload never leaves the machine |
| Agent → data | Ask only has read-only MCP tools on a `query_only` connection. Every tool result has two channels: Ordnung's record (`<ordnung_record>`: ids, statuses, due and send-by dates, rules-engine dates, verified amounts, totals, code-written receipts, a rent contract's rent in force and the next rent that replaces it) and the letters' text by record id (`<untrusted_document>`: titles, summaries, names, quotes, page text, unverified amounts); `<` and `>` are escaped in both. A tool keeps each result within a size budget by leaving out rows, so the model and the check read the same whole result — the CLI backend never shortens the check's copy ([ADR 0008](decisions/0008-two-channels-and-claim-level-citations.md)). Ask's server is `--ledger-only`: the ledger-free rules tools are not among its tools, and a result of any tool that is not one of Ordnung's ledger tools is never evidence for the check ([ADR 0011](decisions/0011-ask-keeps-to-the-ledger.md)) |
| Agent → user | Citations must name records from a record part of the same turn. The answer's words are never streamed: the person sees the tool trace (which tools ran, the words searched for with every word of a value the check reads — any word with a digit, a part of a month — shown as "…", the date range looked at) and a "writing" line until the check is done, and nothing of an answer that stops or fails before it. The answer is read as it will be shown (its bidirectional formatting characters removed first); each date, time or amount must be in the record part of a record its sentence cites (a payment the app says to decide on before paying — a rent increase's new rent, a late statement's back-payment — carries that note in the record, and the check repeats it under an answer that cites it); a sentence without a citation of its own may state a value of a record the answer cites, and the check then adds that record's citation — when the values belong to one record, never a record with scam signs; overview totals only in a sentence without a citation of its own; a cited record's unverified amount or the person's own words are shown quoted as unconfirmed; every other value is left out — one the cited letter's text holds as "[date only in the letter]", whatever the sentence's wording — and never shown within its sentence (the edit keeps the sentence's full stop and citation), and a § nobody vouches for removes its sentence, with a note in the answer's language that only the check writes, that says only what is true of every case it covers, and that travels in its own field with its label. The prompt (`ask_system`, since version 6) says the same, so the model does not state a letter's value in the first place. Every date form the web formats inside an answer is read by the check (one shared list, tested on both sides), the placeholders the check writes are one list the web marks, the month words that keep a day line from being a list item are one list, the web shows a line starting with a day as written (never renumbered), and a run of digit groups shaped like a date that is none is never supported, nor is a day, a word and a year in a language whose month names the check does not know (Ask answers in the question's language; joined by spaces, marks or none, in any order), a month and year of another offered language, another calendar's date, `31/12`, an amount in another currency or with another language's scale word, a clock time moved by words or a day in words; a law cited in words is checked like a §, and the model can never write the note's label (look-alike letters and soft line breaks included). The check fails closed: an answer it cannot read ends in an error and is not shown; a number no amount can be is unreadable, never an exception. Measured by `python -m evals.ask` ([evals-ask](evals-ask.md)), whose replay — like `ordnung demo --check` — answers every recorded tool call again and fails when the tools' output changed |
| Other clients → Ordnung | `ordnung mcp --rules-only` serves only the rules tools: no data folder is opened, results are computed from the arguments alone. The full server gives a client the same read-only ledger Ask has; `ordnung mcp install` prints before it writes and never clobbers a client's config |
| Watched folder → Ordnung | Only files directly in the folder with a type Ordnung reads; symbolic links never followed (`O_NOFOLLOW`), sub-folders not entered, partial and temporary files ignored; at most 50 MB + 1 byte read, then the upload checks below. The folder is never written to. A new file is **held** — private and read on this computer only, never sent to a model — until the person answers in the Inbox (`ingest/held.py`), unless they turned on reading new files at once |
| E-mail → attachments | Each attached PDF or photo (decided by its bytes) passes the upload checks below as a document of its own, at most 10 per e-mail, with the e-mail's privacy choice; pictures inside the e-mail are skipped, other types listed, a forwarded e-mail never opened (`ingest/attachments.py`) |
| Upload → machine | Checked before anything decodes it: PDF stream expansion (an encrypted PDF's measured decrypted), image pixels and text pages are capped; a refused upload leaves no file behind; the text layer is read on a pdfminer document that gives up after 1000 lookups answering with another reference, so a PDF whose objects refer to themselves can't hang a reading (its pages are transcribed instead); the data folder is private to the account (`0700`, files `0600`) |
| Browser → server | Loopback by default (another `--host` warns and still needs the token), session token cookie (the browser is opened through a private local page, never with the token on a command line), `X-Ordnung-Client` header on writes, Fetch-Metadata/Origin checks, strict CSP, side-effect-free GETs (three bounded exceptions: `health?probe=1`, "Run check", makes one tiny live model call, at most once a minute; `health` itself, when its Claude status is stale, checks Claude again (no model call), uses a `claude` found on PATH from then on and, once Claude is ready, lets the letters waiting for it be read; and downloading a drafted letter's PDF — or a sent letter's Nachweis — records its SHA-256 among the last 200, so the watched folder never takes the download for a letter received — the fingerprint must be of the exact bytes handed out, which depend on the profile at download time). Any unexpected server error is a JSON `500`: `{detail: a plain sentence, code: "internal_error", error: the exception's class name}`. The error's message is never sent, because it may quote a letter |
| Process → OS | Documents and user prompts never on argv (stdin only; argv carries flags and the fixed system prompt), own process group killed on timeout, `--setting-sources ""`, `--strict-mcp-config`, `--no-session-persistence`. The desktop notification's texts (letters' titles in *full* mode) reach `notify-send` / `osascript` / PowerShell as separate arguments of a fixed script or in environment variables — never a shell line; markup is escaped, control and bidi characters removed. The start-at-login entry is a file Ordnung writes (quoted per format, a line break refused) and discards the server's standard output, so the session token never reaches a journal |
| Ordnung → your calendar provider (opt-in) | Nothing is sent until a calendar is connected; `https://` (or `http://` to this computer's loopback address), TLS verified, no redirects followed to another host; discreet by default (dates, times and alarms — no titles, names or amounts); only resources Ordnung created are replaced or deleted; the app password lives in the OS keyring (a backend that doesn't keep passwords safely — `null`, `keyrings.alt`, priority below 1 — is refused), never in `ordnung.db`, a log or an answer, and the keyring is read only to connect, send a change, check once a day that Ordnung's events are still there, or disconnect (never to show Settings); the keyring account is bound to the data folder's connection, so a restored copy of the data never reads or deletes the original's password and starts with syncing paused; "Delete everything" removes Ordnung's events and the password first; a server's XML is size-capped and read without a DTD |
| Backup file → data folder | Authenticated encryption end to end (header MAC, AES-256-GCM chunks bound to the header, their order and the last one), a newer format refused before any key is derived, scrypt costs capped when read (at most 256 MiB of memory, p ≤ 2); the archive extracted under a name policy (regular files in three folders only) into a staging folder, read to its authenticated end and checked against its manifest before it replaces anything; a folder with data is moved aside, never deleted ([ADR 0013](decisions/0013-backups-and-reminders-outside-the-browser.md)) |

## Reading a letter

```mermaid
sequenceDiagram
  autonumber
  participant U as You
  participant A as API / worker
  participant T as text & verify
  participant C as claude -p
  participant R as rules engine
  participant D as SQLite

  U->>A: drop letter (PDF or photos)
  A->>A: intake — sniff, normalise, combine photos, hash → doc_<sha>
  A->>T: render pages, text layer + word boxes, hidden-text scan
  alt page has no text layer (photo/scan)
    A->>C: transcribe page image (stdin, no tools)
    C-->>A: verbatim text  → stored as transcript
  end
  A->>C: extract (page text in <untrusted_document>, JSON schema)
  C-->>A: DocumentExtraction with DateSpecs + verbatim quotes
  A->>T: ground every quote (fuzzy ≥ 90 + exact digits) → boxes, grounding level
  A->>R: classify the letter (court order, dismissal, tenancy …) from the reading
  A->>R: compute_due / compute_contract (RuleContext: today, region, delivery scope, letter kind)
  R-->>A: due date · send-by · receipt (steps, citations, confidence) + deadlines the law adds
  A->>D: link party/thread/contract, upsert to-dos by slot, reindex — one transaction
  A->>A: triggers → Ideas (reconciled) · SSE events to the UI
```

Every stage updates the durable `jobs` queue and publishes `job.progress` events, which drive the
live stepper in the UI. Rate limits pause the whole worker until the reset time instead of failing
documents, and Claude not installed or not signed in pauses it until a status check sees Claude ready
(the letters wait as *Waiting for Claude*, and a page opened meanwhile is told of the pause when it
connects; a call that never started carried no letter); a restart resumes queued work.

## The watched folder

```mermaid
flowchart LR
  F[("Watched folder")] -->|"watchfiles + a listing every 60 s"| W["FolderWatcher<br/>settled 2 s · once per file"]
  W -->|"add_file(hold=True), source=folder"| I["intake<br/>(+ e-mail attachments, held too)"]
  I --> Q["worker: text layer only<br/>no model call"] --> H["held<br/>Inbox: From your folder"]
  H -->|"Read these N"| R["queued → read like an upload"]
  H -->|"Keep private"| P["private, processed"]
  P -->|"Undo"| H
```

The watcher runs in the server's lifespan while a folder is set, restarts when the setting changes
and pauses for *Delete everything* (`ingest/watcher.py`; policy in its docstring). It remembers each
file by a hash of folder, name, size and modification time while the file is there — once its pickup
is over, never halfway — so nothing is picked up twice: not after a restart, not after its letter was
deleted. With `inbox_auto_read` files that arrive later skip the waiting; the files that were in the
folder when it was chosen (or chosen again, after *Stop watching*) always wait, and a copy of a waiting file never answers for it (only an
upload or the CLI does, `answer_held`). A held letter stays held whatever happens to its local job.
Refused files and folder problems go to the activity log; `GET /api/folder` reports the state, how
many letters wait and the last files it brought in; Today and the Inbox's count say how many wait.

An e-mail's attachments thread by their own references first (a payment reminder joins its
invoice's thread) and only fall back to the e-mail's thread; a bill that repeats its e-mail's payment
takes it over on read (`Ledger.is_covered_by_attachment`; a bill Ordnung already had counts, from
the e-mail's recorded listing), like a payment reminder takes over its invoice's — and only while no
reminder took the bill's own payment over, so the two relations never hide each other's payment.

## Observability: how a letter was read

Every reading of a letter — on arrival or read again — is kept as a **trace**: a tree of spans
(`ordnung/trace`, migration 0003) that says what Claude was asked and what code decided. The letter's
page shows it in the **How it was read** tab; `ordnung trace <doc> --otel` exports it for any
OpenTelemetry viewer.

```mermaid
flowchart LR
  run["run · Read letter<br/>reading, trigger, result"]
  run --> ocr["ocr · Text layer<br/>pages, words, hidden text"]
  run --> tr["ocr · Transcribe (parallel)"] --> p1["model · Page 1 …"]
  run --> ex["model · Extract"] -.->|"repair_of"| rep["model · Extract · repair"]
  ex -.->|"repair_of"| cmp["model · Extract · complete"]
  run --> q["verify · Check quotes"] --> q1["verify · Quote per item, key fact …<br/>grounding, score, digit groups"]
  run --> snd["link · Sender<br/>decision, candidates + scores"]
  run --> d["rules · Compute dates"] --> d1["rules · Date<br/>DateSpec structure → due, send-by, rule ids"]
  run --> l["link · Thread & contract<br/>payment check, thread, contract, reminder"]
  run --> pl["plan · Plan to-dos"] --> pl1["plan · To-do<br/>created · updated · kept_edited · kept_later_date"]
  ex & rep & p1 -.->|"span_id"| calls[("llm_calls<br/>tokens, cost, latency, key,<br/>prompt + version, outcome")]
```

- **Explicit, never in the way.** The pipeline creates one `Tracer` per reading and passes spans
  down as a `trace` argument; every function defaults to `NO_SPAN`, which records nothing and reads
  no clock. Spans live in memory until the reading ends — done, failed, paused by a rate limit
  or stopped — and are then stored in one insert; storing never raises (a trace that can't be
  written is logged and dropped).
- **One number per reading.** `start_trace` reserves the reading's number in one transaction (its
  root span is stored as `running` and shown nowhere; the worker's startup recovery marks one left by
  a killed process `stopped`), and a measured reading's trace id is random — so a reading whose trace
  was lost, or two readings of one letter at once, never share a number or each other's calls. How a
  reading ended is a code (`done`, `failed` with its kind, `paused`, `stopped`); the view turns it
  into a sentence, so no error message (which may quote the model) is kept. A letter keeps its newest
  five readings that ran to the end and its newest interrupted attempt while it is within them, and
  "Compare" defaults to the newest earlier reading that was done.
- **Model calls join by id.** `LLMService` writes one `llm_calls` row per call (never the prompt or
  the answer) with its replay/cache key, prompt name and version, the model the CLI says answered,
  job, stage and span, and an `outcome` decided by one policy (`ok`, `invalid` → a repair follows,
  `repaired`, `failed`); a repair's row names the call it retried (`repair_of`), and so does the
  completeness re-ask's the call it completes (ADR 0016) — which the reading's repair count leaves out.
- **No letter text.** A span holds counts, codes, scores, the dates Ordnung computed and the ids of
  the records it used — the written vocabulary is `trace/facts.py`. The view looks the records up
  when the trace is shown (a to-do's title, a sender's name), so a deleted record keeps its id and
  loses its label. Key facts have no stable identity, so only the newest reading names them.
- **Stable keys, comparable readings.** A span's key is its path (`run/verify:quotes/verify:item:<slot>`),
  the same in every reading; ids hash the trace id and the key. "Compare with reading N"
  (`trace/compare.py`) lists what a later reading *decided* differently (a date, a grounding, a
  model call's outcome, the sender it linked) — never timings.
- **Deterministic demo.** In the demo (`recorded` timing) no clock is read: a reading starts at a
  fixed time on the demo's day and is laid out from the recorded model latencies (steps of code take
  no time; parallel pages start together, ordered by key), so `ordnung demo --check` rebuilds the
  same spans.
- **OpenTelemetry.** `trace/otel.py` writes OTLP/JSON: model steps are `CLIENT` spans named
  `chat <model>` with `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`,
  `gen_ai.response.model`, `gen_ai.prompt.name`, `gen_ai.usage.input_tokens` (the whole prompt,
  prompt-cache tokens included), `gen_ai.usage.cache_read.input_tokens`,
  `gen_ai.usage.cache_creation.input_tokens` and `…output_tokens`; everything else is under
  `ordnung.*`. Every record id in the file (many are hashes of a file, a name or a sentence) is
  replaced by an HMAC with a key made for that export — a rule's public id (`zpo_692`) stays — and a
  sender's other candidates keep only their scores.
- **Time waiting for Claude** is the union of the model steps' intervals, so the pages of a photo,
  read at the same time, count once.

## Asking a question

```mermaid
sequenceDiagram
  participant U as You
  participant S as Ask service
  participant C as claude -p
  participant M as MCP (read-only)
  U->>S: "When can I cancel my phone contract?"
  S->>C: question + system prompt (tools: the ledger tools only, --ledger-only; budget cap, timeout)
  loop agent loop
    C->>M: search / get_document / list_contracts / explain_date
    M-->>C: <ordnung_record> ids, dates, verified amounts + <untrusted_document> letter text by id
  end
  S-->>U: tool trace, then "writing…" (no words of the answer yet)
  C-->>S: answer with [contract:…] [doc:…] citations
  S->>S: citations: exist + in a record part of this turn, else stripped
  S->>S: each date, time or amount: in a cited record's record part? (no citation of its own: a cited record's, whose citation is added) else unverified amount / person's words (quoted)? else left out
  S-->>U: checked answer + note + citation chips (SSE)
```

The check is a written policy (`assistant/support.py`): deterministic, linear in the answer and the
tool results (each value is looked up in hash maps of the cited records, and no pattern rescans a
run of brackets, digits or spaces; tests time one 88 KB sentence and 40,000-character bracket runs), run in
a worker thread so a long answer never blocks the server, and re-run by the Ask benchmark over
recorded answers.

## My numbers and the weekly session

Two read models over the same ledger snapshot, both written policies (ADR 0007) and both read-only
apart from two `meta` moments:

- **My numbers** (`ordnung/numbers.py`, pure; `views.my_numbers`, `GET /api/numbers`). Each number a
  live letter without scam signs shows — its references, the sender's identifiers in its stored reading,
  its payment IBAN — is classified by value shape, then label words, then context (a Steuernummer is
  yours only from a tax office; an "Ausweisnummer" is an ID card only from an authority), grouped into
  About you, identity documents, call sheets and open cases, and tested with its public check-digit
  algorithm. Ask reads it through `get_my_numbers` (one organisation or one section when asked, bounded
  by its own row caps), values in the letter-text channel (ADR 0008).
- **The weekly session** (`ordnung/secretary/week.py`; `views.weekly_session`, `GET /api/week`) arranges
  `build_agenda`, the money summary, drafts and to-dos as seven steps (and *Act now* first when
  something is overdue or due today; a snoozed to-do is listed where its date puts it) and how it ends —
  overdue, things to do today, or the next day to act (`deadlines`, ranked); `POST
  /api/week/done|dismiss` store the moment (`day|timestamp`) that the prompt policy and "new since your
  last session" read. Its *Post and keep proof* step reads a sent letter's proofs the way its proof
  overview does (`drafts.proof.missing`), its *Waiting for* step is the Waiting for page
  (`secretary.waiting.waiting_for`), and the rows it counts as overdue carry `overdue`. The facts both
  read models share with the Ideas and Ask live in `secretary/triggers.py`: `action_day`, `is_overdue`,
  `paid_at_appointment` (a fee paid on site is no transfer), `unconfirmed_reason` (a date not confirmed
  against its letter, until "The date looks right"), `Ledger.is_set_aside` (a letter with scam signs, an
  invoice a payment reminder took over, an e-mail's payment its attached bill repeats — never counted,
  listed, exported to the calendar or synced) and the identity documents' renewal windows. Every
  `Ledger` built while the database stays the same shares one load of its rows (`_RowsCache`, checked
  per connection with `PRAGMA data_version`, the connection's own writes and the schema version): the
  letters (also by sender, which the scam checks read instead of one query per letter), to-dos,
  contracts and parties, and, once worked out, each letter's scam signs and reading. So a page's
  requests load the letters once.
- **The static demo** gets both from the same code: `scripts/gen_mock_numbers.py` files the mock world
  (`web/scripts/mock-world.mjs`) in a throw-away ledger and writes `web/src/mocks/data/numbers.ts`; the
  mock handlers (`web/src/mocks/numbers.ts`) only follow the visitor's changes (the session ends on the
  first of the ranked days to act still open). CI's end-to-end job
  (the one with both toolchains) checks the file is up to date (`tests/test_mock_numbers.py`).

## The rules engine for other Claude clients

The same engine that dates letters in the app is served as MCP tools that need no ledger
(`ordnung/assistant/rules_tools.py`): `compute_deadline` takes what a letter says — the extractor's
`DateSpec`, validated strictly — plus the letter's date, sender and region, and returns the date
with its receipt (steps, rule ids, citations, warnings, confidence, and hints that name a missing
argument); `german_holidays`, `add_working_days` and `check_iban` expose the calendar and the IBAN
check. Every result says it is information, not legal advice.

```mermaid
flowchart LR
  subgraph client["Claude Desktop · Claude Code"]
    M["the model reads the letter"]
  end
  subgraph rules["ordnung mcp --rules-only"]
    T["compute_deadline · german_holidays<br/>add_working_days · check_iban"] --> R["Rules engine<br/>(ordnung.rules)"]
  end
  M -->|"DateSpec + letter date + sender"| T
  T -->|"date + receipt + citations"| M
```

- `ordnung mcp --rules-only` opens no data folder, so nothing personal is exposed (a `--data-dir`
  given with it is refused, not ignored); the full `ordnung mcp --data-dir D` serves the rules tools
  next to the ledger tools. Ask's own server leaves them out (`--ledger-only`, the server in the
  diagram above): Ask quotes stored receipts and never computes a date. A rules tool's date is
  computed by code, but from a `DateSpec` the model passed — possibly read from an injected letter —
  and it has no record to cite, so it can never be Ordnung's answer under Ask's claim-level check;
  the check reads only the ledger tools' results ([ADR 0011](decisions/0011-ask-keeps-to-the-ledger.md)).
- A model, not a person, passes the facts here, so the tools check them: an arrival day — or a
  delivery day the letter states — after today is refused, an implausible one lowers confidence, a
  letter dated after today is flagged, and a result is always for the server's today — a caller's
  `today` far from it only adds that day's view (the benchmark's server, started with
  `rules_server_config(today=…)`, ignores it). Whether a sender has deemed delivery at all is the
  engine's rule, so the tools and the app agree (a company's letter counts from its arrival; for a
  kind a public body may be filed as, or a period whose own words name an administrative act, a late
  arrival never makes the date later than counting from the day a letter usually counts as delivered;
  a court is a court by its name, whatever kind the model passed it as: formal service, never a delivery
  fiction or `high`, one week at a labour court), and so
  is the warning about a holiday of only part of a Land (15 August in Bavaria) that a date is counted
  back over. A stated posting or delivery day without the letter's date cannot be checked, so the
  result says so and asks for it. Warnings are in the tools' voice (no "tell us"); what to pass is a
  hint. Next to the ledger, a letter in the ledger keeps its stored date: the full server's
  instructions say so.
- `ordnung mcp install --client claude-desktop|claude-code` adds the rules tools unless the ledger
  is asked for (`--with-ledger`, with the privacy warning first); it prints the entry and the file
  it belongs in, and `--write` merges only Ordnung's entry, backs the file up and refuses a file it
  cannot parse (`ordnung/assistant/mcp_install.py`, policy in its docstring). Installing the rules
  tools where the full server already is says so, and `--remove-ledger` takes that entry out.
- The benchmark's fourth condition runs exactly this server next to the *LLM only* prompt, to
  measure an agent with a calculator against the fixed pipeline ([evals](evals.md)).

## Paying a bill: the GiroCode

`GET /api/documents/{id}` carries one GiroCode per payment to-do, worked out on read
([ADR 0012](decisions/0012-girocode-only-for-grounded-transfers.md)): the gate
(`secretary/girocode_gate.py`) gathers the facts — the to-do's status and evidence, where the IBAN and
reference are printed (`pages.text_source`: the text layer is `verified`, an AI transcription
`model_read`), the sender's other letters, the letter's scam signs and payment reminders — and a pure
`decide()` returns either the EPC069-12 payload (`girocode.py`, pure) or a reason. "These match the
letter" (`POST /api/items/{id}/girocode/confirm`) is refused unless the gate is waiting for exactly
that comparison and the posted values are the current ones; it is stored as a `payment.checked`
activity entry naming the letter (`data.doc_id`, so deleting the letter deletes it even after the
to-do is gone), so no migration and no change to the model-facing `PaymentDetails` schema (which would
invalidate the recorded model answers). A refusal — and a failed "Read the letter again", whose
mutation is silent for the same reason — shows in the GiroCode block (not a toast, which waits behind a
phone's sheet or covers a popover's footer), scrolled clear of the panel's sticky footer, with focus
back on its button once the answer is rendered; a refusal refetches the letter; `item.updated` events
refetch letters too, so a code follows an amount changed elsewhere. Whether a payment is a transfer at
all is `ordnung/payments.py`'s written wording policy, which the whole app shares (Today, the triggers,
the party view) and `web/src/lib/payments.ts` mirrors for the to-do's words. The web app draws the QR with `uqr` (level M, version ≤ 13,
quiet zone of four modules), dark on white in both themes. The static demo's codes are generated from
the same gate and builder (`scripts/gen_mock_girocodes.py`; a test keeps them current).

## While the browser is closed: reminders and backups

A secretary that only speaks while its tab is open doesn't do the job, and for a local-first app
the backup is the person's only copy. Both work without the browser and without a model.

```mermaid
flowchart LR
  subgraph login["At login"]
    AS["systemd user unit · LaunchAgent · Startup .cmd<br/>(written by ordnung autostart enable)"]
  end
  AS -->|"python -m ordnung serve --no-browser"| SRV["ordnung serve"]
  SRV --> TICK["Daily tick<br/>(every 15 min)"]
  TICK -->|"build_agenda (code, no model)"| NOTE["notify/desktop.py<br/>discreet: a count · full: 3 things"]
  NOTE -->|"argv / env, never a shell"| OS["notify-send · osascript · PowerShell toast"]
  TICK -->|"only what changed (opt-in)"| CAL["calendar/caldav.py<br/>the .ics events, discreet by default"]
  CAL -->|"https PUT/DELETE, password from the OS keyring"| DAV["your CalDAV calendar"]
  DB[("ordnung.db + files/ derived/ drafts/")] --> BK["backup/ — snapshot in memory → tar →<br/>AES-256-GCM chunks (key: scrypt)"]
  BK --> FILE["one .ordnung-backup file"]
  FILE -->|"ordnung restore: verify all, then swap"| DB2[("a data folder")]
```

- **The notification** is the agenda's words, not a model's: `notify/desktop.py` counts what ends
  today, what is overdue and what is due within 7 days and, in *full* mode, lists the first three —
  today's first. The tick wakes up for it at the chosen time (or a minute after start-up, when the
  desktop may still be starting), retries one the system couldn't show at its next checks (three a
  day at most) and keeps the last failure for Settings; a missing tool shows nothing. The web app's
  preview and test use the same functions (`GET /api/reminders/desktop`, `POST …/test`).
- **Start at login** (`autostart.py`) writes one entry and runs nothing; `status` reads it back
  (which folder it starts, whether it is current) for the CLI and for Settings.
- **Calendar sync** (`calendar/caldav.py`, opt-in) puts the calendar file's events into the
  person's own CalDAV calendar — discreet by default — and keeps them current from the same tick:
  it remembers a digest per event it sent, so an unchanged ledger sends nothing (and reads no
  password) and a finished to-do's event is removed; once a day it asks which of its own events
  are still there and puts back missing ones. The password is in the OS keyring
  (`calendar/secrets.py`), under an account bound to this data folder's connection: a restored
  backup starts detached (`backup/restore.py` → `caldav.detached`). While a calendar is connected the "import the calendar file" Idea stays
  quiet, and "Delete everything" (`api/routes/data.py`) clears the calendar and the keyring first,
  holding calendar sync's lock so no running sync writes its record back.
- **The backup** (`backup/`) is a pull-based stream (`BackupStream`, one step per file): the CLI
  writes it to a file atomically, the API sends it as the HTTP response while it is made. Restore is
  all or nothing (`backup/restore.py`). The format and its policies are in
  [ADR 0013](decisions/0013-backups-and-reminders-outside-the-browser.md).

## Data model (simplified)

```mermaid
erDiagram
  PARTY ||--o{ DOCUMENT : sends
  PARTY ||--o{ CONTRACT : "has"
  PARTY ||--o{ CASE : "threads"
  CASE ||--o{ DOCUMENT : groups
  DOCUMENT ||--o{ PAGE : has
  DOCUMENT ||--o{ ITEM : "creates (slot_key)"
  CONTRACT ||--o{ ITEM : "milestones"
  ITEM }o--o{ SUGGESTION : "referenced by"
  DOCUMENT ||--o{ DRAFT : "answered by"
  DRAFT ||--o{ PROOF : "proof of sending"
  PROOF }o--|| DOCUMENT : "file (source=proof, private)"
  PARTY ||--o{ CALL_NOTE : "phone calls"
  CASE ||--o{ CALL_NOTE : "in thread"
  DRAFT {
    string status "draft|final|sent"
    string tracking_number "checked S10 / online stamp / 12 digits"
    json sent_profile "sender as the PDF showed it when sent"
    date answered_on "the person's word"
    string answer_doc_id "the letter they named"
  }
  PROOF {
    string kind "posting_receipt|delivery_record|..."
    date on_date "the day it shows (optional)"
  }
  CALL_NOTE {
    date called_on
    string promise
    date promise_due "waited for"
  }
  DOCUMENT ||--o{ TRACE_SPAN : "read as (per reading)"
  DOCUMENT {
    string id "doc_ + sha256"
    string kind
    json remedy
    json payment
    bool hidden_text
  }
  ITEM {
    string kind "deadline|payment|appointment|task|expiry"
    date due_date
    date send_by
    json date_spec "what the letter says"
    json computation "receipt: steps, citations, confidence"
    json evidence "quote, page, boxes, grounding"
    bool user_modified
  }
  CONTRACT {
    string regime "bgb309_new|tkg56|vvg11|..."
    json computed "term end, cancel_by, send_by, safe date"
  }
```

IDs are content-derived (`doc_` from the file hash, `itm_` from document + slot, `pty_` from the
normalised name), so re-processing is idempotent and recorded demo outputs stay valid.

**After a letter is sent** (SPEC § 11): `drafts/tracking.py` checks tracking numbers,
`drafts/proof.py` is the written policy (what each proof shows, what is missing, the timeline, what
counts as an answer), `drafts/sent.py` stores proofs and makes the Nachweis (`drafts/pdf.py`
`render_nachweis`), `secretary/waiting.py` works out *Waiting for* on read and `secretary/calls.py`
keeps call notes. Proof files are documents with `source="proof"` and *Keep private* on: the Store
leaves them out of letter lists and counts in SQL, and the ledger never sees them. Whether a file
already in Ordnung was given to a model is `Store.given_to_model` (it was read, a logged call that
started — one whose CLI never started carried nothing —, a cached answer or a transcribed page), never
the document's status — the letter page's *Not sent to Claude* reads it too; removing a proof deletes
its file for good
([ADR 0014](decisions/0014-proof-files-are-deleted-for-good.md)).

**Migrations** (`db/migrate.py`): numbered SQL files — 0001 the v1 schema, 0002 proof of sending and
call notes, 0003 reading traces, 0004 a contract's notice day and a fixed-term job's early notice, 0005
the statutory notice periods a contract names, numbered without a gap when they ship — applied once each and recorded
in `schema_migrations`, so work merged in any order (a lower number after a higher one) still reaches
every database. A ledger that records a different migration under one of the numbers (a development
build from before a renumbering) is refused with the reason, never migrated on a guess.

## Concurrency model

- **One process.** FastAPI (uvicorn) runs the API, the ingest worker, the daily tick and the folder
  watcher on one asyncio loop; CPU-heavy work (PDF text, rendering, listing and reading the watched
  folder) runs in threads (`asyncio.to_thread`); `watchfiles` waits for changes in its own thread.
  `ordnung serve` runs uvicorn on the plain asyncio loop, not uvloop: uvloop runs Python in the child
  it forks to start `claude`, where closing the other threads' SQLite connections could freeze the
  server.
- **SQLite:** one connection per thread, WAL, `BEGIN IMMEDIATE` write transactions (re-entrant via
  savepoints). Linking + planning for a document happen in one transaction under a ledger lock, so
  two letters from the same new sender can't create duplicate parties.
- **Model calls:** two lanes — *interactive* (Ask, letters, brief) never waits behind *background*
  (transcribe, extract, review) — each bounded by a semaphore.
- **CLI + server:** if a server is running for the data directory, the CLI talks to its API;
  otherwise it takes an exclusive data-dir lock and runs in-process.

## Testing strategy

| Layer | How it is tested |
|---|---|
| Rules engine | Worked examples from verified legal research (with sources), external golden cases, Hypothesis property tests, branch coverage |
| Text & verification | Generated PDFs (rotated pages, CropBox offsets, hidden text, scans), exact-digit and consistency rules |
| Store | CRUD round-trips, search escaping, idempotent upserts, purge-on-delete, concurrency, migrations |
| Pipeline & services | `FakeBackend` scripted model outputs end-to-end through the real pipeline |
| Watched folder & attachments | A real temporary folder with short timings: settling, ignored files, symlinks, once-only pickup across restarts and deletions, held by default, auto-read, restarts, a missing folder, the folder left untouched; crafted e-mails for the attachment policy, and e-mailed bills end to end (one thread, limits, privacy inherited) |
| Traces | The tracer's keys, ids and layouts; the span tree of a text letter and a photo letter through the pipeline; the repair link and outcomes; that no letter text reaches a span; delete-means-delete; the API, the comparison, `ordnung trace` and the OTLP export; migration 0003 on an empty database and the demo's |
| CLI subprocess layer | A fake `claude` executable replaying captured CLI outputs (errors, timeouts, huge lines) |
| Demo | `ordnung demo --check`: rebuild twice with strict replay → zero misses, identical dumps, all references resolve |
| Web app | Vitest units; Playwright over the real demo (tour, pages, layout guards) with axe accessibility checks in light and dark mode, and a layout sweep of every page and key state at 320–1920 px (`web/e2e/layout-sweep.spec.ts`) with the UI audit's probes (`make ui-audit` runs the full audit: screenshots of every state at five widths in both themes); and a `real-app` project against `ordnung serve` with a fake `claude` (`web/e2e/real-app-*.spec.ts`: what the demo can't show, such as a letter you add being read and its date reaching the calendar file, or a letter deleted for good being gone) |
| Model quality | The benchmark in [evals](evals.md), recomputed deterministically in CI from recorded outputs |
| MCP tools and install | In-memory MCP client and a real stdio handshake (`python -m ordnung mcp --rules-only`); config merge, backup and refusal in temporary home folders |
| Ask | Unit tests of the two channels and the claim policy (incl. injected dates and ids), and the Ask benchmark in [evals-ask](evals-ask.md), replayed in CI with gates |
| Backup and restore | Byte-for-byte round trips with equal row counts (a seeded ledger and the whole demo life), every byte flipped, chunks cut, swapped, appended or taken from another backup, hostile header parameters, a Hypothesis round-trip-and-flip property, hostile archives inside validly encrypted files (`..`, absolute names, links, duplicates, extras, a damaged or newer database), and the restore policy (free folder, `--force` moves aside, a held lock, a failed swap); a write only in the WAL; every file written through a binary descriptor, and a restored file whose size on disk differs refused; links named, not silently skipped |
| Reminders outside the browser | Notification text in both modes from seeded agendas (discreet never names a title, party or amount), argv/env per system with hostile titles, the once-a-day policy and the tick; autostart entries per system written into temporary home folders, quoting of awkward paths, status and removal |
| Calendar sync | A small fake CalDAV server (in-process and on a loopback socket) that checks the password, one event per resource and UID conflicts: discreet events never carry a title, name or amount; only changed events are sent, only Ordnung's own removed; discovery (well-known, principal, calendar home, another https host); every refusal (password, not a calendar, tasks only, redirects, DTDs, oversized answers, TLS, the network); the pause after a refused password; the password never in the data folder; the keyring adapter with an in-memory backend; events deleted from the calendar put back by the daily check; a backup restored next to the original, or on a new computer after the old one was wiped; addresses in a server's answer that can't be read |
