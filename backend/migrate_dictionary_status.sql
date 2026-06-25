-- Dictionary extraction-status migration (idempotent — safe to re-run).
-- ponytail: raw SQL rather than Alembic (single forward migration, single operator);
--           adopt Alembic when there's a team / rollback needs.
--
-- Tracks the modern-word EXTRACTION pipeline (modernize_dictionary.py / on-add
-- extraction in main.py), not document embedding — words aren't embedded.
--   pending : modern_word not yet extracted (NULL)              → badge "In progress"
--   done    : extraction returned a valid word (or identity)    → "Done"
--   failed  : the LLM call raised; `error` holds the reason     → "Failed" + reason

ALTER TABLE dictionary ADD COLUMN IF NOT EXISTS status text DEFAULT 'pending';
ALTER TABLE dictionary ADD COLUMN IF NOT EXISTS error text;

-- backfill: ADD COLUMN ... DEFAULT 'pending' already set every existing row to 'pending',
-- so rows still awaiting extraction (modern_word NULL) are correct. Flip the already-
-- extracted rows to 'done'. Unguarded by status — re-runs are a harmless done→done no-op
-- and failed rows (modern_word NULL) are never matched, so their state is preserved.
UPDATE dictionary SET status = 'done' WHERE modern_word IS NOT NULL;
