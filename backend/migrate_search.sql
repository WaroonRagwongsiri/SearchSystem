-- Search schema migration (idempotent — safe to re-run).
-- ponytail: raw SQL migration rather than Alembic (one forward migration, single operator);
--           adopt Alembic when there's a team / rollback needs.
--
-- Design: lexical/fuzzy search + display run over the RAW historical text (raw_content).
-- modernized_content is kept ONLY as the embedding pipeline's internal scratch space
-- (modernize(description) → modernized_content → embed → embedding). It is not searched
-- and not shown. See backend/main.py.

-- columns kept for the vector pipeline (modernize→embed)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS modernized_content text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- raw historical text pulled straight from the source JSON (search + display surface)
ALTER TABLE documents ADD COLUMN IF NOT EXISTS raw_content text
  GENERATED ALWAYS AS (coalesce(json_data->>'description', '')) STORED;

-- full-text + trigram indexes are rebased on RAW content (previously modernized_content).
-- A STORED generated column's expression can't be ALTERed in place, so drop + recreate.
-- Note: search_tsvector reads json_data->>'description' directly — Postgres won't let a
-- generated column reference another generated column (raw_content), only base columns.
DROP INDEX IF EXISTS documents_search_tsvector_idx;
ALTER TABLE documents DROP COLUMN IF EXISTS search_tsvector;
ALTER TABLE documents ADD COLUMN search_tsvector tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', coalesce(json_data->>'description', ''))) STORED;
CREATE INDEX IF NOT EXISTS documents_search_tsvector_idx ON documents USING gin (search_tsvector);

DROP INDEX IF EXISTS documents_modernized_trgm_idx;
CREATE INDEX IF NOT EXISTS documents_raw_trgm_idx ON documents USING gin (raw_content gin_trgm_ops);

-- HNSW vector index created AFTER the embedding pipeline loads (bulk-load then index is faster).
