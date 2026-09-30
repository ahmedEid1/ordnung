# Ordnung — Product & Engineering Specification (v2)

> Build contract. Every module is implemented against this document; if code and spec disagree,
> fix one of them in the same change. v2 folds in a four-lens design review (product, engineering,
> hiring, trust) — see §20 for what changed and why.

## 1. Vision

**Ordnung is a private AI secretary for life admin.** Drop in letters, bills, contracts, payslips
and phone photos. Ordnung reads them with Claude, keeps a living record of everything you owe and
everything that is coming (deadlines, payments, appointments, renewals, expiries), shows your life on
a timeline, reminds you before things matter, suggests helpful actions, and drafts the formal
replies — with every fact traceable to the sentence it came from and every date computed by tested
legal rules, not guessed by a model.

**Honest privacy statement (use this wording everywhere):** *Your files and your database stay on
this computer. When Claude reads a letter, that letter's text or image is sent to Anthropic through
your own Claude account (Claude Code, the Claude program you installed and signed in to). Ordnung
has no server, no telemetry and never sees your credentials.*

### 1.1 What makes it different

1. **A ledger, not a chat** — parties, threads, contracts, to-dos & dates, linked across letters.
2. **Grounded** — every extracted fact carries evidence (page, verbatim quote, highlight box).
   Digits must match the page exactly and values must be consistent with their quote.
3. **LLM reads, code computes** — the model returns a `DateSpec`; a unit-tested rules engine computes
   the date (4-day *Bekanntgabe* rule since 2025, §§ 187–193 BGB, Bundesland holidays, consumer
   contract law) and explains it ("Why this date?").
4. **A proactive secretary** — deterministic triggers + a weekly LLM review produce "Ideas" with
   reasons and sources; nothing is ever sent or paid automatically.
5. **Measured** — a benchmark separating *reading* errors from *computing* errors, LLM-only vs
   LLM + rules, with confidence intervals and a failure gallery.

### 1.2 Principles
Local app & data · grounded or flagged · humble automation (suggest, never act) · works without AI
(manual entry, demo replays) · not legal advice (citations + disclaimer, conservative dates).

### 1.3 Persona for the demo
**Sam Rivera**, 26, international master's student at the fictional *Hochschule Musterstadt* in
*Musterstadt* (NRW → holidays region `NW`), Werkstudent 20 h/week, student residence permit, rented
flat, phone contract, gym, electricity, health & liability insurance, Deutschlandticket. Reads German
at B1, prefers English. All organisations are fictional (`Muster…`) and every sample is marked
SPECIMEN.

## 2. Release plan (definition of done)

**P0 — golden path (must be flawless):**
1. `ordnung demo` opens instantly on a prebuilt demo database with a guided tour; a *New mail* tray
   holds 3 unopened letters that are processed live (replayed model output, visible stepper).
2. **Today**: secretary's note, top-3 actions with countdowns, coming up, ideas, life at a glance.
3. **Document viewer**: verdict card (what / do / by when / if ignored), highlighted evidence on the
   page image, "Why this date?" with rule steps and citations, explained simply, key facts.
4. **Timeline** with year-ahead *life lanes* and a month-grouped list.
5. **Contracts** with lanes chart (notice windows, send-by markers), fixed costs per month.
6. **Ask** with a visible tool trace, answers shown once checked, validated citations.
7. **Letters**: cancellation / objection / general reply → bilingual draft → DIN 5008 PDF → "how to send".
8. `.ics` export with alarms ("Add your dates to your calendar"), onboarding wizard, Settings incl. privacy & AI usage.
9. Benchmark run live and published (`docs/evals.md`), README with GIF, diagram, numbers.
10. CI green: backend, frontend, e2e (Playwright over demo mode incl. axe checks), `demo --check`.

**P1 — only after P0 is green:** quick capture bar ("Add anything…" with preview), static hosted demo
export, model/cost trade-off eval, Ask agent eval, "please check" received-date question, ⌘K search,
per-document pipeline trace view.

**Cut (v1.1+):** bank CSV/money subsystem, calendar month page, MCP write tools, OCR, LLM party
tie-break, extra letter kinds, most CLI commands. (The watched inbox folder, cut here, came in phase 2:
§ 8.1.)

## 3. Architecture

```
 untrusted input                      local machine (127.0.0.1)                          user's own account
┌──────────────┐   upload   ┌───────────────────────────────────────────────────────┐
│ letters, PDFs├──────────► │ FastAPI  ──►  ingest pipeline                          │   stdin (JSON)   ┌─────────────┐
│ phone photos │            │   │           intake → text/transcribe → extract ──────┼────────────────► │ claude -p   │──► Anthropic
└──────────────┘            │   │           → verify → compute (rules) → link → plan │ ◄──────────────  │ (no tools,  │
                            │   │                                                    │  schema-checked  │  JSON schema)│
 browser SPA ◄── REST+SSE ──┤   ├─ secretary (triggers, review, brief, daily tick)   │                  └─────────────┘
 CLI (Typer)  ─────────────►│   ├─ drafts (compose → checks → DIN 5008 PDF)         │
                            │   └─ assistant (Ask) ── claude -p ── MCP (read-only) ──┼──► SQLite (query_only)
                            │  SQLite (WAL, FTS5) · files/ · derived/                │
                            └───────────────────────────────────────────────────────┘
```

Trust boundaries: documents are **untrusted**; the extraction model has **no tools** and its output
is schema-validated, verified against the page text and fed to deterministic code; the Ask agent can
only call Ordnung's **read-only** MCP tools; the UI never renders model output as HTML.

### 3.1 Repository layout
```
src/ordnung/            (the main modules; the package itself is the complete list)
  cli.py  config.py  clock.py  ids.py  models.py  events.py  app_context.py  views.py  tick.py
  payments.py  numbers.py  girocode.py  recurrence.py  doctor.py  locking.py  server.py
  db/ (schema.sql, migrations/NNNN_*.sql, store.py)
  llm/ (base.py, claude_cli.py, replay.py, fake.py, runtime.py, schemas.py, prompts/*.md)
  rules/ (calendar_de.py, periods.py, delivery.py, deadlines.py, contracts.py, catalog.py, send.py,
          routing.py, letters.py, advice.py, explain.py, consumer.py, employment.py, tenancy.py)
  ingest/ (intake.py, text.py, transcribe.py, extract.py, verify.py, link.py, plan.py, pipeline.py, worker.py,
           held.py, watcher.py, attachments.py, own_files.py, expansion.py, normalize.py)
  secretary/ (triggers.py, review.py, brief.py, week.py, waiting.py, scam.py, calls.py, girocode_gate.py)
  assistant/ (mcp_server.py, ask.py, citations.py, support.py, channels.py, rules_tools.py, mcp_install.py)
  drafts/ (compose.py, checks.py, pdf.py, templates.py, template_letters.py, proof.py, sent.py, tracking.py, fonts/)
  calendar/ (ics.py, caldav.py, secrets.py)  trace/ (spans.py, runs.py, view.py, facts.py, compare.py, otel.py)
  notify/desktop.py  autostart.py  money/iban.py  backup/ (container.py, archive.py, restore.py)
  demo/ (loader.py, tour.py, samples/, fixtures/, demo_db/)   # samples + fixtures ship in the wheel
  api/ (app.py, security.py, deps.py, routes/*.py)
  web/dist/                                                     # built SPA (generated)
web/            React + TS + Vite + Tailwind v4 source
scripts/        make_sample_life.py (+ scan simulation), capture.sh (README assets; web/scripts/capture.mjs), gen_mock_*.py
evals/          dataset manifest, runner, results/*.json
docs/           SPEC, architecture, deadline-rules, privacy, evals, evals-ask, decisions/ (ADRs), assets/ (README pictures)
tests/          pytest (+ tests/fake_claude.py, the fake claude CLI)
```

