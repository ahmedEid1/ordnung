-- Migration 0002: proof of sending for letters, and call notes (Gesprächsnotizen).
--
-- Only adds: columns on drafts and two new tables, so it applies after (or before) any other
-- migration that adds its own columns or tables, and on a database without them. Dates: YYYY-MM-DD.
-- Timestamps: ISO-8601 UTC.

-- The Einschreiben's tracking number (Sendungsnummer), stored as typed after normalising
-- (no spaces, upper case); ``drafts.proof.parse_tracking_number`` decides what is accepted.
ALTER TABLE drafts ADD COLUMN tracking_number TEXT;
-- What the letter's PDF showed of the sender when it was marked as sent (JSON: name, e-mail, phone),
-- so the Nachweis encloses the letter as it went out even after the profile changed.
ALTER TABLE drafts ADD COLUMN sent_profile TEXT;
-- The person said the sent letter was answered (the day), and by which letter (NULL: by phone,
-- e-mail … or not said). Only this — or a confirmation of the cancelled contract — counts as an answer.
ALTER TABLE drafts ADD COLUMN answered_on TEXT;
ALTER TABLE drafts ADD COLUMN answer_doc_id TEXT REFERENCES documents(id) ON DELETE SET NULL;

-- One piece of proof for a sent letter: a posting receipt, delivery record, return receipt, fax
-- report, the sent e-mail, a cancel-button confirmation … The file is a private outgoing document
-- (never sent to a model); deleting it deletes the proof, deleting the letter deletes its proofs.
CREATE TABLE IF NOT EXISTS proofs (
  id         TEXT PRIMARY KEY,
  draft_id   TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL,
  doc_id     TEXT REFERENCES documents(id) ON DELETE CASCADE,
  on_date    TEXT,
  note       TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS proofs_draft ON proofs(draft_id);
CREATE INDEX IF NOT EXISTS proofs_doc ON proofs(doc_id);

-- A phone call the person noted: when, with whom, what was said and what was promised (a promise
-- with a date is waited for, see ``secretary.waiting``). Written by the person, never by a model.
CREATE TABLE IF NOT EXISTS call_notes (
  id              TEXT PRIMARY KEY,
  party_id        TEXT REFERENCES parties(id) ON DELETE SET NULL,
  case_id         TEXT REFERENCES cases(id) ON DELETE SET NULL,
  called_on       TEXT NOT NULL,
  contact         TEXT,
  summary         TEXT NOT NULL,
  promise         TEXT,
  promise_due     TEXT,
  promise_amount  REAL,
  promise_kept_on TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS call_notes_party ON call_notes(party_id);
CREATE INDEX IF NOT EXISTS call_notes_case ON call_notes(case_id);
