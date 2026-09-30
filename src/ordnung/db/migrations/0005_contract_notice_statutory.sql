-- Migration 0005: a contract that names the statutory notice periods instead of a period of its own.
--
-- Only adds a column to contracts, which no other migration but 0004 touches (with other columns), so it
-- applies after (or before) any other migration. Rows written before it read as "not stated".

-- The contract names the statutory notice periods ("unter Einhaltung der gesetzlichen Kündigungsfristen
-- (§ 622 BGB)", "Es gelten die gesetzlichen Kündigungsfristen"): 1, else 0.
ALTER TABLE contracts ADD COLUMN notice_statutory INTEGER NOT NULL DEFAULT 0;
