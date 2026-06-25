# PocSearch

Hybrid search (**lexical + fuzzy + vector**) over a corpus of **historical Thai archive documents**, with an LLM-based **modernization** pipeline. ~745k document records, each embedded with BGE-M3 (1024-d) and indexed for full-text, trigram, and vector similarity search in PostgreSQL.

> Operator's manual — how to run it, restore it, and rebuild each layer. The build spec is [`PLAN.md`](PLAN.md).

---

## Stack

| Layer | Tech |
|------|------|
| API | FastAPI (Python 3.13), SQLAlchemy 2, psycopg 3 |
| DB | PostgreSQL 16 + extensions: `pgvector`, `pg_trgm`, `fuzzystrmatch` |
| Frontend | Next.js 16 (App Router, JS) |
| Infra | Docker / Docker Compose (db + backend + frontend) |
| Embeddings | BGE-M3 (`BAAI/bge-m3`, 1024-d) via OpenAI-compatible vLLM endpoint |
| LLM (modernization) | Qwen2.5-14B-Instruct via OpenAI-compatible vLLM endpoint |

---

## Data model

Two tables (see `backend/models.py`, `backend/migrate_search.sql`):

**`documents`** — one row per source item (keyed by item UUID `id`), ~745,691 rows.
- `id` (PK), `json_data` (JSONB — the raw source record)
- `raw_content` *(generated, stored)* — `coalesce(description, '')`, the lexical/fuzzy + display surface
- `search_tsvector` *(generated, stored)* — `to_tsvector('simple', description)`, GIN-indexed
- `modernized_content` — LLM-modernized Thai (internal scratch for the embed pipeline; **not searched, not shown**)
- `embedding` — `vector(1024)` (BGE-M3), HNSW-indexed (cosine)

**`dictionary`** — 1,097 historical→modern Thai word mappings (from `dict_โบราณ.csv`).
- `ancient_word` (PK), `modern_definition` (raw scholarly entry), `modern_word` (clean modern equivalent, LLM-extracted)

**Indexes:** `documents_embedding_hnsw_idx` (HNSW, cosine), `documents_search_tsvector_idx` (GIN), `documents_raw_trgm_idx` (GIN trigram), plus PKs.

---

## Adding a historical→modern word mapping

This is the core extensibility hook. You add an entry to `dictionary`; future document modernization pulls these mappings into the LLM prompt as context (see `context_for()` in `backend/modernize_embed.py`).

**Where it stores:** the `dictionary` table (`ancient_word` = the historical word, `modern_definition` = the modern meaning). Upsert is keyed on `ancient_word`, so re-adding a word updates it in place.

**How (3 ways):**

1. **One-off via the API** (no restart needed):
   ```bash
   curl -X POST localhost:8000/add_new_word_map \
     -H 'Content-Type: application/json' \
     -d '{"ancient_word":"สรวป","modern_definition":"สรุป (สรุปความ)"}'
   ```
2. **Via the frontend** — open the **Add Word** page (`frontend/app/add-word/page.js`), fill the form, submit. It hits the same `POST /add_new_word_map`.
3. **Bulk from CSV** — re-run `.venv/bin/python backend/seed_dictionary.py` (idempotent upsert from `dict_โบราณ.csv`).

**What step it does:** the endpoint (`backend/main.py` `add_new_word_map`) does an `INSERT ... ON CONFLICT (ancient_word) DO UPDATE` — insert-or-replace. There is **no re-indexing or re-embedding** of documents when you add a word; the mapping only takes effect on the next modernization run. To apply a new mapping to the corpus, re-run the modernize+embed pipeline (`backend/modernize_embed.py`).

---

## Prerequisites

- Docker + Docker Compose
- A `.env` (copy from `.env.example`). The DB vars are the **single source of truth** — `DATABASE_URL` is derived in code, not stored separately:

```bash
POSTGRES_USER=pocsearch
POSTGRES_PASSWORD=...						# set a real password
POSTGRES_DB=pocsearch
POSTGRES_HOST=localhost						# docker-compose overrides to `db` inside the stack
POSTGRES_PORT=5432
EMBEDDING_ENDPOINT=http://host:port			# BGE-M3 vLLM, OpenAI-compatible /v1/embeddings
LLM_ENDPOINT=http://host:port				# Qwen vLLM, OpenAI-compatible /v1/chat/completions
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Quick start (restore from dump — fastest path)

A full database dump (data + embeddings + index definitions) lives at **`backups/pocsearch.dump`** (gitignored; ~3 GB). Restoring it brings up a fully searchable corpus with **no ingest or embedding step**.

```bash
cp .env.example .env					# fill in POSTGRES_* and model endpoints
docker compose up -d --build 			# builds pgvector from source (see db/Dockerfile); first build is slow
# wait for db healthy, then restore:
docker compose cp backups/pocsearch.dump db:/tmp/pocsearch.dump
docker compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --clean --if-exists -j 4 /tmp/pocsearch.dump
docker compose up -d --build backend frontend
curl localhost:8000/health				# {documents: ~745691, embedded: ~745690, dictionary: 1097, ...}
```

Restore rebuilds the HNSW + GIN indexes from the index definitions in the dump (one-time cost, ~minutes). Verify with `GET /health`.

`backups/schema.sql` (in git) is a tiny schema-only dump for quick reference — not enough to run, just to read the structure.

---

## Rebuild from scratch (no dump)

If you don't have the dump, rebuild each layer from the source files. The corpus is checked in under `all_documents/` (7,481 JSON pages, ~745k items; 2 unreadable files are auto-skipped).

```bash
docker compose up -d --build db

# host venv for the scripts (they talk to db at localhost:5432)
.venv/bin/python -m pip install -r backend/requirements.txt

