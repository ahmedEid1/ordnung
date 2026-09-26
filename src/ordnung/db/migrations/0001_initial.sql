-- Ordnung schema, migration 0001 (initial). JSON columns hold JSON text. Dates: YYYY-MM-DD. Timestamps: ISO-8601 UTC.

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parties (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'other',
  aliases     TEXT NOT NULL DEFAULT '[]',
  identifiers TEXT NOT NULL DEFAULT '[]',
  address     TEXT,
  email       TEXT,
  phone       TEXT,
  website     TEXT,
  notes       TEXT,
  region      TEXT,
  ibans       TEXT NOT NULL DEFAULT '[]',
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS parties_name ON parties(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS cases (
  id         TEXT PRIMARY KEY,
  title      TEXT NOT NULL,
  party_id   TEXT REFERENCES parties(id) ON DELETE SET NULL,
  reference  TEXT,
  status     TEXT NOT NULL DEFAULT 'open',
  summary    TEXT,
  area       TEXT NOT NULL DEFAULT 'other',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cases_party ON cases(party_id);

CREATE TABLE IF NOT EXISTS documents (
  id            TEXT PRIMARY KEY,
  sha256        TEXT NOT NULL UNIQUE,
  filename      TEXT NOT NULL,
  mime          TEXT NOT NULL,
  pages         INTEGER NOT NULL DEFAULT 1,
  direction     TEXT NOT NULL DEFAULT 'incoming',
  source        TEXT NOT NULL DEFAULT 'upload',
  status        TEXT NOT NULL DEFAULT 'queued',
  error         TEXT,
  kind          TEXT,
  area          TEXT,
  title         TEXT,
  summary       TEXT,
  explanation   TEXT,
  language      TEXT,
  doc_date      TEXT,
  received_date TEXT,
  party_id      TEXT REFERENCES parties(id) ON DELETE SET NULL,
  case_id       TEXT REFERENCES cases(id) ON DELETE SET NULL,
  urgency       TEXT,
  text_mode     TEXT,
  text          TEXT,
  extraction    TEXT,
  key_facts     TEXT NOT NULL DEFAULT '[]',
  refs          TEXT NOT NULL DEFAULT '[]',
  warnings      TEXT NOT NULL DEFAULT '[]',
  tax_relevant  INTEGER NOT NULL DEFAULT 0,
  tax_note      TEXT,
  remedy        TEXT,
  payment       TEXT,
  hidden_text   INTEGER NOT NULL DEFAULT 0,
  ai_private    INTEGER NOT NULL DEFAULT 0,
  ai_processed_at TEXT,
  deleted_at    TEXT,
  tags          TEXT NOT NULL DEFAULT '[]',
  file_path     TEXT NOT NULL,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  processed_at  TEXT
);
CREATE INDEX IF NOT EXISTS documents_party ON documents(party_id);
CREATE INDEX IF NOT EXISTS documents_case ON documents(case_id);
CREATE INDEX IF NOT EXISTS documents_date ON documents(doc_date);

-- Full text search (maintained by Store on every document write).
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
  doc_id UNINDEXED, title, summary, explanation, text, parties,
  tokenize = 'unicode61 remove_diacritics 2'
);
-- Substring search inside German compounds ("steuerbescheid" in "Einkommensteuerbescheid").
CREATE VIRTUAL TABLE IF NOT EXISTS documents_trigram USING fts5(
  doc_id UNINDEXED, body,
  tokenize = 'trigram'
);

CREATE TABLE IF NOT EXISTS pages (
  doc_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page       INTEGER NOT NULL,
  width      INTEGER NOT NULL,
  height     INTEGER NOT NULL,
  image_path TEXT NOT NULL,
  text       TEXT NOT NULL DEFAULT '',
  text_source TEXT NOT NULL DEFAULT 'none', -- text | transcript | none
  words      TEXT NOT NULL DEFAULT '[]',   -- [[text, x0, y0, x1, y1], ...] relative coords 0..1
  hidden     TEXT NOT NULL DEFAULT '',     -- invisible text detected on the page (excluded from prompts)
  PRIMARY KEY (doc_id, page)
);

CREATE TABLE IF NOT EXISTS contracts (
  id                  TEXT PRIMARY KEY,
  party_id            TEXT REFERENCES parties(id) ON DELETE SET NULL,
  case_id             TEXT REFERENCES cases(id) ON DELETE SET NULL,
  name                TEXT NOT NULL,
  category            TEXT NOT NULL DEFAULT 'other',
  customer_number     TEXT,
  concluded_date      TEXT,
  start_date          TEXT,
  initial_term_months INTEGER,
  renewal_term_months INTEGER,
  notice_value        INTEGER,
  notice_unit         TEXT,
  notice_basis        TEXT,
  end_date            TEXT,
  cost_amount         REAL,
  cost_currency       TEXT NOT NULL DEFAULT 'EUR',
  cost_interval       TEXT,
  is_consumer         INTEGER NOT NULL DEFAULT 1,
  is_basic_supply     INTEGER NOT NULL DEFAULT 0,
  status              TEXT NOT NULL DEFAULT 'active',
  computed            TEXT,
  source_doc_id       TEXT REFERENCES documents(id) ON DELETE SET NULL,
  evidence            TEXT NOT NULL DEFAULT '[]',
  area                TEXT NOT NULL DEFAULT 'other',
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS contracts_party ON contracts(party_id);

CREATE TABLE IF NOT EXISTS items (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,
  title         TEXT NOT NULL,
  description   TEXT,
  action        TEXT,
  consequence   TEXT,
  due_date      TEXT,
  due_time      TEXT,
  send_by       TEXT,
  date_spec     TEXT,
  computation   TEXT,
  amount        REAL,
  currency      TEXT,
  direction     TEXT,
  recurrence    TEXT,
  status        TEXT NOT NULL DEFAULT 'open',
  snoozed_until TEXT,
  priority      TEXT NOT NULL DEFAULT 'normal',
  area          TEXT NOT NULL DEFAULT 'other',
  party_id      TEXT REFERENCES parties(id) ON DELETE SET NULL,
  case_id       TEXT REFERENCES cases(id) ON DELETE SET NULL,
  contract_id   TEXT REFERENCES contracts(id) ON DELETE SET NULL,
  doc_id        TEXT REFERENCES documents(id) ON DELETE CASCADE,
  evidence      TEXT NOT NULL DEFAULT '[]',
  grounding     TEXT NOT NULL DEFAULT 'unverified',
  slot_key      TEXT,
  user_modified INTEGER NOT NULL DEFAULT 0,
  due_date_source TEXT NOT NULL DEFAULT 'none',
  origin        TEXT NOT NULL DEFAULT 'extracted',
  location      TEXT,
  filed_on      TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  completed_at  TEXT
);
CREATE INDEX IF NOT EXISTS items_due ON items(due_date);
CREATE INDEX IF NOT EXISTS items_status ON items(status);
CREATE INDEX IF NOT EXISTS items_doc ON items(doc_id);
CREATE UNIQUE INDEX IF NOT EXISTS items_slot ON items(doc_id, slot_key) WHERE slot_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS suggestions (
  id               TEXT PRIMARY KEY,
  kind             TEXT NOT NULL,
  title            TEXT NOT NULL,
  body             TEXT NOT NULL,
  rationale        TEXT,
  priority         TEXT NOT NULL DEFAULT 'normal',
  status           TEXT NOT NULL DEFAULT 'new',
  snoozed_until    TEXT,
  fingerprint      TEXT NOT NULL UNIQUE,
  refs             TEXT NOT NULL DEFAULT '[]',
  action           TEXT,
  source           TEXT NOT NULL DEFAULT 'rule',
  rule_id          TEXT,
  savings_estimate REAL,
  due_date         TEXT,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
  id              TEXT PRIMARY KEY,
  kind            TEXT NOT NULL,
  language        TEXT NOT NULL DEFAULT 'de',
  party_id        TEXT REFERENCES parties(id) ON DELETE SET NULL,
  case_id         TEXT REFERENCES cases(id) ON DELETE SET NULL,
  doc_id          TEXT REFERENCES documents(id) ON DELETE SET NULL,
  contract_id     TEXT REFERENCES contracts(id) ON DELETE SET NULL,
  sender_block    TEXT NOT NULL DEFAULT '',
  recipient_block TEXT NOT NULL DEFAULT '',
  place_date      TEXT NOT NULL DEFAULT '',
  subject         TEXT NOT NULL DEFAULT '',
  body            TEXT NOT NULL DEFAULT '',
  body_translation TEXT NOT NULL DEFAULT '',
  send_guidance   TEXT,
  sent_channel    TEXT,
  enclosures      TEXT NOT NULL DEFAULT '[]',
  notes_for_user  TEXT NOT NULL DEFAULT '[]',
  checks          TEXT NOT NULL DEFAULT '[]',
  status          TEXT NOT NULL DEFAULT 'draft',
  sent_at         TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
  id         TEXT PRIMARY KEY,
  text       TEXT NOT NULL,
  item_ids   TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       TEXT NOT NULL,
  kind     TEXT NOT NULL,
  message  TEXT NOT NULL,
  ref_type TEXT,
  ref_id   TEXT,
  data     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS llm_calls (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  ts                    TEXT NOT NULL,
  purpose               TEXT NOT NULL,
  model                 TEXT NOT NULL,
  backend               TEXT NOT NULL,
  duration_ms           INTEGER NOT NULL DEFAULT 0,
  input_tokens          INTEGER NOT NULL DEFAULT 0,
  output_tokens         INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd              REAL NOT NULL DEFAULT 0,
  ok                    INTEGER NOT NULL DEFAULT 1,
  error                 TEXT,
  cache_hit             INTEGER NOT NULL DEFAULT 0,
  doc_ids               TEXT NOT NULL DEFAULT '[]',
  pages_sent            INTEGER NOT NULL DEFAULT 0,
  bytes_sent            INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS llm_cache (
  key        TEXT PRIMARY KEY,
  purpose    TEXT NOT NULL,
  model      TEXT NOT NULL,
  response   TEXT NOT NULL,
  doc_sha    TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_cache_doc ON llm_cache(doc_sha);

CREATE TABLE IF NOT EXISTS jobs (
  id         TEXT PRIMARY KEY,
  kind       TEXT NOT NULL DEFAULT 'ingest',
  status     TEXT NOT NULL DEFAULT 'queued',
  stage      TEXT,
  progress   REAL NOT NULL DEFAULT 0,
  doc_id     TEXT REFERENCES documents(id) ON DELETE CASCADE,
  attempts   INTEGER NOT NULL DEFAULT 0,
  force      INTEGER NOT NULL DEFAULT 0,
  not_before TEXT,
  waiting_reason TEXT,
  error      TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id         TEXT PRIMARY KEY,
  thread_id  TEXT NOT NULL,
  role       TEXT NOT NULL,
  content    TEXT NOT NULL,
  citations  TEXT NOT NULL DEFAULT '[]',
  tool_calls TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_thread ON chat_messages(thread_id, created_at);
