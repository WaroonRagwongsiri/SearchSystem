-- embed_text migration (idempotent — safe to re-run).
-- ponytail: raw SQL rather than Alembic (single forward migration, single operator);
--           adopt Alembic when there's a team / rollback needs.
--
-- The text actually used for embedding — the Human-In-The-Loop override of the
-- modernize step's modernized_content. The embed pipeline falls back to
-- modernized_content when this is NULL; /reembed writes a value here and embeds
-- it in place, so a bad embedding can be corrected without re-running the LLM.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embed_text text;