### 3.2 Stack
Python ≥ 3.11: FastAPI, uvicorn, Pydantic v2, Typer, Rich, sqlite3 (WAL, FTS5), pdfplumber,
pypdfium2, Pillow + pillow-heif, holidays, python-dateutil, icalendar, fpdf2, rapidfuzz, platformdirs,
sse-starlette, python-multipart, httpx, mcp v2 (`mcp.server.mcpserver.MCPServer`), cryptography
(backups), keyring (calendar sync's password store), hypothesis (dev).
Frontend: Vite 8, React 19, TypeScript 5.9, Tailwind 4, React Router 8, TanStack Query, lucide-react,
date-fns, recharts, motion, @fontsource (Inter, Fraunces). Tooling: uv, ruff, mypy, pytest, vitest,
Playwright + @axe-core/playwright, GitHub Actions.

## 4. Domain model — `ordnung/models.py` (implemented; the file is authoritative)

Key additions in v2 (to implement in models.py):
- `Evidence.grounding: Literal["verified","model_read","unverified","user"]` (replaces the boolean
  semantics; keep `verified: bool` = grounding in {verified,user}), `value_consistent: bool`.
- `DateSpec.nature: Literal["objection","payment","declaration","notice","appointment","other"] = "other"`
  (decides whether the § 193 BGB weekend/holiday shift applies).
- `Item.slot_key: str` (stable identity within a document), `user_modified: bool`,
  `due_date_source: Literal["computed","fixed","manual","none"]`.
- `SuggestionStatus` gains `"expired"`.
- `DraftKind` = `"cancellation" | "objection" | "general_reply"` plus eight template kinds (phase 2:
  `withdrawal`, `extension_request`, `payment_plan`, `defect_notice`, `data_access`, `receipts_inspection`,
  `deposit_return`, `address_change` — `models.TemplateDraftKind`); `Draft.body_translation: str`,
  `Draft.send_guidance: SendGuidance | None`.
- `Document.ai_processed_at`, `Document.ai_private: bool` ("Keep private — no AI").
- `DocumentStatus` gains `"held"` (phase 2): a file from the watched folder, or an attachment of one,
  stored and read on this computer only until the person answers (§ 8.1); a held letter is always
  `ai_private` too. `Document.source`: `upload`, `folder`, `email:<the e-mail's id>`, `capture` …
- `AppSettings.model: str = "claude-sonnet-5"` — the model every call runs on (Settings → Claude); the
  per-purpose `AppSettings.models` aliases only key the recordings; the cache is keyed by the model
  a call runs on, so a new choice is a new call (§ 7).
- `AppSettings.inbox_auto_read: bool = False`; `DocumentDetail.attachments: list[EmailAttachment]`
  (an e-mail's attachments and what became of each) and `DocumentDetail.email` (the e-mail a letter
  came attached to); `FolderStatus`, `FolderPickup` (`GET /api/folder`).
- `Page.text_source: Literal["text","transcript","none"]`.
- `LLMRequest.attachments: list[Attachment(path, media_type)]` replaces `files`;
  `purpose: LLMPurpose` Literal.

## 5. Persistence — `db/`

SQLite `<data>/ordnung.db`. Every connection: `isolation_level=None` (autocommit; explicit
transactions), `PRAGMA journal_mode=WAL; busy_timeout=5000; synchronous=NORMAL; foreign_keys=ON`.
`Store.tx()` = `BEGIN IMMEDIATE … COMMIT/ROLLBACK` (re-entrant per thread). Migrations: `PRAGMA
user_version` + `db/migrations/NNNN_name.sql` applied in order on open (0001 = the v1 schema;
0002 = proof of sending and call notes; 0003 = reading traces). What ships is numbered 0001, 0002, …
without a gap; on a development branch a number may be handed out ahead, so the runner only requires
that numbers start at 0001 and never repeat. It keeps a ledger of what ran (`schema_migrations`:
version, name) and applies every migration not in it, in number order — also a lower number that
arrives after a database ran a higher one; `user_version` holds the highest (a newer database is
refused). A database from before the ledger at version 1 ran 0001 (it gets 0002 and 0003); one past 1
without a ledger, or one whose ledger records a different migration under one of the numbers (a
development build from before a renumbering), is refused with the reason (see `db/migrate.py`).
The MCP server opens the DB read-only (`mode=ro` URI + `PRAGMA query_only=ON`).

**Deterministic IDs** (so recorded demo/replay references stay valid):
`doc_` = b32(sha256(file bytes))[:12] · `itm_` = b32(sha1(doc_id|slot_key))[:12] ·
`pty_` = b32(sha1(normalised first-seen name))[:12] · `ctr_` = b32(sha1(party_id|category|customer_number or source doc))[:12] ·
`cas_` = b32(sha1(party_id|normalised reference or case title))[:12] · `sug_` = b32(sha1(fingerprint))[:12].
Random IDs only for manual/user rows (`ids.new_id`), drafts, chat, jobs.

FTS: `documents_fts` (unicode61, remove_diacritics 2) **and** `documents_trigram` (trigram tokenizer)
for substring matches inside German compounds. User queries are escaped (each token quoted).
`delete_document` purges items, pages, jobs, FTS rows (then `optimize`s the indexes), derived files,
the original, `llm_cache` rows of every call that carried the document (cache rows carry `doc_sha`,
`doc_a|doc_b` for several), the Ideas and activity entries about it, its quotes in kept contracts and
its id, replay keys, spans and jobs in `llm_calls`, and the `trace_spans` of its readings;
connections run with `secure_delete=ON`. `llm_calls` never stores prompt or response bodies. A call
that finishes after a letter it carried was deleted is logged without that id, key, span or job, and
its answer is not cached (`log_llm_call`/`cache_put` check in their transaction).

The Store API contract is Appendix A (unchanged names; additions: `tx()`, `reconcile_suggestions`,
`upsert_item_by_slot`, `list_pages`, `set_page_text`, `purge_cache_for(sha)`, `jobs` queue methods).

## 6. Rules engine — `rules/` (pure, 100 % branch-covered, Hypothesis property tests)

A sketch; `src/ordnung/rules/` and `src/ordnung/models.py` are the source of truth (`RuleContext` has more
fields, e.g. the sender's delivery scope and the letter's kind).

```python
@dataclass(frozen=True, kw_only=True)
class RuleContext:
    today: date; country: str = "DE"; region: str | None = None   # None: nationwide holidays only (§ 21)
    document_date: date | None = None; received_date: date | None = None

compute_due(spec: DateSpec, ctx, postal_buffer_days=POSTAL_BUFFER_DAYS) -> ComputationReceipt   # 4 (§ 21)
compute_contract(terms: ContractTerms, ctx, postal_buffer_days=POSTAL_BUFFER_DAYS) -> ContractComputation
is_business_day(d, region) · next_business_day(d, region) · add_business_days(d, n, region)
add_period(event_day, amount, unit, region) -> (date, steps)       # §§ 187(1), 188(2)(3) BGB
deemed_delivery(posted, rule, region) -> (date, steps)
send_guidance(kind, contract_category) -> SendGuidance            # channels & form requirements
catalog: RULES[rule_id] -> RuleInfo(title, citation, url, effective_from, summary, topic)
```

Semantics (final text follows the verified research in `docs/deadline-rules.md`):
- **fixed** dates are returned as written (appointments never shift).
- **relative**: anchor → optional deemed delivery → period arithmetic → § 193 BGB-type shift to the
  next business day of `region` **only** for `nature ∈ {objection, payment, declaration}` (and
  `shift_rule == "auto"`). Notice periods (`nature == "notice"`) never shift.
- **deemed delivery** (`de_admin_post`): letters posted from 2025-01-01 count as delivered on the
  4th day after posting (3rd day before 2025) — § 122 Abs. 2 Nr. 1 AO / § 41 Abs. 2 VwVfG /
  § 37 Abs. 2 SGB X (PostModG). For tax letters (AO) that day moves to the next working day when it is a
  Saturday, Sunday or holiday (BFH IX R 68/98; AEAO zu § 108 Nr. 2). Under § 41 VwVfG and § 37 SGB X it
  does not move (OVG NRW 19 A 4216/99; BSG B 14 AS 12/09 R) — see `docs/deadline-rules.md` § 5. If the
  person entered a later actual arrival date, the receipt keeps the conservative (earlier) deadline and
  adds a note that late receipt may extend it.
- **contracts** (cancel_by = last day the cancellation must be *received*; send_by = cancel_by minus
  `postal_buffer_days` business days; `earliest_exit` is computed on read, not stored):
  consumer contracts concluded on/after 2022-03-01 → after the initial term indefinite, cancellable
  any time with ≤ 1 month notice (§ 309 Nr. 9 BGB); telecom § 56 TKG similar; older contracts use
  their written renewal terms; tenant rent § 573c BGB (3rd business day rule); special cancellation
  rights after price increases (§ 41 Abs. 5 EnWG, § 57 TKG) become Ideas with computed windows
  (`Ledger.price_increase_windows`), which Ask's record carries too (`special_cancellation`, § 10).
- **payments** get a send-by day one business day before the due date for a bank transfer (§ 675s
  Abs. 1 BGB) — none when their words say they are paid in person, by card or cash at the appointment,
  the desk or a machine (`RuleContext.in_person`, set from `payments.pays_on_site` whenever a to-do's
  dates are computed: a letter read, a to-do added or a date set by hand, a recurring one moving on; UI
  audit R1-backend-8).
- Every result has steps with rule ids + citations and a one-sentence plain explanation
  (`ComputationReceipt.summary`), e.g. "Letter dated 15 Sep counts as delivered on Sat 19 Sep →
  moved to Mon 21 Sep; one month later is Wed 21 Oct."
- **High-stakes letters** (`routing.py`, `letters.py`, `advice.py`; `docs/deadline-rules.md` § 7):
  code recognises a court payment order, an enforcement order, a dismissal, a landlord's notice and
  a rent increase request from the model's reading (a written policy) and files the letter under that
  kind (`Document.kind`, a `HighStakesKind` only code assigns). Since extraction prompt version 9 the
  model names the kind itself (`DocumentExtraction.high_stakes_kind`): code's own kind wins when it reads
  one, else the model's is filed unless the reading rules it out (a sender that is clearly no court, a
  European order for payment, a contract of another category, an increase that needs no consent); a
  reading without it (every one recorded before version 9) is filed as before, and the kind the person
  chose wins over both (ADR 0010, update). `RuleContext.letter_kind` routes its dates (two weeks from the
  envelope date for court orders, § 692/§ 339 ZPO; § 38 SGB III; the end-of-month consent period,
  § 558b BGB; two months before the end, § 574b BGB; the 14-day withdrawal that only has to be sent, § 355 BGB), and
  `routing.derived_deadlines` adds the deadlines the law sets that the letter doesn't state (the
  three weeks of § 4 KSchG) as `origin="rule"` to-dos, unless one of the letter's own dates was
  computed under that rule and is not later than the law's (a date that only mentions it, like a
  severance "if you don't sue", isn't; nor is a court order's payment date, which is only half of "pay or
  object"; a letter's own date later than the law's never hides the law's to-do). The three weeks of § 4
  KSchG run from the dismissal's arrival whoever the employer is — a city or a university too, never with
  an authority's delivery fiction — and a regional holiday moves their end only where it holds both at
  the employer's seat and where the person lives (the action may be filed at the court of the place of
  work, § 48 Abs. 1a ArbGG). Registering as job-seeking takes the earlier reading on the boundary day:
  learning on 1 Oct of a job ending 31 Dec gives 1 Oct (three months still left on the reading that three
  months before 31 Dec is 1 Oct), not three days later. A court order
  is only one when a court's letter (a kind of court by name, also in the genitive or abbreviated
  before its place — "AG Hagen", "SG Berlin", "VG Minden", a federal court's alone, "BGH" — never any word
  ending in "gericht") asks the person to answer it (a
  Widerspruch/Einspruch remedy or an objection date) and its title or remedy says which — three
  signals, no list of exceptions: a bailiff's letter, the court's notices to a claimant and
  enforcement-stage letters state no such remedy or date. A date
  follows a letter rule only when its nature fits (an appointment is never re-dated as a
  registration; a hearing never follows the court-action rule; a withdrawal is a declaration). No
  date on a court order is ever `high`, fixed or relative, and a court order's envelope date, once
  entered, is its start whatever anchor it was read with — unless the reading names an earlier start
  of its own, then the earlier, with a warning naming both. Deadlines the law adds that count from the
  end a termination announces (§ 574b, § 38 SGB III) are only as sure as that end: `medium` when it is
  written elsewhere in the letter than the notice's sentence, `low` with "Please check" when it isn't
  written at all (`termination_end`). Every letter from a court
  (`RuleContext.court`), whatever kind it is filed as, runs from delivery — never from an authority's
  4-day fiction — and is never `high`; a labour court's orders give one week (§ 46a Abs. 3, § 59 ArbGG;
  `RuleContext.labour_court`), in their dates, to-dos, card and sending advice. A served letter's one date
  is "delivered" in its summary, warnings and card (the date on the yellow envelope), and its receipt cites
  the court's counting rules (§ 222 Abs. 1 ZPO with §§ 187, 188 BGB; at a labour court through § 46 Abs. 2
  ArbGG; at a social court § 64 SGG), not the AO's or the VwVfG's. A landlord's notice is
  one without notice period only when its own quote or the title says so (*fristlos*, § 543/§ 569 BGB; only
  "außerordentlich" said of the notice is *probably* one, § 573d BGB: its to-do and letter are kept and the
  card says it may be one), not negated (before it or at the end of its clause), not called *ordentlich*,
  not only reserved (a reservation of the notice itself) or "mit (der) gesetzlichen / gesetzlicher Frist" (§ 573d BGB;
  "with statutory notice" in the title) said of the notice itself — not denied ("without statutory notice")
  and not after *hilfsweise* (the alternative notice's period) — and the tenancy ends
  within two months; then there is no hardship objection to-do, and the card and the composer offer no
  objection letter (unless its own words give notice in the alternative — *hilfsweise*, *ersatzweise*,
  *andernfalls*, "sollte die fristlose Kündigung unwirksam sein", or a later end it names: the next permissible
  date or a day at least two months after the letter's date — then the card and the letter's
  note say the objection is excluded against that one too when the grounds for the notice without notice
  period existed, BGH VIII ZR 323/18, so object anyway only if they didn't). Without a to-do computed under
  § 574b (no notice period) the landlord's card is urgent and the verdict says "get advice
  now". An ordinary notice whose objection date had passed when it was written (an end too early for the
  notice period), or whose end wasn't read ("zum nächstmöglichen Termin"), usually ends the tenancy at the
  next permissible date (§ 573c Abs. 1 BGB), so the
  objection may still be open: a `low` to-do counts back two months from the earliest such end after the
  notice arrived (`bgb_573c_landlord`), and the urgent card says both readings — if the end is right, the
  landlord can't have told the tenant in time, so § 574b Abs. 2 S. 2 BGB applies; a notice without notice
  period that gives notice *hilfsweise* with no end of its own (or only the immediate one) gets the same
  to-do for the notice in the alternative. Once the person has closed every to-do that carries a high-stakes letter's legal deadline (the
  law's, or one citing a rule of its card — never the arrears a notice demands or a handover appointment)
  its card is no longer urgent and says so (`advice.handled`, which the verdict uses; never by a recurring
  to-do; its title then reads "… — you've dealt with it" instead of the urgent one), stops asking for the delivery day and offers no letter, and the verdict says it is filed; a
  landlord's notice no objection to-do carries is `closable` instead: the person files it with "I've dealt
  with this" (the letter's `dealt-with` tag, undoable). The objection is for a home only (not a garage or business premises, § 578
  BGB). A rent increase is a
  consent request unless its own quote or title names another kind of increase or a quote says consent
  isn't needed; its payment to-dos say the higher rent is only owed once the person agrees (§ 558b Abs. 1
  BGB) and are never due before the start of the third calendar month after the request arrived (an
  earlier start the letter names is noted, a later one kept), and the verdict never leads with "Pay" for it: "Decide before you pay" until the person closed the
  consent decision (which handles the letter), then "Only if you agreed …" — closing it doesn't say which
  way they decided. What a termination ends is decided by its contract, then the letter's kind, then the sender's (an
  employer's company flat is a landlord's notice); a court's abbreviation ("AG Hagen") counts only before a
  place and from a sender read as an authority (not a retailer, landlord or company, nor a recipient typed
  in without its kind — only a court's full name makes that one a court; an abbreviation typed in may be
  one, so an objection, reply or request for more time to it gets the court's channels with e-mail last
  and allowed "if it isn't a court"), and every court letter's periods cite § 180 ZPO — except a court's
  own period the letter counts from its own date (§ 221 ZPO), which the envelope date never moves (unless
  the letter's date is missing: then it is the latest start). Rule to-dos are filed on read and when the person chooses the kind; a
  changed region, postal buffer or arrival day only recomputes those left, so a deleted one stays
  deleted. An operating-cost statement is recognised on read only (from its words, or the model's
  `operating_costs`), never from a reminder about one, and counts from the statement's own date when a
  later letter dates it ("Abrechnung 2023 vom 15.11.2024": after
  the billing period, of that period's year — never another year's statement's date); a date without its
  year ("unsere Abrechnung vom 15.11.2024", an enclosure's) may be either, so the letter's arrival counts
  but the statement is never called late when that date would make it on time (the card says both
  readings); its card
  checks the 12-month limit of § 556 Abs. 3 BGB from the latest billing period the letter names (in
  figures, words, ISO dates or months, or a billing year) and calls a statement late only when it
  certainly is: only a range the letter calls its billing period decides (any other range or a billing
  year: at most "probably"), and when the latest range found is the previous year's comparison nothing
  is claimed. A named billing year gives way only to a range that says which months it covers (one the
  letter calls its billing period with an "Abrechnungs…" word, or a split year's own months) — never to a
  cost item's service period (a bare "Zeitraum" is no label) or the tenant's own time in the flat
  ("Nutzungszeitraum", "Mietdauer … (Auszug)", "Mietende"), which is never the billing period, even when
  labelled so (at most "probably") — though a range with the tenant's own range written beside it
  ("Abrechnungszeitraum 01.01.–31.12.2025 · Ihr Nutzungszeitraum 01.10.–31.12.2025") is not the tenant's: a tenant who moved out mid-year gets the landlord's period (§ 556 Abs. 3
  S. 2 BGB). A
  date near the end of the calendar (a mistyped year 9999) claims nothing, never an error. When it calls a statement (probably) late, the letter's one-off back-payments (never a
  credit or the new monthly prepayment) carry a "may not be owed — check before you pay" warning, the card
  is urgent and the verdict doesn't lead with Pay; nothing is dismissed. The rent cap is compared exactly, in cents. The person can correct a letter's kind on its
  page ("What kind of letter is this?"); a kind the person chose is kept when the letter is read again
  (the kind and its "kind chosen" entry are written together under the ledger lock, and a re-read reads
  the letter again inside it), a kind an older version filed — the model's, or a high-stakes kind the
  policy no longer gives — is not. A statement the person filed under another kind (even the kind it was
  stored under) is never recognised as a statement again: no card, no late-statement check, no payment note
  (`plan.kind_chosen`).

## 7. LLM layer — `llm/` (implemented; update to v2 invocation)

Invocation (verified on claude 2.1.x): no positional prompt; the request is written to **stdin** as
one stream-json user message containing a text block plus optional base64 `image` (JPEG ≤ 1600 px) or
`document` (PDF) blocks; then stdin is closed.

```
claude -p --input-format stream-json --output-format stream-json --verbose
  [--include-partial-messages]  --model M  --no-session-persistence  --setting-sources ""
  --strict-mcp-config  --system-prompt S  --tools ""  [--allowedTools …]
  [--json-schema J]  [--mcp-config C]  [--max-budget-usd B  (Ask, benchmark tool condition)]
```
- `complete()` returns the model's tool calls with the answer (`LLMResponse.tool_calls`: name,
  arguments, result text), paired by `tool_use_id` because parallel calls may answer out of order;
  the CLI's own `StructuredOutput` call is not one of them. `stream()` yields them as events
  (carrying the same id).
- Process: `create_subprocess_exec(shutil.which("claude"), …, limit=32 MiB, start_new_session=True)`;
  timeout/cancel → `os.killpg`. Never `--bare` (breaks subscription login) and never
  `--dangerously-skip-permissions`.
- Errors are classified from the parsed `result` object (not the exit code): `api_error_status`
  401/403 → `ClaudeAuthError`; 429 / usage-limit text → `ClaudeRateLimited(reset_at)`; 5xx/529 →
  transient (retry ×2 with backoff); `error_max_budget_usd` → `LLMError`; missing or invalid
  structured output → `ClaudeBadOutput` (1 retry); no JSON at all → `LLMError` with stderr tail.
- **Model** (`--model M`), decided in one place (`ClaudeCLIBackend.model_for`), in this order:
  `ORDNUNG_CLAUDE_MODEL` (an override for every call while it is set; the recorders don't use it:
  the demo records with the default model, the benchmarks with the run's `--model` on a backend
  without the setting) >
  `AppSettings.model` (Settings → Claude; `claude-sonnet-5` by default — a pinned id, an alias moves
  with releases; an id or alias as Claude Code takes it: no spaces, not starting with a dash, so a
  Bedrock or Vertex id and `sonnet[1m]` pass; read when the call is made, so a save counts from the
  next call) > the request's own model (`settings.models.<purpose>`, an alias that keys the
  recordings; the doctor probe's `haiku` when no caller names the chosen model). The cache is keyed
  by the model the call runs on: a letter read again after a new choice is read anew. The usage
  log and the trace name the model that answered (`modelUsage`), else the one the call named. The
  demo's settings are the defaults, so it records with the default model. `health` names the pin
  (`model_pinned`) so Settings → Claude can say the saved model waits while the variable is set.
- **Lanes**: interactive (ask, draft, capture, brief; semaphore 1) and background (transcribe,
  extract, review; semaphore `settings.concurrency`, default 2).
- **Keys**: `llm_key(req) = f"{purpose}:{prompt_version}:{model}:{sha256(canonical(stable_inputs))}"`
  — callers pass `cache_key` = canonical stable inputs (e.g. extract: file sha + page modes + language +
  region + simulated today). Used for `llm_cache` and fixture paths `<fixtures>/<purpose>/<sha256(key)[:24]>.json`.
- **Usage log** (`llm_calls`, one row per call): accounting (tokens, cost, latency, cache hit) plus
  the replay/cache key, the prompt template and version, the model the CLI says answered, and — when
  the caller passes its trace step — job, pipeline stage and span; `repair_of` links a repair to the
  call it retried and `outcome` is `ok | invalid | repaired | failed` (`LLMService`, one policy).
- **Replay**: strict in CI/`demo --check` (miss = failure); in the interactive demo a miss becomes a
  friendly note, never an error dialog: Ask's one `demo_miss` event (`error_code: "demo_miss"`, one
  message in `assistant/ask.py`), other model calls one plain message ("The demo replays recorded
  answers only …"). API messages are plain text (commands in “quotes”, never Markdown).
- `doctor` is zero-token: `claude --version`, `claude auth status` (JSON), warns if
  `ANTHROPIC_API_KEY` is set (API billing overrides the subscription), optional 1-call probe on the
  model every call runs on (the CLI reads the setting; "Run check" passes it), whose row names it
  and whose fix on a failure points at that model after the sign-in.

## 8. Ingestion pipeline — `ingest/`

Stages (jobs table is the queue of record; CPU work in `asyncio.to_thread`):
1. **intake** — size cap 50 MB, page cap 60; sha256 → dedupe; HEIC via pillow-heif; images uploaded
   together with `combine=true` become one multi-page PDF (default when several photos are dropped at
   once); render pages (`derived/<doc>/page-N.jpg`, 1600 px) + thumbnail; EXIF transpose.
2. **text** — per page: pdfplumber text + words (coordinates normalised to the page box, CropBox
   and rotation handled) → `text_source="text"` if ≥ 40 meaningful chars, else needs transcription.
3. **transcribe** — for each page without a text layer: vision call (`purpose="transcribe"`, image
   block, cached by page-image sha) → verbatim text → `pages.text`, `text_source="transcript"`.
4. **extract** — one text-mode call with page-delimited text (`=== Page N ===`) + context (today,
   language, region, name, known parties) → `DocumentExtraction`, completed by code where the model
   left out an item its own fields imply (`ingest/extract.py`, `with_rent_series`): a statement's
   higher advance payments given in `change` alone (a monthly price increase with an effective day and
   a new amount on a letter that states a rent contract) become the payment every month from that day
   that the prompt asks for and `recurrence.py` point 9 needs, quoting the change's sentence — never for
   a rent increase that needs consent (§ 558b BGB) or beside a recurring payment that holds the amount.
5. **verify** — for each quote: normalise (with offset map) → `partial_ratio_alignment` against each
   page; score ≥ 90 **and** every digit token of the quote present verbatim on that page →
   located. Grounding: text page → `verified` (+ boxes from matched words); transcript page →
   `model_read`; not found → `unverified`. `value_consistent`: dates/amounts in the DateSpec/item
   appear in the quote (date formats `15.10.2026`, `15. Oktober 2026`, `2026-10-15`, amounts `1.234,56`).
   Dated items with `unverified` evidence → document `needs_review` ("Please check").
6. **compute / link / plan** — inside `store.tx()` under a process-wide ledger lock: compute receipts
   and contract computations; resolve party (identifier → exact/alias → fuzzy ≥ 92, else new party);
   thread into a case by reference numbers/party; link contract changes and cancellation
   confirmations to contracts; dunning ↔ invoice supersession (a reminder takes over a bill's one-off
   payments, never its recurring ones); upsert items by `slot_key`
   (`sha1(kind|normalised quote)`), never overwriting `user_modified` rows; reconcile triggers. The
   letter's warnings are stored as the page shows them: the count of dates that couldn't be confirmed
   without a "Please check:" before it (the page's heading says it), and the model's sentences about the
   payment IBAN's check digits squared with Ordnung's own check (`square_iban_claims`: a claim the check
   contradicts is dropped, a failing IBAN is said once in Ordnung's words; UI audit R1-backend-7).
7. **done** — status `processed`/`needs_review`, `ai_processed_at`, activity log entry, SSE events.

**Two dates for one obligation** (`ingest/conflicts.py`, code only). At **verify**, each dated to-do
(not a recurring one, money coming in, or one whose sentence speaks of a discount) is checked against
the letter's other statements of the same nature — a payment's date or period ("Zahlbar bis",
"binnen 14 Tagen nach Rechnungsdatum"), an objection's date, and for a period counted from the letter a
date the letter gives for itself ("mit diesem Bescheid vom …") — never its own sentence, another
to-do's date, a statement naming another amount, another kind of payment (instalments, a prepayment,
a fee, a direct debit, "erstmals am …") or another remedy, one in the past tense, a due word of another
label on the page ("Rechnungsdatum:" above "Zahlbar bis:"), or an early-payment discount (*Skonto*:
paying after it is not late). At **compute** the engine dates each; a same date, or a written date on or
before the letter's own (the letter's date itself, a reminder's original due date; before the day it
arrived when the letter's date is unknown), is no conflict. Otherwise the
to-do keeps the **earlier** date, its receipt names both and says why (`conflicting_dates`), and it is
`low` and "Please check" — also when the letter's dates are recomputed.

Only the stages that happen are reported to the stepper: a photo goes from **intake** straight to
**transcribe** ("Reading the photo or scan"), a PDF whose pages all have text skips **transcribe**
("Reading the text"); a scanned PDF shows both.

**Trace** (`ordnung/trace`): every reading is one trace — a tree of spans (`run` → `ocr` · `model` ·
`verify` · `rules` · `link` · `plan`) recorded through an explicit tracer the pipeline passes down
(no global state; the default `NO_SPAN` records nothing) and stored in one insert when the reading
ends, however it ends. A span keeps only counts, codes, scores, computed dates and record ids — never
letter text (`trace/facts.py` is the vocabulary); how a reading ended is a code (`done`, `failed` +
the kind of failure, `paused`, `stopped`), never the error's message. A reading's number is reserved
when it starts (its root span is stored as `running`, shown nowhere; one left running by a killed
process is marked stopped at the next start) and a measured reading's trace id is random, so a lost
trace or two readings at once never share a number or a call. A letter keeps its newest five readings
that ran to the end, plus its newest paused or stopped attempt while it is within them. The demo
lays its spans out from the recorded latencies and hashes its trace ids, so a rebuild stores the same trace.

Rate limits pause the worker globally (`paused_until`, SSE `llm.paused` banner); jobs stay queued.
On startup `running` jobs return to `queued`. Reprocess = `force` (skip cache read) and replaces
non-user-modified extracted rows in one transaction. "Keep private (no AI)" skips stages 3–4, and so
does a *held* letter (§ 8.1), which ends `held` and publishes no stage events until the person answers.

**E-mail attachments** (`ingest/attachments.py`, policy in its docstring). When an `.eml` is added,
each attached PDF or photo (JPEG, PNG, WEBP, HEIC/HEIF — decided by its bytes, never by the declared
type or name) becomes a document of its own right after it: through the normal intake with every
limit, `source="email:<the e-mail's id>"`, the e-mail's arrival date and its privacy choice (private,
or held). At most 10 attachments per e-mail are read, the first in the message; pictures inside the
e-mail are skipped (under 64 KB and shown by a `cid:` link or not marked as an attachment; or shown by
a `cid:` link with a shorter side under 800 px, a banner) — a photo of a letter pasted into the text is
read; a zip, Word file, calendar invite, text file or forwarded e-mail is listed and not read. What
became of each (`added`, `known`, `inline`, `not_read`, `refused` with the intake's reason,
`over_limit`; with the linked letter's status now) is written to the activity log on the e-mail and
shown on it, with the number of parts past the 50 listed; an attachment shows the e-mail it came
with. Each letter threads by its **own** references first — a payment reminder attached to an e-mail
joins its invoice's thread, so "pay once, not twice" still holds — and joins its e-mail family's thread
only instead of opening a new one (`link.thread_case(family=…)`); an e-mail read first and still alone
in its thread follows its attachment's thread (`link.follow_attachment`), and the thread it leaves —
empty now — is deleted, so its reference draws no later letter into it. An e-mail whose body repeats
its attached bill's payment (the same direction and currency, and the same amount and due date, or
the same invoice number and amount — or no amount in the e-mail) keeps its to-do, but the bill's
takes it over on read (`link.attachment_repeats`, `Ledger.is_covered_by_attachment`: left out of
Today, the totals and the Ideas, noted on the e-mail, set aside as `attached` on the party and in
Ask's record) — deleting the bill brings it back. The bill counts as the e-mail's attachment also
when Ordnung had it before (`known`: uploaded, from the folder or another e-mail), and its payments
count unless the e-mail itself took them over as a payment reminder: a reminder e-mail with its invoice
attached (or with the Mahnung PDF of the day before) takes the invoice's payment over as the later
reminder and keeps its own — the two never set each other aside; a bill a later reminder took over
keeps the e-mail that repeats it set aside — so one payment to act on always stays. An e-mail nested too deeply
for the parser is refused with a reason. An e-mail title is its subject and sender while it is private
or held (no model). Adding a trashed e-mail again restores its attachments too; adding an e-mail again
whose adding was stopped before its attachments adds them.

### 8.1 The watched folder — `ingest/watcher.py`

`FolderWatcher` runs in the server's lifespan next to the worker and the daily tick while
`settings.inbox_dir` is set, and restarts when the setting changes (policy in its docstring):

- Files directly in the folder with a type Ordnung reads (`.pdf .jpg .jpeg .png .webp .heic .heif
  .txt .eml`, any case); sub-folders are not entered and symbolic links never followed; partial and
  temporary files (`.part`, `.partial`, `.crdownload`, `.download`, `.tmp`, `.temp`, `~$…`, dotfiles,
  `…~`) are ignored.
- A file counts once its size and modification time have not changed for 2 s and it is not empty.
  The folder is listed on every `watchfiles` notification and every 60 s (lost notifications on
  network and cloud drives); when notifications fail, it polls.
- Once per file: a hash of folder, name, size and modification time is kept while the file is in
  the folder (meta `inbox_seen`), so a file is never picked up twice — not after a restart, and not
  after its letter was deleted. A file is remembered once its pickup is over (added, known or
  refused), never when Ordnung stops in the middle of it. Files already there when watching starts
  are picked up once. Content Ordnung already has adds nothing, and a letter in the trash stays there.
  A folder with more than 5,000 candidate files is not watched (`problem`).
- Every file goes through `add_file` with all limits (at most 50 MB + 1 byte is read),
  `source="folder"`; a name that is not UTF-8 is shown as Windows-1252. By default it is **held**:
  private and `held`, stored and read on this computer only, never sent to Claude until the person
  answers — *Read these N* (`release`: no longer private, queued for reading) or *Keep private*
  (`keep_private`: as "Keep private — no AI"; undone by `back_to_waiting`, an e-mail with the
  attachments kept private with it), for an e-mail with its held attachments (`ingest/held.py`). With
  `inbox_auto_read` files that **arrive** later are read at once; the files in the folder's first
  listing after it was chosen (meta `inbox_baseline`, dropped whenever `inbox_dir` changes — also by
  *Stop watching* — so a folder chosen again counts as chosen then; a restart keeps it) always wait,
  and in the replay-only demo every file waits. Only adding a held file again **by hand** (`answer_held`: the
  upload route, the CLI) answers for it — a copy in the folder never does. A held letter keeps waiting
  whatever happens to its local reading (stopped: stored next time; failed: `error`, still `held`).
  A PDF Ordnung itself rendered (a draft, remembered by SHA-256 when served) is refused, never added.
- Read-only: the folder is only listed and read (`O_NOFOLLOW`); nothing there is written, moved or
  deleted. A refused file (a limit, not allowed to read it) is logged with the reason
  (`folder.refused`) and not retried until it changes, a known one as `folder.known`; a missing or
  unreadable folder is reported (`FolderStatus.problem`, once in the activity log) and checked again
  every 30 s; one file's error never ends the watching. *Delete everything* pauses the watcher and
  clears the setting. Choosing Ordnung's own `<data>/inbox` creates it (`0700`).
- Today counts the waiting letters (`Dashboard.waiting`) and shows a card for them instead of "nothing
  needs you"; they are left out of the recent letters and the life areas, and the Inbox's nav count
  includes them.

## 9. Secretary — `secretary/` + `tick.py`

- **Daily tick** (startup + every 15 min, timezone-aware `clock.today()`): on day change move
  recurring to-dos whose date has passed on to their current occurrence, run triggers + reconcile,
  rebuild agenda; LLM brief regenerated by POST or tick
  when enabled; weekly LLM review in background if the last one is > 7 days old. SSE `day.changed`.
  On every check (not only on a day change) the morning desktop notification is shown once it is
  due, and — in `ordnung serve` — calendar sync sends what changed to a connected calendar (§ 12).
  While today's notification waits for its first try the loop wakes up for it (its time, or a
  minute after start-up) instead of sleeping the whole 15 minutes.
- **Triggers** (`run_triggers(store, today) -> dict[rule_id, list[Suggestion]]`, then
  `reconcile_suggestions` expires absent ones): `deadline_soon`, `overdue`, `contract_cancel_window`
  (send_by within 60 days), `price_increase_right`, `expiry_soon` (passport/ID 180 d, residence
  permit 90 d — apply before expiry, § 81 Abs. 4 AufenthG), `passport_before_permit`,
  `followup_due` (a sent letter's follow-up item became due), `please_check`, `dunning_escalation`,
  `scam_warning`, `tax_documents` (Jan–Jul), `calendar_outdated` (new dates since last .ics export),
  `proof_missing` (a cancellation or objection sent by Einschreiben has no tracking number and no
  proof two days on — not once an answer *from them* shows it arrived, the person closed the
  follow-up themselves, or 15 months passed (Deutsche Post no longer issues the delivery record); the
  person's own "I got an answer" keeps it, as it shows nothing about arrival; expires when either is
  added).
  `followup_due` and `confirm_cancellation` read the letter's proof: a recorded delivery day and the
  tracking number are named for the reminder; a later letter of the thread is asked about ("is it
  the answer?"), a confirmation of the cancellation is named as one; without proof they say what
  they said before.
  Fingerprint = rule_id + entity id + hash(triggering values). Savings are yearly-normalised.
- **Review** — compact snapshot → ≤ 6 new Ideas with refs to existing ids (validated; duplicates by
  fuzzy title dropped); `source="review"`.
- **Brief** — deterministic agenda + optional 2–3 sentence prose (cached per day + agenda hash). The
  code-written note is served as the ledger stands (a stored one only while it still says the same),
  and while letters from the watched folder wait unread it never says "all clear": "Nothing is due in
  the next 7 days from the letters that were read." (the count is not sent to the model). The model sees
  each to-do's dates labelled — `due`, and `send_by` when a transfer or letter must go out earlier — and
  a note that calls a send-by day "due"/"fällig" for the to-do it names (written out, or as "today",
  "tomorrow" or a weekday) is rejected for the code-written note, which says "send by …, due …" (a fee
  paid at an appointment is listed on the appointment's day).
- **Weekly session** (`secretary/week.py`, policy in its docstring; `views.weekly_session`) — a guided
  ~10-minute review composed from the agenda, the money summary, drafts and to-dos: *act now* (only when
  a deadline, task or appointment is overdue or to act on today, a missed send-by day included) · new
  since the last session (the first time: in the last 7 days; a letter waiting from the watched folder, or
  kept private and never read, is never "filed") · compare with the letter (to-dos whose date isn't
  confirmed against the letter; "The date looks right" vouches for the date only — a payment's amount is
  compared in its Pay panel, and *pay this week* warns about an amount by the GiroCode gate's own check) ·
  pay this week (transfers with their total, fees paid at an appointment, direct debits to cover) · post
  and keep proof (a letter's send-by day with the day it must arrive by, and once that has passed only the
  ways its own send advice allows the same day — never a fax or e-mail for a notice that must be signed by
  hand; then sent letters still waiting for their answer that lack the proof their channel needs,
  `drafts.proof.missing` — for an Einwurf-Einschreiben the delivery record, BAG 2 AZR 68/24 — and "delivered
  on …" once a proof shows it) · waiting for (the *Waiting for* page's open entries: replies, money and
  phone promises, overdue first; always linked) · decide in the next 30 days (contract decisions,
  objection/declaration/notice deadlines) · file or archive. What is set aside anywhere else — a letter
  with scam signs, an invoice a payment reminder took over, an e-mail's payment its attached bill repeats
  (`Ledger.is_set_aside`) — is never counted or listed. A snoozed to-do is put off, not away: it is
  listed where its date puts it, is overdue once its due date passes and keeps its letter open. Every
  row's day reads as Today words it (transfer by, send by, on, expires; money coming in is *expected*,
  never overdue); once a send-by day has passed but the due date (for a letter: the day it must arrive
  by) has not, the row says *act today* with the due date beside it, and a row is overdue only after its
  due date. It ends "N overdue" while anything is overdue — a to-do, a letter to send past the day it had
  to arrive by, or a *Waiting for* entry past its day — else "All clear until <next day to act>" — or
  "N things to do today" (`due_today`) when that day is today (after a missed send-by day too; contract
  decisions and snoozed to-dos count). Only the moments of the last session and of a dismissed prompt
  are stored (`meta`: `weekly_session_at`, `weekly_prompt_dismissed_at`, each `day|timestamp`). Today
  suggests it once — 7 days after the last session or "Not now", on a Sunday 4 days after — and only when
  a step has something to show; the session says the day it will next (`next_prompt`). Nothing is paid,
  sent or closed.
- **My numbers** (`numbers.py`, pure, policy in its docstring; `views.my_numbers`) — every number the
  letters show (references, the sender's identifiers in the stored reading, a payment IBAN — always where
  to pay the sender, checked like any IBAN; never a trashed or scam letter's), sorted by whose it is:
  *about you* (Steuer-ID, SV-Nummer, Krankenversichertennummer, Matrikelnummer, Rundfunkbeitrag
  Beitragsnummer, a tax office's Steuernummer, a number plate — never a number labelled as a child's or
  spouse's), identity documents (passport, residence permit, ID card — not a library card or student ID —
  with the expiry to-do's date, flagged when not confirmed, and the Ideas' renewal windows; a residence
  permit's note says what § 81 Abs. 4 AufenthG means before and after it expires), yours with one
  organisation (customer, contract, policy, member, employee, account — also an IBAN labelled as yours —,
  mandate, meter), a case reference (Aktenzeichen, Kassenzeichen, invoice/order/tracking numbers — listed
  while its thread has an open or snoozed one-off to-do; a fee paid at the appointment is no transfer) or
  the organisation's own (USt-IdNr., register, Gläubiger-ID, BIC, IBAN; a retailer's Steuernummer). A label
  that names a matter ("Kundennummer", "Bestellnummer") wins over a value's look. Check digits where a
  public algorithm exists: Steuer-ID (§ 139b AO, the BZSt's specification: ISO/IEC 7064 MOD 11,10 and
  the digit-repetition rule), Rentenversicherungsnummer (§ 147 SGB VI, § 2 Abs. 6 VKVV),
  Krankenversichertennummer (§ 290 SGB V), IBAN (ISO 13616; a misread IBAN still counts as one) — "check
  digit OK" or "does not check — compare with the letter". A call sheet per organisation adds its phone,
  e-mail and website, open cases and last letter; a number from an older letter links to it.

## 10. Ask — `assistant/`

MCP server (`python -m ordnung mcp --data-dir D`, read-only DB, lazy imports): `search`,
`get_document`, `list_items`, `list_contracts`, `get_party`, `timeline`, `money_summary`,
`explain_date`, `get_profile`, `today`, `get_my_numbers` — the ledger tools. `list_items` with a date range
(and no kind, or kind `deadline`) also lists the contracts' cancellation deadlines in that range
(`contract_deadlines`), unless the cancellation was sent or confirmed. The special cancellation window a
price increase opened — the one its Idea shows, computed on read; of several letters', the one that closes
first (in `contract_deadlines`, of those in the range) — is in the contract's `list_contracts` row,
`explain_date` (with its steps and rules) and `contract_deadlines` row, and in the price letter's
`get_document` (`special_cancellation`); `timeline` gives every letter's window's days
(`special_cancellation_send_by`, `special_cancellation_cancel_by`). It is flagged `needs_check` when the
letter's text does not write a day it is computed from — the effective date, and the letter's own date where
the window counts from being told (§ 57 TKG, § 40 VVG) — and gone once the cancellation was sent or
confirmed. Ask runs `claude -p` with `--tools ""`,
`--allowedTools` naming exactly these ledger tools (`mcp__ordnung__search`, …), `--mcp-config`
(absolute `sys.executable`, the server started `--ledger-only`), `--max-budget-usd 0.50`, 120 s
timeout. **Ask keeps to the ledger** (ADR 0011): the ledger-free rules tools (below) are not on its
server and not allowed, and the answer check reads only the ledger tools' results — a result of any
other tool, such as a rules tool's date computed from a `DateSpec` the model supplied, is never
record support and never makes an id citable. Citations
`[doc:ID]`, `[item:ID]`, `[contract:ID]`, `[party:ID]` are **validated**: the id must exist and
appear in the record part of a tool result of the same turn; otherwise it is stripped and logged. The
tool trace is streamed to the UI and persisted with the message. Markdown is rendered without raw
HTML and without remote images.

**Two channels and claim-level citations** (ADR 0008; the policy is the docstring of
`assistant/support.py`, the measurement `python -m evals.ask`, [evals-ask](evals-ask.md)).

- **Two channels.** Every tool result has Ordnung's record (`<ordnung_record>`: ids, types, statuses,
  due and send-by dates — none for a payment made in person (at an appointment, by card or cash on site,
  as the app's views read it), whose send-by date would be a bank transfer's —, a to-do's time only as a clock time, rules-engine contract dates, letter dates,
  amounts and terms with verified or person-given evidence, totals of verified amounts, code-written
  receipts and notes) and the letters' text by record id (`<untrusted_document>`: titles, summaries,
  names, quotes, warnings, payment details, page text, and amounts or terms read by AI from a photo or
  not found on the page, flagged `amount_unverified`/`terms_unverified`). A tool keeps each result
  within a size budget by leaving out rows (and says how many); the answer is checked against the whole
  result the model read.
- **My numbers.** `get_my_numbers` keeps every label and value in the letter text of the letter that
  shows it (a number is what the model read, never verified against the page) and puts what code decided
  in the record: each number's kind, group and check-digit result (with its code-written note and law),
  the letter and party ids to cite, an identity document's expiry as its to-do (`id`, `due_date`,
  `needs_check` when not confirmed against the letter) and an open case's next to-do (no `send_by` and
  `at_appointment` for a fee paid at the appointment; `direction: in` for money coming in, never
  overdue). It takes `section` (about_you, organisations,
  open_cases) and `organisation` (an id or name: that call sheet and its open cases only, never the
  person's own numbers), and bounds itself — at most 20 call sheets (latest letter first), 20 open
  cases, 20 numbers of a kind per sheet and no further sheet past 150 numbers — saying what it left out
  (`left_out`), so every `ref` it gives resolves. Letters marked private give nothing — not their
  numbers, nor their to-dos as a case's next step. Numbers are no date, time or amount, so the claim
  check leaves them as the model wrote them (a known limit: a misquoted identifier is not caught).
- **What the record says.** `money_summary` lists open payments with no stored due date and, apart, the
  demands of letters with scam signs (`do_not_pay`: not to be paid until the person has checked with
  the sender — a real sender whose bank details changed shows the same signs), with `today` and each
  fixed-cost contract's category. An invoice payment still to be made that a later payment reminder took
  over, or a to-do of an e-mail whose attached bill asks for the same payment, says so in its record
  (`set_aside`, with the reminder's or the bill's id, in every row and timeline entry): one payment, counted
  once. A payment the app says to decide on before paying — a rent increase's
  new rent (only owed once the person agrees, and paying it can count as agreeing, § 558b Abs. 1 BGB) or
  a late statement's back-payment (may not be owed, § 556 Abs. 3 S. 3 BGB) — carries the app's note in
  its record (`payment_note`, in every row and timeline entry) and is listed apart too
  (`decide_before_paying`), never among the upcoming payments or in the totals; the answer check repeats
  the note, in the answer's language and first in its note, under an answer that cites the to-do or its
  letter, or states its due date or amount through any record linked to it (its contract, its sender), and
  adds the app's scam warning under one that cites or states a `do_not_pay` demand. Only the new rent
  carries the note — never the current rent (its amount, or a date before the increase), which is owed and
  dated as ever — an undated one too, and a due date the person sets by hand keeps it. A rent contract's
  record — its `list_contracts` row, `explain_date`, its `money_summary` fixed-cost row and its reference in
  `get_document` and `get_party` — gives its rent in force and the next rent (`rent`): each open rent of
  `recurrence.py` point 9 that no other one replaces, as its to-do's row (its amount only when verified),
  with `next_rent`, the row of the rent that replaces it (`recurrence.replacement`) and `from_month`, the
  month it starts in — so "how much is my rent?" can name a statement's new total rent and its first due
  date as Ordnung's own, past `money_summary`'s 30 days too. A rent increase's new rent the person hasn't
  agreed to replaces nothing until they agree (§ 558b Abs. 1 BGB), so it is neither the next rent nor a rent
  in force but `proposed_rent`, with a note that says so and its `payment_note`. `explain_date`
  keeps an unverified contract's steps (which repeat its terms) in its letter text, like the terms, and
  leaves out the wording and quotes of a to-do whose letter is private or in the trash. `list_contracts` names a letter that says a contract is cancelled
  only as `cancellation_letter` (pending the person's confirmation). `if_not_cancelled` (also in
  `explain_date` for a fixed-term job or flat let) says a job ends by itself on its date (§ 15 Abs. 1
  TzBfG); ending it earlier by ordinary notice needs an agreed notice clause (§ 15 Abs. 4 TzBfG), and a
  written agreement (§ 623 BGB) or notice for cause (§ 626 BGB) end it early without one; everyone whose
  job ends must register as job-seeking 3 months before the end (§ 38 Abs. 1 SGB III, not in a company
  apprenticeship) — the record puts it as advice for whoever may claim unemployment benefit, since a late
  registration blocks the benefit for a week (§ 159 Abs. 1 S. 2 Nr. 9 and Abs. 6 SGB III). A flat let's
  record says notice may still be needed (§ 575 Abs. 1 BGB, with the § 549 Abs. 2 and 3 BGB exceptions
  as examples) and that courts often read the agreed end date as a waiver of ordinary notice until then
  (BGH VIII ZR 388/12), so leaving earlier may not be possible; `explain_date` notes that the catalog's
  `fixed_term` rule applies to a flat let only where § 575 or § 549 allows it. Once the end date of an
  active job or flat let has passed, the record never says it "ended": it may continue by conduct
  (§ 15 Abs. 6 TzBfG, § 545 BGB), and a flat let without a written reason never had a fixed term (§ 575
  Abs. 1 S. 2 BGB).
- **The contract page says the same** (resolved in review round 1 of phase 2): the rules engine's summary
  of a fixed-term flat let says it ends without notice only with a written legal reason (§ 575 Abs. 1
  BGB), else it counts as open-ended and needs notice; an active flat let or job past its end date "may not
  have ended" (§ 575 Abs. 1 S. 2, § 545 BGB; § 15 Abs. 6 TzBfG), never "ended" (`rules/explain.py`); the
  catalog's `fixed_term` rule is titled "Fixed-term contracts" and its text names § 575 BGB and the
  continuation rules. The sample life has no fixed-term lease, so neither the demo nor the benchmark shows it.
- **Nothing unchecked is shown.** The answer's words are never streamed: the UI and the CLI show only
  the tool trace (which tools ran, the words searched for with every word of a value the check reads —
  any word with a digit, a part of a month — shown as "…", and the date range looked at) and "Writing
  the answer — it appears once Ordnung has checked it". The check runs off the event loop and fails
  closed: if it cannot read an answer, the stream ends with an error and nothing of it is shown.
- **What the check reads.** The answer as it will be shown (bidirectional controls removed; Markdown,
  escapes and invisible characters dropped; soft-wrapped lines joined where a value spans the break; a
  line starting with a day read whole; digits of any script read as digits), with every date, time and
  amount form of the policy. A run of digit groups shaped like a date that is no calendar date
  (`31.02.2027`, year 0), a number too long to be an amount, a day, one word and a year whose word is no
  month the check knows (`31 décembre 2027`: Ask answers in the question's language, the check knows
  English and German month names) — also joined by marks or none, or with the word first (`31-dic-2027`,
  `dic-31-2027`) —, a month and year or a month before its day in another offered language (`décembre
  2027`), an Islamic or Solar Hijri date, a month in Chinese numerals, a day and month joined by a slash
  with no year (`31/12`), a day in words before or after a month, an amount in another currency or with
  another language's scale word (`1412 zł`, `412 mil €`), an hour next to another language's part of the
  day (`下午3点`), and a clock time moved by words (`halb 10 Uhr`) are *unreadable* and never supported —
  never an exception. A scale glued to a currency (`412 T€`, `€412M`), the euro named in another script
  (`1412 евро`) and an hour word of another offered language (`15 heures`, `15時30分`) are read as the
  amount and time they are. What stays unread is listed
  in the policy's limits. The date forms the web formats inside an answer, its placeholders and its month
  words are lists both test suites read.
- **What stays.** Each date, time or amount must be in the record part of a record its sentence cites
  (a letter's includes its to-dos, a contract's its letter, a person's their to-dos; a sentence without
  citations takes its line's, a list item its lead line's). Today only in a sentence that cites no record,
  not even one it inherits; Ordnung's totals only in a sentence without a citation of its own; a year that
  stands in no other value only when a cited record has a date in it. A sentence without citations of its own may state a
  value of a record the answer cites; when its values belong to one record, the check adds that record's
  citation (never a scam record's; none for several) — counted in the note only when the sentence did not
  already inherit it. A cited record's flagged, unverified amount and a value the person typed are shown
  in quotation marks as unconfirmed.
- **What is left out.** Every other value: as "[date only in the letter]" / "[time …]" / "[amount …]"
  when the letter text of a record the sentence cites holds it (the note says to open the letter),
  whatever the wording, and otherwise as "[date left out]" / "[time left out]" / "[amount left out]". The
  edit replaces only the value — the sentence's full stop and a citation after it stay. A sentence that
  keeps no value is removed unless all it leaves out is its letter's (a warning about injected text); a
  § — or a law cited in words ("section 999", "Paragraf 999 AO", "Art. 99 EGAO") — that is not in the
  rules catalog, among `IDEA_LAWS` or in a record removes its sentence. Within its
  sentence a left-out value is never shown; another sentence without a citation of its own can still
  state the same date when a cited record holds it anywhere in its record part (literal support, listed
  in the limits).
- **The note.** What was left out, quoted or cited, the citations removed and the weekday names
  corrected, and why — worded as what is true, for a non-expert ("isn't among the dates and amounts
  Ordnung saved for the linked letter, to-do or contract"; "a letter's text has it") — and, for the records concerned, their own dates or amounts on file (never
  a demand not to pay), in the answer's language under its label ("Checked by Ordnung:" / "Von Ordnung
  geprüft:", sent as `note_label`). It travels in its own `note` field of the `done` event and the stored
  thread; the UI shows only that field. An answer the check did not change says "Dates and amounts
  checked against your records" ("Daten und Beträge mit Ihren Unterlagen abgeglichen" under a German
  label) — what was checked, not every claim. A checked answer is stored with the label (alone when
  nothing changed), so an answer stored before this check is never shown as checked; a model sentence
  that starts like the note — also with look-alike letters or across a soft line break — is left out.
- **The prompt** (`ask_system` version 9: since 7 a to-do's own words are letter text, since 8 a year
  standing alone in its title too, since 9 a matter's open to-dos and appointments are looked up before
  the answer says what to do) says what the check does: a value only a letter holds is not
  stated (it would be shown as "[… only in the letter]", however the sentence frames it), only a cited
  record's flagged amount and the person's own words stay as quotes (a `terms_unverified` contract's
  term dates are left out, its cost stays), today's date is checked like any other date, each sentence
  and list item cites its own record, the record's legal statements keep their hedges, German answers
  use "Sie", and a `do_not_pay` demand is not to be paid until checked with the sender. It names every
  ledger tool (`get_my_numbers` too) and the app's buttons by their labels ("Add your dates to your
  calendar"). Every demo and benchmark answer was recorded with it.

**Rules tools** (`assistant/rules_tools.py`, no ledger): `compute_deadline(spec, document_date?,
sender_kind?, sender_name?, remedy_type?, region?, recipient_region?, received_date?, today?)` —
the extractor's `DateSpec` (validated strictly: unknown keys are refused, every date must be
`YYYY-MM-DD`, `true` is no number) → the rules engine's date with steps, rule ids, citations,
warnings, confidence and hints naming a missing argument (never one that was given; for a holiday
region the one the engine reads: `recipient_region` for a payment to a company or person, else
`region`), and `assumed` (today, letter date, the arrival day the period ran from and where it came from — none
when it did not run from one — an arrival day given but not used, the delivery law, the holiday
calendar and which argument's Land it follows). The day a period runs
from is checked: when it runs from arrival, the day used — a delivery day the letter states
(`spec.anchor_date` not before the letter's date) or `received_date` — after today is refused, and
one before the letter's date or more than 14 days after it gets a warning and one level less
confidence (a late one the period did not run from gets the warning only: the date shown does not
rest on it, the later date in the engine's note does); an arrival day the engine did not use is
named. A letter dated after today gets a
warning and one level less confidence. Whether the sender has deemed delivery at all is the
engine's rule, as in the app (a private sender's letter counts from its arrival — for a kind a public
body may be filed as, or a period whose words name an administrative act, never later than from
the day a letter usually counts as delivered; an unknown one, `other` included, keeps the earliest
plausible deemed delivery). A court is a court by its name, as in the app (`routing.is_court`, whatever
`sender_kind` the model passed — a court is no `PartyKind`): its periods run from formal service, never
from a delivery fiction, are never `high`, a labour court's order gives one week, and a court order is
recognised from the remedy and the period's own words by the app's policy; `assumed.delivery_law` names
formal service (§ 180 ZPO) when the period ran from it (not for a court's fixed date) and the hint asks for
the envelope's date; `assumed.holidays_from` names the Land the rule applied uses (a payment's and a
withdrawal's: the payer's or consumer's, `recipient_region`; a Kündigungsschutzklage's: only a holiday both
Länder have). The spec help says how to pass a
formally served letter (yellow envelope: `anchor: receipt`, the envelope's date), and a result that
applied deemed delivery to a posted letter says it would not apply then (a warning) and what to pass
if it was (a hint). A stated posting or delivery day (`spec.anchor_date`) can only be checked against
the letter's date: without `document_date` the result says so, asks for it and has one level less
confidence. Warnings say what the person should know, in the tools' voice (the engine's "tell us"
and "enter the envelope date" are the app's); how to call again is a hint. Holidays of only part of
a Land are the engine's warning, as in the app. `german_holidays(year, region?)`;
`add_working_days(start, days, day_type, region?)` (its disclaimer says it is a calendar count, not
a deadline); `check_iban(iban)` (an invalid one gets the app's advice: misprinted, misread or fake —
ask the sender before paying; a valid one says it tells nothing about the owner, and mentions the
bank's payee-name check before a euro transfer only where the account's bank has to answer it by
today — in the euro area since 9 October 2025; in CZ, DK, HU, PL, RO and SE only from 9 July 2027 and in
Bulgaria from 1 January 2027, which the note names; elsewhere it says there may be none — and in
every case that a check the bank reports "not possible" confirms nothing (Art. 5c(9), 16(9) Reg. (EU)
No 260/2012 as amended by 2024/886); a printed `IBAN:` label and
invisible characters ignored; country from the full SWIFT registry — any other two letters are not
an IBAN — registered length, mod-97, bank code where the format shows it; pure code in
`money/iban.py`). Unknown tool arguments are refused and argument errors are plain words. "Today" is
the server's (`ORDNUNG_TODAY`, else the date in Germany): a result — whether a deadline has passed,
its send-by date — is always for it; a caller's `today` that differs never replaces it (a deadline
runs to midnight German time: a later day would make a live deadline look missed, an earlier one an expired
deadline read "send it today"; an arrival on a day ahead is still accepted) and only adds `for_today_given`
(that day's send-by date and whether it had passed) and a warning, and a server started pinned (`ORDNUNG_PIN_TODAY=1`, as the benchmark starts
it) does not use it at all. Every result carries "Information, not legal advice". The full server
serves them next to the ledger tools (counting from the ledger's day), and its instructions and
`compute_deadline`'s description say that a letter in the ledger keeps its stored date (quoted from
`list_items`/`explain_date`, which may rest on a confirmed arrival day or a corrected sender) —
except Ask's own server (`--ledger-only`, ADR 0011): Ask quotes stored receipts and never computes a
date — a rules tool's date is computed by code, but from a `DateSpec` the model passed (possibly read
from an injected letter), and has no record to cite, so it could never support a claim; `ordnung mcp
--rules-only` serves only them — no data folder, nothing personal.

**Other clients** (`assistant/mcp_install.py`). `ordnung mcp install --client claude-desktop|
claude-code [--rules-only|--with-ledger] [--data-dir D] [--config PATH] [--write]` adds the rules
tools (the default) or, with `--with-ledger`, the full server, which needs an existing database and
shows the privacy warning before anything is printed to copy or written (`--data-dir` without
`--with-ledger`, and options put before `install`, are refused rather than ignored). It prints the
entry, the target file (Claude Desktop: macOS `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows `%APPDATA%\Claude\…`, Linux `$XDG_CONFIG_HOME/Claude/…`) and, for Claude Code, the
`claude mcp add` command (rules tools `--scope user` or a project `.mcp.json` entry; the full server
`--scope local` only, never a shared `.mcp.json`) and the matching `claude mcp remove`. Printed
commands are quoted for the platform's shell. `--write` merges only `mcpServers.<name>`
(`ordnung_rules` or `ordnung`), backs the file up first, writes atomically, keeps its permissions,
refuses invalid JSON or a file that is not UTF-8 without touching it, and never creates Claude
Desktop's settings folder. When the file already has the other Ordnung server, the command says so
(above all when the ledger stays readable next to the rules tools), and `--remove-ledger` (rules
tools only) takes the full server's entry out in the same backed-up write.

## 11. Letters — `drafts/`

Kinds: `cancellation`, `objection` (Einspruch/Widerspruch — for a court order or a landlord's notice
the remedy the law gives it), `general_reply`, and the template letters `withdrawal`,
`extension_request`, `payment_plan` (Stundung under § 222 AO to a tax office), `defect_notice`
(§ 536c BGB), `data_access` (Art. 15 GDPR, the free SCHUFA copy), `receipts_inspection` (§ 556 Abs. 4
BGB), `deposit_return` (the profile's IBAN) and `address_change`, written entirely from fixed German
and English sentences (`drafts/template_letters.py`) filled from `LetterDetails` (`POST /api/drafts`
`details`); a missing required fact is refused with what to add, and so is more time against a
deadline the law sets (a court order, a dismissal) or instalments offered to a court instead of the
claimant (`compose.template_refusal`). Instalments on a court order go to its claimant, typed in: the
letter stays linked to the order (its Geschäftsnummer and date, "aus dem Mahnbescheid vom …"), the typed
claimant — never the court — is its recipient (`compose.to_claimant`: a typed name that is or may be a court
is refused like the court), and the offer's notes say the order's own deadline still runs, with its date
(`compose.court_order_note`). An objection to a court order goes to the court: when the letter's sender, as
filed, is no court (a Mahnbescheid re-filed from what was read as the claimant's reminder) and its
instructions name none, the person types the court and the letter is refused without it
(`compose.objection_to_typed_court`, § 694, § 700 ZPO). A withdrawal's date is the 14 days while they run, even when
the person says the instructions were missing (the 12 months and 14 days are then a note). An
objection to a court payment order objects to the whole claim (a partial one goes on the court's
form, which the note says); the application to suspend enforcement is added only when the person
ticks it (`suspend_enforcement`), never from the wishes, and never against a payment order.
Single-line facts (what was ordered, the billing period) have their line breaks collapsed. A letter's title never becomes what was ordered, the
deadline to extend is never one the law sets, and a letter whose sender isn't in Ordnung takes a
typed recipient; letters flagged as a possible scam aren't offered. Compose → `DraftOutput
{subject, body, body_translation, enclosures, notes_for_user}` (letter in German for German
recipients; translation in the user's language) → checks (`has_reference`, `has_dates`,
`recipient_complete`, `sender_complete`, `no_placeholders`, `language_matches`) → DIN 5008 Form B PDF
(fpdf2, DejaVu). `send_guidance` (rules): send-by date, channel ranking (provider's cancel button
§ 312k BGB; text form/email where allowed § 309 Nr. 13 BGB; signed paper where required: rent § 568,
employment § 623 BGB; "Einschreiben Einwurf — keep the receipt"; the objection to a court order in
writing or at online-mahnantrag.de, never by e-mail — nor any other letter to a court; a withdrawal
only has to be sent in time).
Marking sent asks for channel + date and creates a follow-up item 21 days later (35 for a data access
request, which has one month from receipt).

**Proof of sending** (`drafts/tracking.py`, `drafts/proof.py` = the policy, `drafts/sent.py` = the
service; migration 0002). A registered letter (only it: marked again with another channel, the number
goes) takes an Einschreiben tracking number, when marking it sent or later: normalised (NFKC, every
decimal digit of any script as ASCII, spaces, dots, hyphens, slashes dropped; upper case; only ASCII
stored; shown grouped with no-break spaces so it never breaks inside), UPU S10
(`RT 123 456 785 DE`) accepted only with the right check digit (weights 8 6 4 2 3 5 9 7, 11 − sum mod
11; 10 → 0, 11 → 5), not starting with R kept with a note; an Einschreiben bought online
(Internetmarke) has the 20 characters next to the stamp's square code (`A0 0123 45D6 0000 123C EC`,
digits and A–F), kept unchecked with a note; twelve digits kept unchecked with a note; anything else
refused with what a number looks like; the web app checks the same as the person types (an online
stamp's number isn't called a mistake before its 20 characters are typed). *Change how or when you
sent it* with the number field emptied removes the number (`tracking_number: ""`; left out, it is
kept), and a sending day after a recorded delivery is refused. Proofs (`posting_receipt`, `delivery_record`, `return_receipt`,
`fax_report`, `sent_email`, `cancel_confirmation`, `other`; ≤ 20 per letter, each file once; a day
that isn't in the future and — for a delivery record or return receipt — not before the sending; a
note) are files uploaded through the normal intake as documents with direction `outgoing`,
`source="proof"` and *Keep private (no AI)* on — never sent to a model, never listed or counted as
letters (Inbox, search, Today and its letter count, timeline, life areas; filtered in SQL), opened on
their own page under their letter (`/letters/{id}/proofs/{doc}`), deleted with their letter unless the
person keeps the files (`DELETE drafts/{id}?keep_proof_files=true`: they become their own private
documents). A file already in Ordnung (the same bytes) is linked as it is and said to be so: made
private now if no model call ever carried it (`llm_calls`, a cached answer or a transcribed page —
also a reading that failed, or paused on a rate limit, after the model had it), else named as given
to Claude (`notice`) — "kept private" is never claimed for it, also not when it was marked private
later; one still waiting from the watched folder (`held`) gets the answer *Keep private* then, so
*Read these* never offers a proof to Claude; the same file uploaded to the Inbox again says which
letter it is proof of. Removing a proof
(or deleting its letter without keeping the files) deletes the file for good, after a confirmation
that names it and offers to download it first (ADR 0014). A proof of
the sending (posting receipt, fax report, sent e-mail, cancel page) whose day differs from the sending
day is pointed out (`conflicts`: one of them is wrong), as is a delivery before the sending; the
upload form starts it on the sending day. Each kind states what it shows and
what it doesn't; *What would make it stronger* depends on the channel (Einschreiben: tracking number,
posting receipt, and the delivery record or return receipt — the posting receipt with the online
status alone was not accepted as prima facie proof of arrival, BAG 30.01.2025 2 AZR 68/24; bought
online: no posting receipt exists, so a printout of the online stamp, and for a deadline the post
office counter; fax: the
transmission report; e-mail: the sent message; cancel button: the saved page and the provider's
confirmation, § 312k Abs. 3/4 BGB; a plain letter: nothing shows arrival, said once). The delivery
record is suggested only within 15 months of posting (Deutsche Post issues it that long); after that
only the return receipt is mentioned. Only an **answer from them** counts as a sign of arrival: a
confirmation of the cancelled contract, or a letter the person names as the answer. The person's word
alone ("I got an answer — close this", `POST drafts/{id}/answered {doc_id|null}`, stored as
`answered_on`/`answer_doc_id`, closes the follow-up; `DELETE` takes it back and reopens it) closes the
wait but shows nothing about arrival: the delivery record is still suggested while it can be had, and
the timeline and Nachweis say "marked as answered" ("Als beantwortet vermerkt (Angabe des
Absenders)") on the day they said so. A later letter that is merely in the same thread is a
*possible* answer: shown to the person (a "?" line on the timeline), never counted as arrival, never in
the Nachweis. The timeline lists only what the person recorded (drafted, sent, tracking number, each
proof on its day, the confirmed answer); a proof without a day is listed apart with the day it was
added, never put on that day; the days a letter was drafted and a proof added are the person's local
days (their time zone), never after today. **Nachweis** (`GET drafts/{id}/proof.pdf`, named `Nachweis <subject>
<day>.pdf`, `drafts/pdf.render_nachweis`): a German summary page with the timeline, the proofs without
a day apart, and the caveat (kept on one page), then the letter, then every proof file (PDF pages
merged, images placed on a page; pypdfium2 under the intake lock, fpdf2). The letter is "as sent": the
first marking keeps what its PDF showed of the sender (`drafts.sent_profile`: name, e-mail, phone) and a
sent letter's text can't be edited (`PATCH` answers 409), so the Nachweis and the letter's PDF show
what went out; a letter from before that is captioned "as recorded in Ordnung", and one sent by the
cancel button, a portal or e-mail as "the text as written in Ordnung — not sent as a letter" (e-mail:
the sent e-mail shows what went out). Ordnung never says a proof is enough: every overview and the PDF
carry the caveat that proof of sending never shows what was inside and that sufficiency is for a
court to decide.

**Waiting for** (`secretary/waiting.py`, derived on read, `views.waiting`, `GET waiting`): (1) each
sent letter waits for what its kind asks for (an address change for nothing; a deposit letter for an
answer on *when* the deposit will be settled — a landlord may take more than six months, BGH VIII ZR
71/05, and the entry says so; an objection for the acknowledgement — an authority's decision often
takes months, and an action for failure to act is as a rule possible only after three months, § 75
VwGO, § 88 Abs. 2 SGG, or six against the tax office, § 46 Abs. 1 FGO, which the entry says unless
the objection answers a court or a landlord) until the date of its follow-up to-do, and is closed by the person's
word that it was answered (also by phone or e-mail); (2) open one-off payments to the person (to-dos of kind payment, direction `in`, no
recurrence — a deposit, a refund; not from a scam-flagged letter) until marked received; (3) call
notes' promises with a day. Status: *overdue* after the day, *answered* when a linked letter arrived
(same thread on or after the sending/call day, or the confirmation of the cancelled contract) — the
entry names it and says so, but closing stays the person's click (ADR 0006) — *closed* once the
follow-up is done/dismissed, the letter marked answered or the promise marked kept (then not listed).
Order: overdue, waiting by day (undated last), answered. An entry carries its thread (`case_id`), so
"call them — and note what they say" comes with *Note a call*: the person's drawer opens with the form
and that thread chosen (`?party=…&call=<thread|new>`).

**Call notes** (Gesprächsnotizen, `secretary/calls.py`, `GET/POST calls`, `PATCH/DELETE calls/{id}`):
when, with whom, what was said, what was promised (with a day and an amount), for a person or
organisation and/or a thread; typed by the person, no model call; a promise with a day is waited for;
*kept* is the person's click and can be taken back.

## 12. Calendar — `calendar/ics.py`
One-click `.ics` export of open dated items + contract send_by dates, VALARMs from
`profile.reminder_days`, stable UIDs, per-item `.ics`; guides for Google/Apple/Outlook import. Left out:
to-dos set aside (`Ledger.is_set_aside`), open one-offs whose date had long passed when their letter was
read (a backfilled archive's 2025 deposit), and the send-by dates of contracts whose cancellation was sent
or confirmed. The Timeline marks money coming in "Money in" (never overdue) and a to-do set aside by why
("Replaced by the reminder"); the Settings preview calls a past event "Date passed";
`meta.last_calendar_export_at` drives the "3 new dates since your last calendar update" card.
Browser notifications (Notification API) while the app is open. Local feed URL documented as
"desktop calendar on this computer" only.

**Reminders while Ordnung is closed** (`notify/desktop.py`, `autostart.py`; the policies are in
their docstrings):
- **Morning desktop notification** — setting `desktop_notifications: off | discreet | full`
  (default `off`; the web app switches it on as `discreet`) and `desktop_notify_time` (`HH:MM`,
  default 08:00). Built by code from `build_agenda` — no model call: overdue, due today or in the
  next 7 days, contract decisions whose send-by day is within 7 days; nothing due, nothing shown.
  Discreet: "Ordnung" + counts only, today's apart ("3 due today · 4 overdue · 5 more this week").
  Full: the counts in the title, the first three things with amounts and days — what ends today
  first (deadlines, decisions and appointments before tasks, tasks before payments), then what is
  overdue, then the week by day ("Decide on FitWell: cancel today · Pay the parking fine €30 —
  overdue · Dental appointment on Thu 10:30 · and 1 more"; an appointment says its time). Once per
  local day at the chosen time (the tick wakes up for it), or a minute after start-up when Ordnung
  wasn't running then; a notification the system couldn't show is tried again at the next checks
  (3 a day at most) and the last failure is shown in Settings; a missing tool uses the day up;
  never in the demo. Shown with `notify-send`, `osascript` (fixed script, texts as arguments) or a
  Windows PowerShell toast (fixed script, texts in environment variables) — argument lists, never a
  shell; a missing tool or an error breaks nothing. A tool that took it counts as *sent to the
  system* (the activity log says so): the system may still keep it back (macOS without permission
  for Script Editor, Focus, Do not disturb), so the test's toast and the card say where to look
  per system. Settings shows today's text in both modes and can show a test notification (it
  doesn't use the day up); the toast only promises the morning one once the switch is saved.
- **Start at login** — `ordnung autostart enable|disable|status`: one entry per system (systemd user
  unit + `default.target.wants` link, LaunchAgent, Startup-folder `.cmd`) running
  `<python> -m ordnung --data-dir D serve --no-browser`, written by Ordnung itself (no service
  manager is run), printed with its path; standard output (the sign-in link with the token) is
  discarded, errors go to the journal / `~/Library/Logs/ordnung.log`. The `.cmd` switches cmd.exe
  to UTF-8 (`chcp 65001`) before any non-ASCII byte, so a user folder like `C:\Users\Jürgen` works.
  Settings offers the command for *this* data folder (`--data-dir` when it isn't the default one;
  none in the demo). `enable` says when the morning notification is still off. All entries (and
  backups and restored files) are written through binary descriptors (`O_BINARY` on Windows).
- **Calendar sync (CalDAV, opt-in)** — `calendar/caldav.py` (policy in its docstring, ADR 0013).
  The person connects one calendar in Settings → Calendar: an address (a calendar's, an account's or
  just the provider's — Ordnung finds the calendars that take events: the address itself, the
  collections inside it, or `current-user-principal` → `calendar-home-set` from the address or
  `/.well-known/caldav`, RFC 6764/4791; a redirect of the typed address — a web root's login page —
  doesn't end the search), a user name and an app password. `https://` (or `http://` to loopback);
  the address is checked with `PROPFIND` before the password is stored, in the OS keyring
  (`calendar/secrets.py`, `keyring` is a dependency; the `null`/`fail` backends, `keyrings.alt` and
  any backend below priority 1 are refused; asking whether there is a store reads no secret),
  never in the database; unavailable in the demo. What is sent: the events of the `.ics` export,
  one resource `ordnung-<id>.ics` each (one VEVENT + its VTIMEZONE, no METHOD). Mode `discreet`
  (default): date, time and alarms kept; title "Ordnung: deadline" / "…: payment" / "…:
  appointment" / "…: money in", "— check the date" added for a date Ordnung couldn't confirm, a
  fixed description, no location or categories. Mode `full`: the calendar file's events (which
  leave out invoice payments a later payment reminder took over, as the agenda does). While a
  calendar is connected the `calendar_outdated` Idea ("import the calendar file") is not raised:
  the same UIDs imported by hand would clash. Idempotent: resource names from the stable UIDs; meta `calendar_sync`
  (`CalendarSyncState`: address, user, mode, the data folder's connection id, SHA-256 per sent
  event, last report, paused, whether the password was there when last needed, the day of the
  last check) — only changed events are sent, events that left the export are deleted, only
  Ordnung's own resources are ever touched. Runs on connect, on "Sync now" and at every tick check
  of `ordnung serve` (nothing changed: nothing sent and the keyring not read); once a day and on
  "Sync now" a `calendar-multiget` REPORT of Ordnung's own resource names finds events that went
  missing (deleted in the calendar app, or by another Ordnung) and sends them again
  (`CalendarSyncReport.missing`; a server that can't answer is not asked); entering the password
  sends every event again. A refused or missing password pauses automatic runs until a manual sync
  or a new password; a 400/403 that names the UID is a conflict. The keyring account is
  `<user> @ <address> #<connection>`; a restored backup gets a new connection id with the calendar
  sync waiting (no password, no events claimed, paused) — it never reads or deletes the original's
  password or events. The status (`GET /api/calendar/sync`) never reads the keyring.
  "Delete everything" first removes Ordnung's events from a connected calendar and its password
  from the keyring (refused, nothing deleted, when that can't be done). httpx, TLS
  verified, Basic auth, no redirects (same-host redirects only while discovering), 20 s timeout,
  answers ≤ 1 MiB and never with a DTD. Settings previews every event in either mode first.

## 13. HTTP API — `api/`

Security: bind 127.0.0.1; `Host` allow-list; **session token** (Jupyter style: `serve` prints/opens
`/?token=…` → HttpOnly SameSite=Strict cookie; CLI reads `<data>/server.json` {port, token, pid});
non-GET requires header `X-Ordnung-Client`; reject `Sec-Fetch-Site` not in {same-origin, none} and
foreign `Origin`; strict CSP on the SPA; GETs are side-effect free; originals served with `nosniff`
and `attachment` unless PDF/JPEG/PNG/WEBP; `--no-token` for tests only.

Endpoints (all under `/api`): `health`, `profile` (GET/PUT), `settings` (GET/PUT), `onboarding`
(POST), `documents` (POST upload `files[]`, `combine`, `private`; GET list), `documents/{id}`
(GET detail / PATCH / DELETE), `documents/{id}/file`, `documents/{id}/pages/{n}.jpg`,
`documents/{id}/thumbnail.jpg`, `documents/{id}/reprocess` (POST), `documents/{id}/trace`
(`?run=` a reading's trace id; default the newest kept: its steps, their model calls and the kept
readings), `documents/{id}/trace/compare` (`?base&head`: what a later reading decided differently;
`base` defaults to the newest earlier reading that was done, not a paused or stopped attempt),
`traces` (every kept reading, for the data export), `items` (GET/POST),
`items/{id}` (PATCH/DELETE; PATCH with `due_date` sets `due_date_source=manual`, `user_modified`),
`items/{id}/confirm` (POST: grounding=user), `items/{id}/girocode/confirm` (POST: the transfer details
the person compared with the paper letter; 409 when they changed or the code is refused for another
reason), `items/{id}.ics`, `contracts` (GET), `contracts/{id}`
(PATCH), `parties`, `parties/{id}`, `cases/{id}`, `timeline?from&to`, `lanes?from&to`, `dashboard`,
`suggestions` (GET), `suggestions/{id}` (PATCH status/snooze), `suggestions/review` (POST),
`brief` (GET cached — a code-written note current —, POST regenerate), `numbers` (GET: My numbers), `week` (GET: the weekly session),
`week/done` and `week/dismiss` (POST: remember the session or a "Not now"; answer the session), `ask`
(POST → SSE), `chat/{thread_id}`, `drafts` (GET/POST), `drafts/{id}` (GET/PATCH/DELETE),
`drafts/{id}/pdf`, `drafts/{id}/preview.png` (the PDF's pages as one image: the print preview),
`drafts/{id}/sent` (POST),
`drafts/{id}/translate` (POST: translate the edited letter again, purpose `draft`; 409 in the
replay-only demo), `drafts/{id}/proof` (GET the proof overview), `drafts/{id}/tracking` (PUT
`{tracking_number}`, `null` removes; 422 with the reason for a wrong check digit), `drafts/{id}/proofs`
(POST multipart `file`, `kind`, `on_date`, `note` → 201), `drafts/{id}/proofs/{proof_id}`
(PATCH kind/day/note — `null` removes the day or the note —, DELETE), `drafts/{id}/proof.pdf` (the Nachweis), `drafts/{id}/answered` (POST
`{doc_id}` / DELETE), `waiting` (GET), `calls`
(GET `?party_id&case_id` / POST), `calls/{id}` (PATCH `{kept}` / DELETE),
`calendar.ics`, `calendar/exported` (POST), `activity`, `usage`, `rules`, `jobs`,
`events` (SSE), `data` (DELETE `{"confirm": "DELETE"}`: "Delete everything" — a connected
calendar's events and app password go first (`calendar_events_removed`; 409 and nothing deleted
when that can't be done), then empties the database in place and removes Ordnung's files, keeping
the lock and `server.json`; 409 in the demo),
`calendar/sync` (GET: available here, the connected calendar, the last sync; PUT `{url, username,
password|null, mode}`: connect or change the mode — checked with the server, the password to the
keyring, then sent), `calendar/sync/preview?mode=` (every event as it would be sent),
`calendar/sync/discover` (POST `{url, username, password}`: the calendars that take events),
`calendar/sync/run` (POST: send what changed now), `calendar/sync/disconnect` (POST
`{remove_events}`; refusals carry `code`: `address`, `auth`, `not_calendar`, `network`,
`not_connected`, …; the demo answers 409),
`reminders/desktop` (GET: the notification tool, today's text in each mode, the last day shown, the
last failure, whether it is the demo, the start-at-login entry and the command for this folder), `reminders/desktop/test` (POST `{mode}`: show it now), `backup` (GET: what a
backup would hold; POST `{passphrase}`: the encrypted backup file, streamed while it is made — the
passphrase is never stored, logged or echoed),
`demo/tour` (GET tour state), `demo/mail` (GET tray, POST `{id}` → ingest a tray letter),
`folder` (GET: the watched folder, its state or problem, `auto_read`, `can_read`, how many letters
wait, the suggested `<data>/inbox`, the last files it brought in), `documents/held/read` and
`documents/held/keep-private` (POST `{doc_ids}`, at most 500: the person's answer for the waiting
letters they saw, a held e-mail's held attachments included; ids that no longer wait come back as
`skipped`; *read* is `409` in the replay-only demo; the web app sends more ids in several requests),
`documents/held/wait` (POST `{doc_ids}`: undo *Keep private* — letters kept private from waiting,
never read since, wait again; an e-mail with the attachments kept private with it; a letter's
`DocumentDetail.can_wait_again` says whether it can). `settings` takes `inbox_auto_read` and `model` (trimmed;
no spaces, not starting with a dash, else 422 with the reason); a waiting letter can't
be reprocessed or made non-private by `PATCH` (`409`) — only an answer changes it.
A letter's detail carries `girocodes`: per payment to-do a GiroCode (`ready`, with the EPC payload)
or why there is none (`blocked`, a reason code and plain words), worked out on read (§ 21).
Contracts carry `cancellable` + `cancel_hint`, worked out on read (not for the broadcasting fee,
obligations towards authorities or a job — a job gets "Draft resignation").

View models (in models.py): `Dashboard`, `TimelineEntry`, `Lane{id,label,area,bars[]}`,
`LaneBar{id,label,start,end,kind,marker_dates[],ref}`, `DocumentDetail`, `PartyDetail`,
`CaseDetail`, `UsageStats`, `Health`, `RuleInfo`, `TourState`, `MailTrayItem`, `EmailAttachment`,
`FolderStatus`, `FolderPickup`, `DocumentTrace`,
`TraceRun`, `TraceSpan`, `TraceComparison`, `TraceExport`. Live event `folder.updated` {state, doc_id?, held?}.

Contract details: list endpoints answer plain JSON arrays. `health` carries `rules_last_checked`
(the catalog's `LAST_CHECKED`, shown as "Based on the law as of …"); `health?probe=1` ("Run check")
adds the doctor's `checks` plus one tiny live call, at most once a minute (else `429` +
`Retry-After`). `ask` streams default SSE `message` events whose JSON carries `type`: the tool trace,
one `text` event without text while the answer is written (its words are never sent before the
check), then `done` with the checked answer `text`, the check's `note`, `citations[{type,id,label}]`,
`message_id`, `thread_id` — or `error`. `events` payloads are
declared per event name in `models.ServerEvents`. `web/openapi.json` (`ordnung openapi`) and the
generated `web/src/api/schema.d.ts` are the web app's source of API types (`make openapi`); tests fail
when they are stale, when a mock route or response differs from the schema, or when a GET endpoint's
JSON doesn't validate against it.

## 14. Web app — `web/`

Navigation (7 + footer): **Today · Inbox · Timeline · Contracts · My numbers · Letters · Ask**; footer:
Settings (incl. "Privacy & AI usage" with the activity log). The phone tab bar keeps six sections; My
numbers is an icon in the phone top bar (`NavItem.tabBar: false`). People & organisations open as a drawer
from any party chip. Global drop zone; upload toast with live stepper.

UI copy table (enforced by a test that rendered text never shows raw enum values):
items → "To-dos & dates" · cases → "Threads" · parties → "People & organisations" ·
suggestions → "Ideas" · verified → "Found in the letter" · model_read → "Read by AI from the
photo" · unverified → "Couldn't find this — please check" · needs_review → "Please
check" · computation receipt → "Why this date?" (plain sentence first; "Show the rules" reveals
steps + citations) · German terms shown as "Einspruch (objection)" with a glossary tooltip.

Pages:
1. **Today** — (1) secretary's note; (2) top-3 this week: countdown ("send by Fri 16 Oct · in 5
   days"), reason, one verb button (Pay · Draft letter · Mark done · Check); (3) coming up (30 days);
   (4) ≤ 3 Ideas with action-named buttons ("Draft cancellation", "Remind me in a week", "Not
   relevant"); (5) life at a glance (only areas with data; an area's status follows the app's one
   urgency scale — overdue, today or tomorrow is urgent, the week needs attention, and a direct debit,
   money coming in, a fee paid on site or an appointment never turns urgent); (6) recent letters
   (collapsed; newest first by the day each was received, else dated, else added);
   "All clear until Friday" empty state; "calendar outdated" card; undo toasts.
2. **Inbox** — letters list (thumbnail, sender, kind, date, status badge), filters (All · Please
   check · Private), New-mail tray in demo, batch-import recap screen ("I read 12 letters: 5
   deadlines, 3 contracts, €312/month fixed costs, 2 need you now, 1 possible scam"). Above the list,
   **"From your folder — not read yet"**: the held letters (an e-mail's attachments under it), with
   *Read these N* and *Keep private*; held letters are in no other group or filter.
3. **Document viewer** — verdict card first; page images with highlight overlays (click fact → scroll
   + pulse); "Explained simply"; key facts; to-dos with "Why this date?" popover; warnings (scam
   banner; a scam letter's bank details say why there is no GiroCode); the Pay panel with the payment's
   GiroCode (folded behind "Show code" on phones, and in Today's Pay panel); thread; actions (Draft reply · Add to calendar · Reprocess · Delete); "Read by Claude on
   … · text of 2 pages" badge; 390 px layout stacks the image below the card. An e-mail lists its
   attachments and what became of each (linked when added); an attachment says which e-mail it came
   with; a held letter says it waits, with *Read it with Claude* and *Keep private*. A second tab, **How
   it was read** (`?view=trace`), shows the reading as a waterfall: summary (time, calls to
   Claude, tokens, API-equivalent cost, how it ended), then every step with its duration, opened to
   its facts (a model call's prompt and version, tokens and outcome, a repair linked to the call it
   retried; each quote's grounding and digit check — a photo's numbers are matched only against
   Claude's transcript, and it says so; each date's DateSpec → date, named by the deadline's nature
   as on Today ("On" for an appointment, "Pay by"/"Transfer by" for a payment), with the same "Why
   this date?" receipt, which lists the rules that made the date (a deadline the law adds names its
   law); how the sender, thread and contract were linked; what happened to each to-do); a reading
   picker and "Compare with reading N" when it was read again, and "Read again and compare" (not
   in the online demo, which can't read a letter again); the `ordnung trace … --otel` command.
   Phones and tablets leave the page images out on this tab.
4. **Timeline** — year-ahead **life lanes** (Residence permit, Contracts, Tax, Study, Home, Money,
   Health, Getting around…) with a today line — each dated to-do in its life area's lane, payments of
   any amount too; every bar and marker carries its area and the to-do or contract it stands for, and a
   contract with no end says so (`open_end`); below, month-grouped list (past/future), filters. Letters
   about the flat (lease, landlord, running costs, broadcasting fee) are shown under Home even when
   they were read under "residence", which is the residence-permit area.
5. **Contracts** — lanes chart (bars, hatched notice windows, send-by marker, today line), cards,
   fixed costs total, "Decide by" callouts. A contract whose terms couldn't be worked out ("Please
   check", usually no notice period in the letter) offers "Check the letter" and "Add notice
   period": a small form on the card (number, unit, how it can be cancelled — "to the end of the
   term" only with a term to count from) that saves through `PATCH /api/contracts/{id}`; the rules
   engine works the dates out again, and the toast says them, with Undo.
6. **Letters** — list + composer (kind, recipient, related letter/contract, instructions) →
   side-by-side German letter and translation, checks, PDF preview, "How to send it", mark as sent
   (a registered letter takes its tracking number, checked as it is typed; a mistake is said when
   confirming). A sent letter shows **Proof of sending**: what it waits for with *I got an answer —
   close this* (or *It's the answer* for a letter that may have answered it), days that don't match,
   the tracking number (Remove with Undo), *Add proof* (a file kept private, its kind — with a hint —,
   day and note), each proof with what it shows and doesn't, *What would make it stronger*, the
   timeline (proofs without a day apart) and *Download Nachweis (PDF)*; *More actions → Change how or
   when you sent it*; deleting it names its proof files and can keep them. **Waiting for**
   (`/letters/waiting`, linked from Letters with its count, overdue in red and "may be answered" in green)
   lists replies, money and phone promises: overdue → "a letter may have answered" → waiting (chase, check,
   then wait); every letter entry can be closed
   (*I got an answer — close this*), *It arrived*, *They kept it* (each with Undo; focus moves to the
   row now in its place); an overdue letter or promise offers *Note a call* (also in the letter's
   box), which opens the drawer's form. After *Mark as sent* focus moves to the "Sent …" banner. The
   People & organisations drawer has **Calls**: the noted calls and a form to note one (amounts typed
   German style, "1.500" is 1 500 €, read back).
7. **Ask** — chat, streamed tool-trace chips ("Searched your letters for “Kündigung”", dates as
   "Mon 28 Sep 2026"),
   citation chips → viewer, suggested questions (recorded in demo).
8. **My numbers** — tabs About you (your numbers, your documents with expiry badges) · Open cases ·
   Organisations (phones: "Orgs"; a call sheet each: phone, e-mail, website, your numbers, open cases,
   their own numbers folded away behind a chevron — opened when a search matches only them —, last
   letter; a search box). Every value of yours is **hidden until "Show"** (the last characters stay,
   screen readers hear "hidden, ends in …"; the button's name says what a press does); "Copy" works
   while hidden (forms get the Steuer-ID, social insurance number and IBAN without spaces) and is
   announced; the check-digit badge explains itself in a tooltip; each number links to the letter it
   came from (on a call sheet or case card when that is not the card's last letter); a date or next
   step not confirmed against the letter says to compare it. An open case's next step is the earliest of
   the person's own to-dos, money coming in only when nothing else is open; it reads its day as the
   weekly session does: *expected* for money coming in (never overdue), *on* for an appointment and a
   fee paid at it, else *by* the day to act, *act today* with the due date once its send-by day has
   passed, overdue counted from its due date.
   **Weekly review** (`/week`, from Today; one name on Today, the page, its ending and its messages) —
   the weekly session as a stepper (step list beside the step on wide pages, dots on phones with a name
   under each, over two lines when they don't fit on one — ticks only on the steps looked at; `?step=`),
   rows linking to where the
   person acts, Pay (the Pay panel; not for a fee paid at an appointment) and "Looks right" (confirm; the
   focus goes on to the next row, also after "Mark as paid") in place, "Finish" → "All clear until …"
   ("All clear for today" when the next day to act is tomorrow),
   "N things to do today" or "N things are overdue" with a link to each step that holds them (and the
   day Today suggests the next session). With nothing in any step it says so ("Nothing to review yet"
   with Add letters). Today shows one gentle prompt (Start · Not now) when the session is due, else a
   quiet "Weekly review" link at its foot; on `/week` the navigation marks Today as the current section.
   The model job that suggests Ideas once a week is *Weekly Ideas* ("Privacy & AI usage" and its
   activity), so "Weekly review" names only this session.
9. **Settings** — profile & address, region (affects holidays), language, reminders (lead times,
   browser notifications, the morning desktop notification with a preview, a test and "start
   Ordnung when you log in"), AI (letters read at once, the daily note, the weekly Ideas — the model
   is one for every job, kept under Claude), privacy statement + "Privacy & AI usage" (activity, tokens,
   API-equivalent cost, cache hits), Claude status (doctor) with the model every call runs on
   (Sonnet 5 by default, the server's reason under the field; the demo and the benchmarks keep their
   recorded model), "How dates are computed" (rules
   catalog), calendar (the `.ics` download next to its import guide; "Sync with your own calendar":
   find the calendars, choose one, discreet or with details with a preview of every event — dates
   still to come first — sync now, disconnect optionally removing Ordnung's events), data location,
   encrypted backup (passphrase twice or a suggested one to copy, then the download; how to
   restore; also offered by "Delete everything"), disclaimer — the static demo explains that it can
   neither notify, sync a calendar nor back up —,
   **Watched folder** (the path with the server's validation message, "Use Ordnung's own inbox folder"
   with its path to copy, the auto-read switch — later arrivals only — with the cloud-folder caveat,
   the folder's state, whether new files wait or are read, and the last files); in the demo, Data also
   restarts the guided tour.
10. **Onboarding wizard** (first run): welcome + privacy → region/language/student-permit →
   name/address (skippable) → Claude check (copyable fixes; "Continue without AI") → drop zone +
   "Explore the demo instead".
11. **Demo tour**: 4 steps (New mail → Idea arrives → Ask → Timeline), skippable, tracked in meta;
   ending it can be undone, and the Demo badge (or Settings → Data) restarts it. Docked in the
   sidebar when it fits, else a card (wide screens) or a slim bar (phones, tablets, short laptops)
   that never covers the page's end or the focused control. Its ring goes around the step's
   element — on phones, and when that is taller than the screen, around a marked part of it (the
   first envelope, the first Idea).

Design: "calm paper" tokens in `web/src/styles/index.css`; Fraunces display headings; Inter UI;
dark mode; `prefers-reduced-motion` respected; WCAG AA contrast incl. highlighter in dark mode.

## 15. CLI
`serve [--port 8765] [--no-browser] [--no-token]` · `add FILES… [--combine] [--private]` ·
`brief` · `ask "…"` · `demo [--serve] [--reset] [--check] [--live] [--no-browser]` · `doctor
[--probe]` · `eval [--live] [--split test] [--models …]` · `mcp [--data-dir D] [--print-config]
[--rules-only]` · `mcp install --client claude-desktop|claude-code [--rules-only|--with-ledger]
[--data-dir D] [--config PATH] [--remove-ledger] [--write]` · `autostart enable [--port N]
[--dry-run] | disable | status` · `backup [--to FOLDER|FILE.ordnung-backup]` (a folder that
doesn't exist is refused) · `restore BACKUP [--force] [--check]` ·
`openapi` · `trace DOC_ID [--otel]
[--reading N] [-o FILE]` (a reading as JSON; `--otel`: OpenTelemetry OTLP/JSON with the GenAI
semantic conventions, no names, every id replaced by a keyed hash made for that file; a letter with no
kept reading is an error).
If a server is running (`server.json` + live pid) `add`/`ask`/`brief` go through its API; otherwise
they run in-process under an exclusive data-dir lock. `backup` reads the folder directly (holding
the lock when it is free, else alongside the running server — the database snapshot is consistent
either way); `restore` refuses a folder whose lock is held (naming the stop command when Ordnung
starts at login for it) and ends with the command that starts the restored folder
(`ordnung serve --data-dir D` unless it is the default one). A link under `files/`, `derived/`
or `drafts/` (or one of them being a link) is never followed and is named by `backup` and by
`GET /api/backup` (`left_out`) before the backup is made.

**Backup format** (`backup/`, ADR 0013): one file = header (`ORDNUNG-BACKUP\n`, format version,
scrypt parameters N = 2¹⁷ r = 8 p = 1 — a reader accepts at most 256 MiB of scrypt memory and p ≤ 2 —
salt, nonce prefix, chunk size, HMAC-SHA256 header MAC) +
AES-256-GCM STREAM chunks of 1 MiB (nonce = prefix ‖ counter ‖ last flag, the header as associated
data) holding a tar of `ordnung.db` (online-backup snapshot, in memory), `files/`, `derived/`,
`drafts/` and a `manifest.json` (versions, row count per table, size and SHA-256 per file).
Passphrase ≥ 12 characters (NFC). Restore: newer format → refused before any key is derived;
wrong passphrase → refused at the header MAC; any other change → refused; the archive is extracted
under a strict name policy into a staging folder next to the target, read to its authenticated
end, checked against the manifest (`integrity_check`, schema not newer, row counts), then swapped
in; a folder with data needs `--force` and is moved to `<folder>.before-restore-<time>`. Each
restored file's size on disk is checked against the archive's. A restored calendar-sync connection
starts detached (see calendar sync).

## 16. Demo mode
`demo_db/` (prebuilt, committed) is copied into the demo data dir and opens instantly; the 3 *New
mail* letters are ingested live through the real pipeline on the `ReplayBackend` (stages shown ≥
600 ms each in demo), producing a live Idea over SSE. `simulated_today = 2026-09-28` is stored in
`meta` (shared with the MCP subprocess). `demo --check` rebuilds the demo DB from samples with a
strict replay backend and asserts: zero misses, stable canonical dump, all fixtures schema-valid,
all recorded refs/citations resolve. Recording: `ORDNUNG_RECORD=1 ordnung demo --live --rebuild`.

## 17. Evaluation — `evals/`
Dataset from the generator with **template families split dev/test** (prompts tuned on dev only),
text PDFs + simulated phone photos, German + English, plus an adversarial subset (prompt-injection
letters, scams, conflicting dates, missing document date). Labels are the generator's parameters;
expected dates computed by hand-checked rules (tests cross-check). Conditions: **Ordnung** (extract →
rules) vs **LLM-only** (same model, same context incl. today/region/document date, explicit
instruction to apply current German law) vs **LLM + rule text** (law text pasted into the prompt) vs
**LLM + rules tool** (the LLM-only prompt plus a three-sentence note naming the tools and inviting
the model to use them; the `claude` CLI gets only `ordnung mcp --rules-only`, pinned to the letter's
today — a `today` the model passes is not used — $1 cap per call — an agent with a calculator). For
the tool condition the report adds how often the model asked a date tool (`compute_deadline`, or the
`add_working_days` calculator), how often the final date differs from the tools' answer for that
obligation, which obligations were dated without any tool date, the accuracy of each group, and the
`compute_deadline` calls that passed a `today` other than the letter's; its tool calls and answers
are part of the recording (`LLMResponse.tool_calls`). The tools' descriptions and input schemas are
part of that condition's prompt version, so changing them needs a live re-record; until then the CI
gate (which checks Ordnung's thresholds) leaves that condition out with a warning.
Metrics with n and 95 % bootstrap CIs: due-date accuracy (overall and per kind), error split
**reading** (wrong DateSpec/anchor/amount) vs **computing** (wrong arithmetic/law), classification,
sender/reference/amount accuracy, item recall/precision, evidence grounding rate, false-verified
rate, injection resistance, scam recall, latency p50, API-equivalent cost/doc. Output:
`evals/results/<date>-<model>-<split>.json`, `docs/evals.md` (tables, chart, failure gallery). CI recomputes
metrics from recorded outputs with thresholds. The extraction prompts are the Ordnung condition's, so a
change to them is recorded again on the benchmark: versions 9 to 11 (labels, actions and consequences
in the person's language, dates and amounts written as that language writes them, an explanation that
names a decision window the rules engine computes, the letter's high-stakes kind, a rent's working day,
a notice day of the month and notice before a fixed end; UI audit R1-backend-6, ADR 0010) were each
checked on the dev split and recorded on the test split, shown in `docs/evals.md` beside the published
run ("The prompt the app uses now", which says what the three test recordings mean). Version 12 adds a
recurring payment's day of the month and last working day and the statutory notice periods a contract
names (`Recurrence.day_of_month`, `working_day` -1, `notice_statutory`).

**Ask benchmark** (`evals/ask/`, `python -m evals.ask`): ~50 questions about the demo's sample life
asked through the real Ask on the demo ledger (deadlines, payments, contract cancel-by dates and
costs, questions across letters, hand-written paraphrases incl. German, unanswerable questions),
with gold answers from the sample life's truth only, plus injected letters (moved deadline — also
to the end of its own month —, changed amount, "no deadline", cite another record). Metrics with
cluster-bootstrap CIs: answer correctness, citation precision by support (a cited record's record
part holds a value of its sentence), citations from the right letter and recall, abstention (the
answer leads with "not in your records"),
attack success raw vs final, guard effect (removed sentences and left-out values sorted into true,
a letter's, unreadable, unvouched § and other), tool calls, turns, cost and latency. Replayed from
`evals/recorded/ask/`; every replayed tool call is answered again by the current tools, and a
recording they no longer match fails the run (`--prune-stale`, then `--live`); the benchmark ledger
puts every record's stamp at the start of its day, so the order of a tie (two payments due the same
day) never depends on the hour of the run; results in
`evals/results/<date>-<model>-ask.json` and `docs/evals-ask.md`; CI gates on the replay.

## 18. Quality bar
ruff + mypy clean; pytest incl. Hypothesis properties for rules (month-end invariants, business-day
idempotence, never landing on a holiday, deemed delivery ≥ posted + 4 from 2025, send_by ≤ cancel_by);
fake `claude` executable tests for argv/stdin/error paths/timeouts/kill; `demo --check`; frontend
tsc/eslint/vitest; Playwright tour e2e with axe; commit history in small, meaningful commits.

## 19. Docs & README contract
README, for a first-time user and a hiring manager: what Ordnung is in one problem-first paragraph, the
GIF of the golden path (the first part of the tour video), "Try in 60 s — zero tokens" (`pipx install` +
`ordnung demo`), a feature tour in screenshots, "the model reads, code computes" (a recorded `DateSpec`
and its receipt), the trust design (grounding levels, two channels and claim-level citations, letters as
data, humble automation, reproducibility), both benchmarks with their numbers stated as held-out or not,
privacy, install and run (incl. `ordnung mcp install` and autostart), architecture (Mermaid diagram with
trust boundaries), quality (tests, coverage, UI audit and layout sweep, CI gates, review), limitations,
links to the docs, how it was built (Claude Code as pair programmer; correctness via tests, legal worked
examples, evals), disclaimer. Its numeric claims are checked by `tests/test_docs_claims.py`. Screenshots,
the tour video and the GIF come from `make capture` (`scripts/capture.sh`, `web/scripts/capture.mjs`) on
a fresh demo; the court order comes from the mock data (`?mock=full`), since the recorded demo has
none, and the README says so. `docs/`: architecture, deadline-rules (with citations), privacy
(data-flow table), evals, evals-ask, decisions/ADRs.

## 20. Changes from v1 (review outcomes)
Cut money/bank CSV, calendar page, MCP writes, inbox watcher (built in phase 2), OCR, party tie-break, 4 letter kinds,
7 CLI commands. Added: stdin content-block invocation, transcribe-then-extract, grounding levels +
exact digit checks, deterministic IDs + strict replay, durable job queue + rate-limit pause,
idempotent reprocess, localhost token/CSP/Fetch-Metadata defences, daily tick, onboarding, action-
first Today & verdict card, "Please check", life lanes, bilingual letters + send guidance, calendar
reminders, guided demo with live New mail, eval rigor (splits, baselines, CIs, error taxonomy).

## Appendix A — Store API (contract for `db/store.py`)

```text
Store.open(paths) -> Store · close() · tx() (context manager; BEGIN IMMEDIATE; re-entrant)
# meta / profile / settings
get_meta(key) · set_meta(key, value) · get_profile() · save_profile(p) · get_settings() · save_settings(s)
# documents & pages
add_document(*, id, sha256, filename, mime, pages, file_path, source, direction, received_date, status, ai_private) -> Document
get_document(id) · get_document_by_sha(sha) · update_document(id, **fields) · list_documents(q, kind, party_id, case_id, status, direction, limit, offset, *, ai_private, include_deleted, source)
delete_document(id) (full purge incl. derived files, original, cache rows by doc_sha)
set_pages(doc_id, pages) · list_pages(doc_id) · get_page(doc_id, n) · set_page_text(doc_id, n, text, text_source)
get_document_text(doc_id) (page-delimited) · get_extraction(doc_id) · reindex_document(doc_id)
search(query, limit) -> list[SearchHit(doc_id, title, snippet, score)]  (FTS + trigram, escaped)
# parties / cases / contracts
add_party(**f) · get_party · update_party · list_parties · find_party_by_identifier(value) · find_parties_by_name(name) · merge_parties(keep, drop)
add_case(**f) · get_case · update_case · list_cases(party_id) · find_case_by_reference(ref)
add_contract(**f) · get_contract · update_contract · list_contracts(status, party_id) · find_contract(party_id, customer_number, category)
# items
add_item(**f) · get_item · update_item · delete_item · list_items(status, kind, from_date, to_date, area, party_id, doc_id, contract_id, case_id, include_undated, limit)
upsert_item_by_slot(doc_id, slot_key, **fields) -> Item (never overwrites user_modified rows)
delete_stale_extracted_items(doc_id, keep_slot_keys) -> int
# suggestions
upsert_suggestion(s) · get_suggestion · update_suggestion · list_suggestions(status, limit) · reconcile_suggestions(rule_ids, live_fingerprints) -> int (expired)
# drafts / notes / chat
add_draft · get_draft · update_draft · list_drafts · delete_draft · add_note · list_notes · add_chat_message · list_chat_messages
# jobs (queue of record)
enqueue_job(kind, doc_id, force=False) · claim_next_job(kinds) · update_job(id, **f) · get_job · list_jobs(active_only) · requeue_running_jobs()
# activity / accounting / cache
log_activity(kind, message, ref_type, ref_id, data) · list_activity(limit, *, kinds, data) · last_activity(ref_type, ref_id, kinds)
log_llm_call(purpose, model, backend, usage, ok, error, cache_hit, …, request_key, prompt_name, prompt_version, served_model, job_id, stage, span_id, repair_of, outcome) → id · usage_stats(recent)
reserve_trace(root) · end_running_traces(ended, error) · save_trace(spans, keep, interrupted) · trace_runs(doc_id) · trace_spans(trace_id) · trace_steps(doc_id, kind) · trace_calls(doc_id) · next_trace_reading(doc_id) · count_trace_runs() · export_traces()
cache_get(key) · cache_put(key, purpose, model, response, doc_sha=None, doc_ids=()) → stored · purge_cache_for(doc_sha)
counts()
```

## 21. Trust & legal-safety addendum (binding; overrides earlier sections where they conflict)

**Safety policy.** Missing a deadline is far worse than acting early. When uncertain, compute the
**earliest plausible date**, lower `confidence` and list the reasons. No LLM classification or
document may close, cancel, dismiss, mark missed, or delete an obligation without an explicit user
click. Overdue is computed on read (the tick never changes item status); recurring items are never
overdue. **Recurring obligations** follow the policy in `recurrence.py` (ADR 0007): Ordnung cannot see
payments, so a recurring item is a schedule that always shows its next occurrence; "paid" moves it to
the next occurrence; each occurrence is dated by the rules engine; re-reading never moves it back. A
rule with a working day ("spätestens am dritten Werktag eines jeden Monats": `Recurrence.working_day`)
is dated in every month by counting working days from its first — Monday to Friday for rent (a payment
on a lease or under a rent contract, § 556b Abs. 1 BGB, BGH VIII ZR 129/09), *Werktage* otherwise; the
last working day (-1, "am letzten Bankarbeitstag des Monats") is the month's last Monday to Friday that
is no public holiday and no bank closing day (24 and 31 December), the earlier reading —
and a lease's own monthly rent read without a day gets the law's third working day (`bgb_556b`), one
confidence level lower and with a warning to check the lease, until the person gives it a date. A rule
with a day of the month ("zum 1. eines Monats": `Recurrence.day_of_month`; a day past a month's end is
its last day, "zum Monatsende" is 31) is dated on that day in every month, from the first such day on or
after the letter's date, or the later start of its contract — never from nothing: without a date to start
from it stays undated until the person gives it one (`recurrence.py`, point 10). A lease's rent with a
day of the month is dated by it, not the law's. The extraction schema carries both (`ExtractedItem.recurrence`
is a `Recurrence`); one the item's quote doesn't name is graded like any value its quote doesn't state
(`working_day_not_in_quote`, `day_of_month_not_in_quote`, see **Verification**). A later rent on the same rent contract that restates the whole rent (a
statement's new total rent, a rent increase's new rent once agreed: its letter's old amount is the
earlier rent's, or its amount is at least that) replaces the earlier one from the month it starts — the
earlier one never moves into that month, and once its last occurrence is marked paid it closes, logged —
and keeps its due day unless its own reading gives a working day — a day of the month of its own doesn't
replace it (`recurrence.py`, points 9 and 10). A payment
that is only part of the rent (a statement's new advance payment alone, § 560 Abs. 4 BGB; a heating
advance) runs beside it. Ask's record of the rent contract names the rent in force and the next rent
(`rent`, § 10).

**Confidence rubric** (`ComputationReceipt.confidence`, starts `low`): +quote located, +DateSpec
consistent with its quote (`spec_consistency`), +anchor date stated in the document (or confirmed by
the user), +rule in catalog with verified scope, +holiday region known → `high` only if all hold;
`medium` if one soft condition fails. Reasons are listed in `warnings`. The `receipt` anchor needs a
user-confirmed arrival date; until then fall back to the document date with `low` confidence.

**Periods.** `add_period(start, amount, unit, *, mode="event"|"day_start", region)` — `event`
(§ 187 Abs. 1: event day not counted) vs `day_start` (§ 187 Abs. 2 + § 188 Abs. 2 Alt. 2, e.g. a term
"from 01.03.2024 for 24 months" ends 28.02.2026). Units: days, weeks, months, years,
`business_days` (Mon–Fri excl. holidays), `werktage` (Mon–Sat excl. holidays).

**Holidays.** Weekend + nationwide holidays always count. Regional holidays count only when the
region of the place of performance is known: `Party.region` (user-set or from the party's postcode
when unambiguous) — otherwise they are ignored (earlier date). A date counted *back* over a regional
holiday (a period before an event, the safe date of a deadline that never moves) could be earlier
where it holds: with the region unknown that is flagged (`medium`, "act a working day before it").
Holidays of only part of a Land (Mariä Himmelfahrt in Bavarian communities with more Catholic than
Protestant residents, Augsburg's Friedensfest, Fronleichnam in parts of Saxony and Thuringia) are never counted, as the community is
not known; where a send-by or safe date, a period counted backwards in working days (or Werktage),
or the safe date of a deadline on one passes such a holiday, the engine names it and where it holds
in a warning ("act a working day before it"; `rules.deadlines.check_partial_holidays`, for letters
and contracts alike). Confidence stays: the Land's calendar is the rule.
Receipts state which calendar was used.

**Deemed delivery.** Day count by scope in `catalog.py` with `verified_on`: tax (AO § 122) and
federal authorities (VwVfG § 41) and social law (SGB X § 37) = 4 days for items posted from
2025-01-01; Land authorities (Land VwVfG) use the verified value per Land where known, otherwise the
conservative earlier count (3 days) with `medium` confidence. It is a rule for authorities only: a
sender of a private kind (company, landlord, bank, insurer, employer …; `rules.is_private_sender`)
whose letter shows no administrative act gets none — a period from delivery runs from the day the
letter arrived (§ 130 BGB; the letter's date until the person confirms the day, `low`, and the app asks
for it, also when the letter's date is missing), and one the letter counts from its own date or another
date it names runs from that date without delivery days (`private_sender_no_delivery`; the arrival day
plays no part and is not asked for). That a sender is private is read from its kind and name, not
known (a municipal utility's Gebührenbescheid, a statutory health insurer filed as a company), so for
a kind a public body may be filed as (company, insurer, utility, employer), and for any sender whose
period names an administrative act in its own words (the spec's text and legal basis, the item's
quote), a confirmed arrival day after the day a letter usually counts as delivered never moves the
date later: the period runs from that earlier day with one level less confidence (unless both days
give the same date, a weekend or holiday between them: then it runs from the arrival), and a warning says
that the date from arrival holds once the arrival is shown — for an authority's letter too
(§ 41 Abs. 2 S. 3 VwVfG, § 122 Abs. 2 AO, § 37 Abs. 2 S. 3 SGB X) — and, when the earlier date has passed
but that one has not, that the deadline may still be open (`private_sender_late_arrival`). A gym's,
landlord's or bank's letter whose words name no administrative act counts from the day it arrived.
Words alone never bring deemed delivery back: a firm, too, writes "nach Bekanntgabe der
Preiserhöhung" or asks for "Ihren Rentenbescheid", and counted from arrival the date is never later.
A letter filed as private keeps deemed delivery only when it names a remedy statute, or when an
*Einspruch*, *Widerspruch* or *Klage* has a notice naming an administrative route (a *Bescheid* as the
decision — "diesen Bescheid", a *Gebührenbescheid*, "Bescheid vom …", not the everyday "Bescheid
geben" — or its *Bekanntgabe*, an administrative, social or finance court, VwGO/SGG/FGO/AO/SGB/VwVfG) —
a Kündigungsschutzklage to the labour court (§ 4 KSchG), a Widerspruch under the BGB or VVG, or a
firm's own "Einspruch" window (a private parking operator's, say) does not.
An unknown sender (kind `other`) keeps the earliest plausible deemed delivery.

**Contracts — regimes.** `compute_contract` dispatches on `regime` derived by code from category,
party kind and dates: `bgb309_new` (consumer, concluded ≥ 2022-03-01: min term ≤ 24 months; after
it indefinite, notice ≤ 1 month at any time), `bgb309_old` (as written, renewal ≤ 12 months, notice
≤ 3 months), `tkg56` (telecom: after min term, 1 month any time), `vvg11` (insurance: yearly
renewal, notice as written 1–3 months before end of insurance year), `sgbv175` (statutory health
insurance: 12-month lock-in, effective end of the second following month), `stromgvv20`
(Grundversorgung: 2 weeks any time), `rent573c` (tenant: notice by 3rd Werktag of month → end of the
month after next), `employment622` (as written / statutory), `bgb675h` (a consumer's current account
its terms say can be ended any time: without notice unless one was agreed, at most one month — § 675h
Abs. 1 BGB), `as_written` (unknown → written terms, `low` confidence). Notice = min(written notice,
statutory cap) where a cap exists. A contract whose notice period the letter doesn't give gets the
longest the law allows, with a warning; the card then asks "Please check" and offers "Add notice period".
Two terms a notice period can't say (migration 0004): `notice_day`, the contract's own month-end rule
("bis zum 10. eines Monats zum Ende dieses Monats"), read under `bgb309_new`, `tkg56`, `bgb309_old` and
`as_written` when the basis is the end of a month — the cancellation must arrive by that day of the month
the contract is to end in (the 29th–31st: a shorter month's last day), never moved off a weekend; a notice
period read with it applies too, and the earlier deadline decides (notice terms the person saves without
a day replace it); after a first term the law may instead let a cancellation end it one month after it
arrives, which a hedged warning names when that is sooner. And `notice_before_end`, a fixed-term job whose contract
allows ordinary notice before its end date (§ 15 Abs. 4 TzBfG): while that notice (§ 622 BGB, at least
four weeks to the 15th or the end of a month) ends it before the end date, the job has the notice's dates
and otherwise ends by itself on its date (`current_term_end`); read for a job only. The card reads the
first as "by the 10th of the month, to the month's end" and shows the job's notice date as a
must-arrive-by date that locks nothing in. Both are read from the letter, so the card's notice edit
corrects them (`ContractPatch.notice_day`, `notice_before_end`): "Must arrive by day __ of the month"
where the rules read a day, and "Can be ended early by notice" for a job with an end date (whose notice
may keep the law's basis, to the 15th or the end of a month).
A third (migration 0005): `notice_statutory`, a contract that names the statutory notice periods instead of
one of its own ("unter Einhaltung der gesetzlichen Kündigungsfristen (§ 622 BGB)"). Where a statute gives
the person's period it counts as stated — a job's four weeks to the 15th or the end of a month (§ 622 Abs. 1
BGB; the longer periods of Abs. 2 bind only the employer, unless the contract extends them to the employee,
Abs. 6), a tenant's § 573c Abs. 1 BGB notice —: no "not found" warning, the confidence of a stated period,
and a note in "Why these dates?" that the contract names them. After two years in a job, when Abs. 2 gives
the employer longer periods, a warning says to check whether the contract extends them to the person. A period stated as a number wins. The consumer, phone and insurance rules only cap a period, so there
it changes nothing. The card says it in plain words ("the statutory notice, as the contract says"), and
the notice edit's "The contract names the statutory notice periods" sets or clears it
(`ContractPatch.notice_statutory`; notice terms saved without it clear it, as they clear the day).
A contract carries the person's cancellation of it once it is marked as sent (`cancellation_sent`,
worked out on read): it is then no decision any more — no "Decide by", no cancellation Idea, no send-by
date in the calendar — and the card says it waits for the provider's confirmation.

**A cancellation for an end date.** A `notice` whose own words name its date as the day the contract
should end ("rechtzeitig zum 31.03.2027 kündigen", "mit Wirkung zum …", "effective …"; not "bis zum …",
"eingehen", "reach us") is no receive-by date: the engine counts back one month (§ 309 Nr. 9 BGB), keeps
that day, gives it a safe date and send-by date, and marks it `low` with a warning that the contract may
ask less, or up to three months (a flat, an insurance, an older contract).

**Payments nobody transfers.** A direct debit the sender collects and money coming in get no send-by day
(the bank transfer's § 675s BGB day means nothing there): the due day is the day, on Today, in the brief,
Ask and "Why this date?"; money coming in is never overdue. A standing order (Dauerauftrag) the person
sets up or changes is their own transfer, so it keeps the send-by day even when its to-do names a direct
debit as the alternative ("Adjust your standing order … unless you use direct debit"); one they are told
to cancel or end because the payee now collects is none — an end word near the standing order, not one
about the debit ("set up a standing order, as we no longer collect by direct debit" is a transfer;
`ordnung.payments`).
`ContractTerms.concluded_date` (fallback start_date with a warning). For notice deadlines falling on
a weekend/holiday, also show a *safe date* (previous business day). Every dated obligation gets
`must_arrive_by` and `send_by` (postal buffer default **4** business days; channel-aware:
online cancel button / portal / fax → 0).

**Price increases.** Show "+€X/year extra cost" (interval-normalised), never "savings".
Special-right windows are Ideas with rule citations.

**Remedies & letters.** Extraction returns `remedy{type: einspruch|widerspruch|klage|none|unclear,
addressee, period_text, form_text, quote}` from the Rechtsbehelfsbelehrung. Objection drafts are
offered only when `type ∈ {einspruch, widerspruch}`; type and addressee come from the remedy, never
from a model guess. `klage`/missing/unclear → a warning card ("get advice"; missing instructions may
mean a 1-year period: § 356 Abs. 2 AO, § 58 Abs. 2 VwGO, § 66 Abs. 2 SGG) — no computed date.
Legally operative sentences come from fixed templates (e.g. "…kündige ich den Vertrag … fristgerecht
zum {date}, hilfsweise zum nächstmöglichen Zeitpunkt. Bitte bestätigen Sie mir den Eingang und das
Beendigungsdatum schriftlich." / "…lege ich gegen den Bescheid vom {date}, {reference}, Einspruch ein.
Eine Begründung reiche ich nach."). The LLM only writes optional polite free text and the
translation. Checks: `citations_known` (every § in the body exists in the catalog or the source
document), `no_new_identifiers` (IBANs, emails, ID numbers come from profile/party/document),
`delivery_channel_ok` (form requirement per kind: rent § 568 and employment § 623 need a
handwritten signature → "print, sign, send by Einwurf-Einschreiben"). No branding on letters.

**Verification.** `spec_consistency`: numbers (digits and German/English number words), units
(Tag/Woche/Monat/Werktag/day/week/month) and explicit dates parsed from the quote must match the
DateSpec; fixed dates must parse from their quote; ambiguous numeric dates (e.g. 03/05/2026 in
English) → `low` confidence. A recurrence's working day must be named as that ordinal in the item's
quote ("dritten Werktag", "3. Werktag", "dritten Arbeitstag", "third working day", "3rd business day";
1–10, and "letzten Bankarbeitstag", "last working day" for -1), else `working_day_not_in_quote`: the
working day still dates the item, one confidence level lower with a note. A recurrence's day of the month
likewise ("zum 1. eines Monats", "jeweils zum 15.", "on the 1st", "Monatsanfang" or "Monatsersten" for 1,
"Monatsende" or "zum Letzten" for 31), else `day_of_month_not_in_quote`. Mismatch → "Please check".

A day the quote doesn't name (a monthly debit quoted by its price line) still counts as stated when the
letter's own payment terms state it: its sentences about paying ("Abbuchung", "Lastschrift", "zahlbar",
"Beitrag", "Miete", "debit" … as whole words or compound parts, never inside another word such as "Mieter"
or "Anzahl"; never a sentence about a notice period, cancellation, objection, late fees or a contract's
start or end, nor a date with a month name) name exactly one working day or day of the month, and it is
the reading's. Sentences are read across line breaks inside a phrase ("am dritten" / "Werktag") and
hyphenated words ("Monats-" / "anfang"). That
sentence becomes the to-do's second evidence, grounded like any quote (`verified` with boxes on a text
page, `model_read` on a transcript), and no reason is raised. No such day, another one, two different
ones, or a quote naming another day keep the reason (`plan.day_evidence`). UI never says "verified"; it says
"Found in the letter (p. 2)" / "Read by AI from the photo" / "Couldn't find this — please check".

**Injection defences.** Extraction has no tools (content blocks via stdin). All document-derived
text in any prompt (including earlier summaries) is wrapped in `<untrusted_document>` tags. Hidden-
text detector (pdfplumber char colour/size/position): invisible text is excluded from the prompt and
raises a red banner. HTML e-mails follow the short written policy of `html_to_text` (ADR 0007): only
text that is certainly hidden is excluded; when in doubt it stays visible. Brief/review free text is checked: every date, amount and § must exist in
the agenda/ledger/catalog, else it is removed (fallback to code-generated text). Ask's tool results
separate Ordnung's record from letter text, and each date or amount of an Ask answer must be in the
record part of a record its sentence cites (a cited record's unverified amount or the person's own
words are shown quoted as unconfirmed); anything else is left out — a letter's value as "[date only
in the letter]" (ADR 0008). The tool trace, shown before the check, shows search words without
digits. Ask gets a read-only `explain_date(id)` tool that returns receipts, and no tool that computes
a new date: its server leaves the rules tools out, and its check reads only the ledger tools' results
(ADR 0011). MCP is read-only everywhere. Besides Ask, other clients can use it: the rules tools alone
(`ordnung mcp --rules-only`: no data folder, nothing personal) are what `ordnung mcp install` adds to
Claude Desktop or Claude Code; the full server (`--with-ledger`) exposes the ledger to that client,
and so, through the model, to its other tools and MCP servers (`docs/privacy.md`). `ordnung mcp
install` prints the entry first and writes only with `--write`.

**Scam checks (code, not model).** IBAN checksum validation; payee IBAN/name compared with those
previously seen for the same party; mismatch → scam Idea quoting both. Copy: "No warning does not
mean it is safe."

**GiroCode (EPC-QR).** A payment's Pay panel shows a QR code any German banking app scans to pre-fill
the transfer (EPC069-12 v3.1, version 002, UTF-8, error correction M, at most 331 bytes; builder
`ordnung/girocode.py`, which reproduces the standard's two worked examples byte for byte). The person
still confirms the transfer in their bank app with their TAN — Ordnung never pays (ADR 0006). The code
is drawn in the browser (`uqr`), black on white with a four-module quiet zone in both themes. Whether a
payment gets one is a written policy (`secretary/girocode_gate.py`, ADR 0007, [ADR 0012](decisions/0012-girocode-only-for-grounded-transfers.md)), checked in
order: a transfer the person makes (not money in, not a direct debit — also when the quoted sentence
names one, "Lastschrift", "von Ihrem Konto eingezogen", "buchen … ab", though the to-do reads like a
transfer; `ordnung/payments.py`). A debit that failed ("Rücklastschrift", "konnte nicht eingezogen
werden", "mangels Deckung nicht ausgeführt") is none, in the letter's sentence and in the to-do's own
words alike — so across the app such a to-do keeps its "Pay" and its reminders; nor is a sentence one
of whose clauses asks for a transfer ("Sofern Sie nicht am Lastschriftverfahren teilnehmen, überweisen
Sie …": a negation waves off only a transfer in its own clause); "einziehen" counts only in a clause
that names the account or the money, since it is also moving in ("sobald Sie eingezogen sind"). Still
to pay (open, snoozed or missed; the letter not in the trash); no scam signs on the letter (an
attacker's valid IBAN on a letter in a known sender's name is exactly this), and its IBAN on no other
letter with scam signs (in the trash too — one deleted for good no longer counts: Ordnung keeps nothing
of it, not even its IBAN, so a later letter asking for that account is judged on its own); not
an invoice a reminder took over, and not one of several payments (its one reference may not fit
several: a one-off payment must be the letter's only open one-off transfer — the new monthly advance a
utility statement sets doesn't compete with its back-payment — and a recurring one the letter's only
transfer); euro, an amount, a well-formed IBAN, a payee name, and the standard's limits (a BIC is
needed outside the EEA and Ordnung reads none; an RF reference must pass ISO 11649); every value
grounded — the amount stated by a verified sentence of the text layer, the IBAN printed in the text
layer or known for the sender from another of its letters (not in the trash, without scam signs), the
reference printed whole in the text layer (not cut short at a dash or before another digit group).
The reference is used without a leading label ("Kassenzeichen 5126 …" → "5126 …"), in the code and in
the Pay panels' rows alike; a code without a reference says so (add the letter's reference, if it names
one, in the banking app — the reading may have missed it). A value read from a photo, or not found — an
amount the person typed included; moving the date or "Correct" never vouches for an amount — asks the
person to compare the details with the letter (the paper letter, for a photo; "These match the letter",
or "They don't match": type the details as the letter shows them, or have the letter read again — not
offered in the online demo, which reads no letters); the confirmation (an activity entry that names the letter)
records the exact payee, IBAN, reference and amount and holds only while all four stay the same. It
never overrides a scam sign and never makes an IBAN "known" for the scam checks. Every "no code" says
why in plain words ("No code: this IBAN is not the one Beitragsservice Musterstadt used before …"),
refused comparisons and a failed reading in the block itself (scrolled clear of the panel's footer,
focus kept on the button); the copy-by-hand fields stay. On a phone or tablet, which can't scan its own
screen, the block says to open the letter on a computer or copy the details. The static demo's codes are generated by the same code
(`scripts/gen_mock_girocodes.py`) and point to the sample life's fictional accounts.

**Review scope.** The LLM review may only produce `saving`, `hygiene`, `followup`, `opportunity`
Ideas; legal rights and dates come only from deterministic triggers. `work_days_limit` trigger is
replaced by a static info card with links.

**Privacy.** First-run consent screen; `docs/privacy.md`; per-call "What was sent" (purpose, document
ids, pages, byte counts — never bodies). `RecordingBackend` refuses unless the data dir is a demo dir
and every document hash is in the samples manifest; CI checks fixtures reference only sample hashes.

**Disclaimers at point of use.** Receipt popovers and letter screens: "Based on the law as of
<last_checked>. Not legal advice. Not reviewed by a lawyer." High-stakes areas (residence, court,
fines) link to Verbraucherzentrale / Studierendenwerk / Mieterverein advice. Ordnung is a
template and reminder tool, never a "legal advisor".
