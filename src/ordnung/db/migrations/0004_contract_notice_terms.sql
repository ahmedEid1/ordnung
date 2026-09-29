-- Migration 0004: two notice terms of a contract that its notice period alone can't say.
--
-- Only adds columns to contracts, which no other migration touches, so it applies after (or before)
-- any other migration. Rows written before it read as "not stated": no day, no early notice.

-- The day of the month a cancellation must arrive by to end the contract at the end of that month
-- ("bis zum 10. eines Monats zum Ende dieses Monats"): 1–31, NULL when the contract states none.
ALTER TABLE contracts ADD COLUMN notice_day INTEGER;
-- A contract with an end date whose own clause lets it be ended earlier by ordinary notice (a fixed-term
-- job's "Nach Ablauf der Probezeit kann … ordentlich gekündigt werden", § 15 Abs. 4 TzBfG): 1, else 0.
ALTER TABLE contracts ADD COLUMN notice_before_end INTEGER NOT NULL DEFAULT 0;
