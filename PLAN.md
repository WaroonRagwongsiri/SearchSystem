# Search System Implementation Plan

## Overview
A hybrid search system (Lexical + Fuzzy + Vector) with LLM-based modernization for historical Thai documents, built with FastAPI, SQLAlchemy, and PostgreSQL.

## 1. Database & Infrastructure (Docker)
- [x] Define `docker-compose.yml` for PostgreSQL (with `pgvector`, `pg_trgm`, `fuzzystrmatch`).
- [ ] Implement database migrations using `Alembic`. **Deferred** — using idempotent raw-SQL
    migrations instead (`backend/migrate_search.sql`, `migrate_dictionary_status.sql`,
    `migrate_embed_text.sql`); adopt Alembic when there's a team / rollback needs.
- [x] Create `.env.example` (tracked) and `.env` (gitignored) controlling **all** DB connection params:
    - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`
    - `DATABASE_URL` is **derived in code** from the above (`postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB`) — single source of truth, no separate var to keep in sync.
    - `EMBEDDING_ENDPOINT` (BGE-M3), `LLM_ENDPOINT` (modernization).
- [x] Feed the same `POSTGRES_*` vars to the Postgres container so it auto-creates the DB/user on first volume boot.
- [x] Define Docker volume mount for persistent database storage in `docker-compose.yml`.
- [x] Add `.env` to `.gitignore` (keep `.env.example` tracked).
- [x] Schema-only dump committed at `backups/schema.sql` for quick DDL reference (regenerate
    via `pg_dump --schema-only`; see README "Making a fresh dump"). Note: restoring the full
    data dump requires running the migrations above — the dump predates several columns.

## 2. Data Model & Ingestion
- [x] SQLAlchemy Models:
    - `Dictionary`: `ancient_word` (PK), `modern_definition` — **CSV-only**; `modern_word`/`status`/`error` columns are dormant (extraction removed).
    - `Document`: `id`, `json_data` (raw), `modernized_content` (read-only LLM output), `embed_text` (human override; NULL ⇒ `modernized_content`), `embedding` (vector), `tsvector` (search).
- [x] Ingestion Service:
    - [x] Batch reader for the source JSON files (`backend/ingest.py`; actual corpus is 7,481 pages / 745,691 items — 2 unreadable files auto-skipped).
    - [x] Bulk upsert into `Document` table.
    - [x] Import `dict_โบราณ.csv` into `Dictionary` table (`backend/seed_dictionary.py`).

## 3. Modernization & Embedding Pipeline
> The modernize step is the **only retained LLM step** and is Human-In-The-Loop reviewable
> (see §4): dictionary context uses CSV `modern_definition` only (no `modern_word`).
- [ ] Pre-process Service:
    - [x] Fetch document content from the raw `json_data` and concatenate the three prose fields
      in fixed order — **`subject` → `description` → `abstract`** — joined by `\n`, skipping any field
      that is NULL **or empty string** (`data.json` shows `abstract` as `""`, so empty must be handled
      like NULL). Canonical field reference: `data.json` (one full item record).
      ```sql
      concat_ws(E'\n',
        nullif(json_data->>'subject',''),
        nullif(json_data->>'description',''),
        nullif(json_data->>'abstract',''))
      ```
      Example from `data.json` (`abstract` is `""`, dropped → two lines remain):
      ```
      Mr.H.B. Tuner ประธานกรรมาธิการรัฐสภาออสเตรเลียเยี่ยมคารวะที่ทำเนียบ (24 มิ.ย. 2508)
      กองงานโฆษก
      ```
      Field roles (full corpus, 745,691 items): `subject` = narrative title (~100% populated,
      median 78 chars); `description` = short category tag (~28 chars, 77% identical to `accountName`);
      `abstract` = longest prose (median 100, max 6,240 chars) but only ~10% populated.
      This combined text feeds both the LLM modernize step and the BGE-M3 embedder.
    - [x] Query `Dictionary` to find historical terms (`context_for()` in `backend/modernize_embed.py`).
    - [ ] Modernization Call: Send text + dictionary context to LLM Endpoint.
      **Partial** — `modernized_content` holds ~94.5k rows of *free-form* LLM output from an
      earlier run, **not** the intended dictionary-grounded modernization. Needs a proper re-run.
    - [x] Embedding Call: Send text to BGE-M3 Endpoint. **Done over RAW text** (`backend/embed_all_raw.py`,
      ~745k rows embedded) — vector search works fully without the modernization re-run.
    - [x] Update `Document` table with `modernized_content` and `embedding`.
- [x] HITL review loop: `embed_text` (human override, NULL ⇒ `modernized_content`) is what
      gets embedded; re-embed an edited value without re-running the LLM (`/reembed`).

## 4. API Implementation (FastAPI)
- [x] `/add_new_word_map` (POST):
    - Implementation using `on_conflict_do_update`. **CSV-only — no LLM call**; stores
      user-provided `ancient_word` + `modern_definition` only (`status='done'`).
- [x] `/documents_by_word` (GET): drill-down for HITL review — modernized docs whose raw
    text contains the word; returns raw · LLM output · `embed_text` · reconstructed
    dictionary context. Paginated.
- [x] `/reembed/{doc_id}` (POST): persist an edited `embed_text` and embed it in place.
- [x] `/search` (Lexical + Fuzzy) (GET):
    - Weighted scoring between `tsvector` and `word_similarity`.
    - Pagination implementation (`limit`/`offset`).
- [x] `/search` (Lexical + Fuzzy + Vector) (GET):
    - Hybrid Search using Reciprocal Rank Fusion (RRF).
    - Pagination implementation.
- [x] `/dictionary` (GET) — dictionary rows + per-status counts (powers the Add-word table).
- [x] `/health` (GET) + `/document/{id}` (GET) — corpus stats + raw record drill-down.

## 5. Frontend (Next.js 16)
- [x] Scaffold a minimal Next.js 16 app (App Router) in a `frontend/` directory.
- [x] Search page (`/`):
    - Search input bound to the hybrid `/search` endpoint.
    - Result list showing matched `modernized_content` with score.
    - `limit`/`offset` pagination controls.
- [x] Dictionary map page (`/add-word`):
    - Form posting `ancient_word` + `modern_definition` to `/add_new_word_map`.
- [x] API client util hitting the FastAPI backend (`NEXT_PUBLIC_API_URL`).
- [x] Run in dev via `next dev`; add to `docker-compose.yml` as a service for local orchestration.

## 6. Deployment
- [ ] Docker Swarm configuration for container orchestration.