# 1. Create tables (idempotent)
.venv/bin/python -c "import sys; sys.path.insert(0,'backend'); from db import Base, engine; from models import Document, Dictionary; Base.metadata.create_all(engine)"

# 2. Search columns + indexes (run inside db)
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f backend/migrate_search.sql

# 3. Seed the dictionary
.venv/bin/python backend/seed_dictionary.py

# 4. Ingest all_documents/  (~20 min, idempotent upsert, per-chunk commit)
.venv/bin/python backend/ingest.py

# 5. Embed raw text with BGE-M3  (~2.6 h for the full corpus via remote endpoint)
.venv/bin/python backend/embed_all_raw.py

# 6. (Re)build the HNSW index AFTER embeddings load
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "CREATE INDEX IF NOT EXISTS documents_embedding_hnsw_idx ON documents USING hnsw (embedding vector_cosine_ops);"

docker compose up -d --build backend frontend
```

> **Modernization is deferred.** `modernized_content` is currently a partial (94.5k rows) *free-form* LLM output from an earlier run — **not** the intended dictionary-grounded modernization. The embeddings above are over **raw** text, so vector search works fully without it. Redoing modernization properly (dict-grounded) + re-embedding is a quality upgrade, not a blocker. See `backend/modernize_embed.py` / `backend/modernize_dictionary.py`.

---

## API reference (FastAPI, port 8000)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Corpus stats: documents / modernized / embedded / dictionary counts |
| `GET` | `/search?q=&limit=&offset=&vector=true&min_score=` | Hybrid search |
| `GET` | `/document/{id}` | Full raw source record for one document |
| `POST` | `/add_new_word_map` | Upsert a dictionary mapping `{ancient_word, modern_definition}` |

**`/search` parameters:**
- `q` — query string (Thai)
- `vector` (default `true`) — `true` = **RRF fusion** of lexical + fuzzy + vector; `false` = weighted lexical + fuzzy only
- `limit` / `offset` — pagination
- `min_score` — relevance floor. Defaults: `0.15` for lexical/fuzzy (cuts trigram noise), `0` for RRF (different score scale)

**Ranking:** lexical (tsvector) > fuzzy (trigram) > vector. Weights `W_LEX/W_FUZZY/W_VEC = 0.6/0.3/0.1`; `RRF_K = 60`; candidate pool per signal = 100. All tunable at the top of `backend/main.py`.

> Known gap: in hybrid (`vector=true`) mode, `total` is bounded by the per-signal candidate pool (≤300), not the true match count. True full-count paging only in `vector=false` mode.

Examples:
```bash
curl "localhost:8000/search?q=สรุป&vector=true&limit=10"
curl "localhost:8000/search?q=สรุป&vector=false&limit=10&offset=0"
curl "localhost:8000/document/<doc-uuid>"
```

---

## Repo layout

```
.
├── all_documents/					# source corpus: 7,481 JSON pages, {"items":[...]} (gitignored, large)
├── dict_โบราณ.csv					# historical→modern Thai dictionary source
├── docker-compose.yml				# db + backend + frontend; pgdata named volume
├── scrape.sh						# re-scrape the source corpus into all_documents/
├── backend/
│   ├── config.py					# .env → DATABASE_URL (derived)
│   ├── db.py						# SQLAlchemy engine + Base + SessionLocal
│   ├── models.py					# Document, Dictionary
│   ├── main.py						# FastAPI app: /search /health /document /add_new_word_map
│   ├── ingest.py					# all_documents/*.json → documents (idempotent upsert, per-chunk commit)
│   ├── embed_all_raw.py			# BGE-M3 embed raw description/subject (resumable, skips embedded rows)
│   ├── modernize_embed.py			# modernize (LLM) + embed pipeline (resumable)
│   ├── modernize_dictionary.py		# extract clean modern_word per dictionary entry
│   ├── seed_dictionary.py			# dict_โบราณ.csv → dictionary
│   ├── migrate_search.sql			# search columns + GIN/trgm indexes (idempotent)
│   ├── Dockerfile
│   └── requirements.txt
├── db/
│   ├── Dockerfile					# postgres:16 + pgvector built from source
│   └── pocsearch_2026-06-24.pgc	# STALE dump (pre-2026-06-25 ingest); use backups/pocsearch.dump
├── frontend/						# Next.js app (search page + add-word form)
├── backups/
│   ├── pocsearch.dump				# full DB backup — data + embeddings + indexes (gitignored, ~3 GB)
│   └── schema.sql					# schema-only dump (in git)
└── certs/
```

---

## Operating notes

- **`.env` is the source of truth** for the DB; `DATABASE_URL` is derived in `backend/config.py`. Don't hand-set a second URL var.
- **pgvector is built from source** (`db/Dockerfile`) because this environment's Docker mirror serves official images only — `pgvector/pgvector` can't be pulled. Same PG16 base → the `pgdata` volume stays compatible.
- **`docker compose up --build` rebuilds *all* buildable services, including `db`** — which recreates the db container and kills host-side DB connections. While host scripts write to the DB (ingest/embed), prefer `docker compose up -d` / `psql exec` and avoid `--build`.
- **Embedding/ingest scripts run on the host venv** (DB at `localhost:5432`), not in the backend container. The container serves the API only.
- **Frontend `NEXT_PUBLIC_API_URL` is baked at build time** (Dockerfile ENV) — the browser uses it to reach the backend. CORS is wide open (`*`) for the POC; tighten for prod.

---

## Making a fresh dump

```bash
docker compose exec -T db pg_dump -U "$POSTGRES_USER" -Fc -Z6 "$POSTGRES_DB" > backups/pocsearch.dump
docker compose exec -T db pg_dump -U "$POSTGRES_USER" --schema-only "$POSTGRES_DB" > backups/schema.sql
```
