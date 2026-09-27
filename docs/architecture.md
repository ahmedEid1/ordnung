# Architecture

Ordnung is a single Python package (`ordnung`) that serves a React single-page app on
`127.0.0.1`, keeps everything in one SQLite file, and talks to Claude only through the user's own
`claude` CLI. This page explains how the pieces fit together and why.

## Components and trust boundaries

```mermaid
flowchart LR
  subgraph untrusted["Untrusted input"]
    L["Letters · PDFs · phone photos · .eml"]
  end

  subgraph local["Your computer (127.0.0.1)"]
    UI["React app<br/>(Vite · Tailwind)"]
    CLI["CLI (Typer)"]
    API["FastAPI<br/>token · same-origin · CSP"]
    subgraph core["ordnung core"]
      ING["Ingest pipeline<br/>intake → text/transcribe → extract<br/>→ verify → compute → link → plan"]
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
| Document → model | Documents are untrusted: hidden text removed, content wrapped in `<untrusted_document>`, **no tools** during reading, output forced through a JSON schema |
| Model → ledger | Schema validation, quote grounding with exact digits, `spec_consistency`, deterministic date computation, confidence rubric → "Please check"; high-stakes letter kinds (court orders, a dismissal …) are assigned by a written code policy from the reading, never by the model (ADR 0010), and court deadlines — every date on a court's letter, whatever kind it is filed as — are never `high` and never use a delivery fiction |
| Model → user | Ideas and letters are suggestions; nothing is sent, paid, closed or deleted without a click; letters use fixed legal templates |
| Agent → data | Ask only has read-only MCP tools on a `query_only` connection. Every tool result has two channels: Ordnung's record (`<ordnung_record>`: ids, statuses, due and send-by dates, rules-engine dates, verified amounts, totals, code-written receipts) and the letters' text by record id (`<untrusted_document>`: titles, summaries, names, quotes, page text, unverified amounts); `<` and `>` are escaped in both. A tool keeps each result within a size budget by leaving out rows, so the model and the check read the same whole result — the CLI backend never shortens the check's copy ([ADR 0008](decisions/0008-two-channels-and-claim-level-citations.md)). Ask's server is `--ledger-only`: the ledger-free rules tools are not among its tools, and a result of any tool that is not one of Ordnung's ledger tools is never evidence for the check ([ADR 0011](decisions/0011-ask-keeps-to-the-ledger.md)) |
| Agent → user | Citations must name records from a record part of the same turn. The answer's words are never streamed: the person sees the tool trace (which tools ran, the words searched for with every word of a value the check reads — any word with a digit, a part of a month — shown as "…", the date range looked at) and a "writing" line until the check is done, and nothing of an answer that stops or fails before it. The answer is read as it will be shown (its bidirectional formatting characters removed first); each date, time or amount must be in the record part of a record its sentence cites; a sentence without a citation of its own may state a value of a record the answer cites, and the check then adds that record's citation — when the values belong to one record, never a record with scam signs; overview totals only in a sentence without a citation of its own; a cited record's unverified amount or the person's own words are shown quoted as unconfirmed; every other value is left out — one the cited letter's text holds as "[date only in the letter]", whatever the sentence's wording — and never shown within its sentence (the edit keeps the sentence's full stop and citation), and a § nobody vouches for removes its sentence, with a note in the answer's language that only the check writes, that says only what is true of every case it covers, and that travels in its own field with its label. The prompt (`ask_system` v5) says the same, so the model does not state a letter's value in the first place. Every date form the web formats inside an answer is read by the check (one shared list, tested on both sides), the placeholders the check writes are one list the web marks, the month words that keep a day line from being a list item are one list, the web shows a line starting with a day as written (never renumbered), and a run of digit groups shaped like a date that is none is never supported, nor is a day, a word and a year in a language whose month names the check does not know (Ask answers in the question's language), a clock time moved by words or a day in words; a law cited in words is checked like a §, and the model can never write the note's label (look-alike letters and soft line breaks included). The check fails closed: an answer it cannot read ends in an error and is not shown; a number no amount can be is unreadable, never an exception. Measured by `python -m evals.ask` ([evals-ask](evals-ask.md)), whose replay — like `ordnung demo --check` — answers every recorded tool call again and fails when the tools' output changed |
| Other clients → Ordnung | `ordnung mcp --rules-only` serves only the rules tools: no data folder is opened, results are computed from the arguments alone. The full server gives a client the same read-only ledger Ask has; `ordnung mcp install` prints before it writes and never clobbers a client's config |
| Upload → machine | Checked before anything decodes it: PDF stream expansion, image pixels and text pages are capped; the data folder is private to the account (`0700`, files `0600`) |
| Browser → server | Loopback by default (another `--host` warns and still needs the token), session token cookie (the browser is opened through a private local page, never with the token on a command line), `X-Ordnung-Client` header on writes, Fetch-Metadata/Origin checks, strict CSP, side-effect-free GETs |
| Process → OS | Documents and user prompts never on argv (stdin only; argv carries flags and the fixed system prompt), own process group killed on timeout, `--setting-sources ""`, `--strict-mcp-config`, `--no-session-persistence` |

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
documents; a restart resumes queued work.

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
  arrival never makes the date later than counting from the day a letter usually counts as delivered),
  and so
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

## Concurrency model

- **One process.** FastAPI (uvicorn) runs the API, the ingest worker and the daily tick on one
  asyncio loop; CPU-heavy work (PDF text, rendering) runs in threads (`asyncio.to_thread`).
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
| CLI subprocess layer | A fake `claude` executable replaying captured CLI outputs (errors, timeouts, huge lines) |
| Demo | `ordnung demo --check`: rebuild twice with strict replay → zero misses, identical dumps, all references resolve |
| Web app | Vitest units + Playwright tour over demo mode with axe accessibility checks |
| Model quality | The benchmark in [evals](evals.md), recomputed deterministically in CI from recorded outputs |
| MCP tools and install | In-memory MCP client and a real stdio handshake (`python -m ordnung mcp --rules-only`); config merge, backup and refusal in temporary home folders |
| Ask | Unit tests of the two channels and the claim policy (incl. injected dates and ids), and the Ask benchmark in [evals-ask](evals-ask.md), replayed in CI with gates |
