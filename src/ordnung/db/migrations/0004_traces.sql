-- 0004: how a letter was read — spans of each reading, and what every model call belonged to.
--
-- Written to apply on its own after 0001 or after 0002/0003 of other work: it creates one new table
-- and only adds columns to llm_calls, which no other migration touches.

-- One row per step of one reading of a letter (ordnung/trace). A reading's root span has
-- kind 'run' and no parent; its id is the trace_id of every span of that reading. Spans hold
-- only what Ordnung computed or decided and ids of the records they point to — never letter text.
CREATE TABLE IF NOT EXISTS trace_spans (
  id         TEXT PRIMARY KEY,
  trace_id   TEXT NOT NULL,
  doc_id     TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  job_id     TEXT,
  parent_id  TEXT,
  key        TEXT NOT NULL,
  seq        INTEGER NOT NULL DEFAULT 0,
  kind       TEXT NOT NULL,
  name       TEXT NOT NULL,
  stage      TEXT,
  started_at TEXT NOT NULL,
  ended_at   TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'ok',
  error      TEXT,
  attributes TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS trace_spans_doc ON trace_spans(doc_id, kind);
CREATE INDEX IF NOT EXISTS trace_spans_trace ON trace_spans(trace_id, seq);

-- What a model call was: the replay/cache key, the prompt template and version, the model that
-- answered, and where it belongs (job, pipeline stage, span, the call a repair retried) and how
-- its answer turned out (ok | invalid | repaired | failed).
ALTER TABLE llm_calls ADD COLUMN request_key TEXT;
ALTER TABLE llm_calls ADD COLUMN prompt_name TEXT;
ALTER TABLE llm_calls ADD COLUMN prompt_version TEXT;
ALTER TABLE llm_calls ADD COLUMN served_model TEXT;
ALTER TABLE llm_calls ADD COLUMN job_id TEXT;
ALTER TABLE llm_calls ADD COLUMN stage TEXT;
ALTER TABLE llm_calls ADD COLUMN span_id TEXT;
ALTER TABLE llm_calls ADD COLUMN repair_of INTEGER;
ALTER TABLE llm_calls ADD COLUMN outcome TEXT NOT NULL DEFAULT 'ok';
UPDATE llm_calls SET outcome = 'failed' WHERE ok = 0;
CREATE INDEX IF NOT EXISTS llm_calls_span ON llm_calls(span_id);
