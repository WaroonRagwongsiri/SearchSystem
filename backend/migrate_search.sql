-- Search schema migration (idempotent — safe to re-run).
-- ponytail: raw SQL migration rather than Alembic (one forward migration, single operator);
--           adopt Alembic when there's a team / rollback needs.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS modernized_content text;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- tsvector over modernized content. Thai is unsegmented (no spaces), so 'simple' config is
-- coarse here — pg_trgm is the primary lexical signal. tsvector still helps exact token hits.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS search_tsvector tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', coalesce(modernized_content, ''))) STORED;
CREATE INDEX IF NOT EXISTS documents_search_tsvector_idx ON documents USING gin (search_tsvector);

-- trigram index for word_similarity / similarity ranking over modernized content
CREATE INDEX IF NOT EXISTS documents_modernized_trgm_idx ON documents USING gin (modernized_content gin_trgm_ops);

-- HNSW vector index created AFTER the embedding pipeline loads (bulk-load then index is faster).
