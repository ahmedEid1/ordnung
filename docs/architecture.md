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
      RUL["Rules engine<br/>(pure, 100% tested)"]
      SEC["Secretary<br/>triggers · review · brief · daily tick"]
      ASK["Ask (agent loop)"]
      DRF["Letters<br/>templates · checks · DIN 5008 PDF"]
      ICS["Calendar (.ics)"]
    end
    DB[("SQLite<br/>WAL · FTS5 · trigram")]
    FS[("files/ · derived/")]
    MCP["Ordnung MCP server<br/>read-only"]
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
| Model → ledger | Schema validation, quote grounding with exact digits, `spec_consistency`, deterministic date computation, confidence rubric → "Please check" |
| Model → user | Ideas and letters are suggestions; nothing is sent, paid, closed or deleted without a click; letters use fixed legal templates |
| Agent → data | Ask only has read-only MCP tools on a `query_only` connection; every tool result is wrapped as untrusted; citations must appear in the same turn's tool results |
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
  A->>R: compute_due / compute_contract (RuleContext: today, region, delivery scope)
  R-->>A: due date · send-by · receipt (steps, citations, confidence)
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
  S->>C: question + system prompt (tools: mcp__ordnung__* only, budget cap, timeout)
  loop agent loop
    C->>M: search / get_document / list_contracts / explain_date
    M-->>C: results with ids (document text wrapped as untrusted)
  end
  C-->>S: streamed answer with [contract:…] [doc:…] citations
  S->>S: validate citations (exist + seen in this turn's tool results), strip others
  S-->>U: answer + tool trace + citation chips (SSE)
```

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
