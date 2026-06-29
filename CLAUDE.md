# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

This repository is **pre-implementation**. There is no source code, build tooling, dependency manifest, or test suite yet — only [PLAN.md](PLAN.md) (the build spec), this file, and the raw **data assets** (see below). Once scaffolding lands, update this file with the real build/lint/test commands.

## Data Assets (present in repo)

The raw inputs the system ingests are already checked in — no download step needed:

- **`all_documents/`** — 3,138 JSON files (`page_0001.json` … `page_3138.json`). Each file is `{"items": [ … ]}` where every item is a historical Thai archive document record (metadata fields: `id`, `oid`, `digitalFileID`, `digitalFileName`, `accountName`, `fullContentCode`, Thai-language `branchName`/`resourceDigitalFile`, etc.). This array-of-`items` shape must be flattened during ingestion — one `Document` row per item, not per file.
- **`dict_โบราณ.csv`** — historical→modern Thai dictionary. **Actual columns are `Word`, `Definition`, `References (แม่คำ/ลูกคำ)`** (UTF-8 with BOM). This does NOT match the intended `Dictionary` schema below verbatim — see the mismatch note in Data Model.
- **`all_documents.zip`** (≈115 MB) — archived copy of `all_documents/`; ignore unless re-hydrating.

## What Is Being Built

A **hybrid search system (Lexical + Fuzzy + Vector) with LLM-based modernization** for historical Thai documents. The system takes historical/ancient Thai text, modernizes it via an LLM, generates embeddings, and serves search over the modernized content.

## Intended Tech Stack

- **API / app framework:** FastAPI
- **Frontend:** Next.js 16 (App Router), see PLAN.md §5 — search page + dictionary-map form hitting the FastAPI backend
- **ORM:** SQLAlchemy
- **Database:** PostgreSQL with three extensions — `pgvector` (vector similarity), `pg_trgm` (trigram/`word_similarity`), `fuzzystrmatch` (fuzzy matching)
- **Migrations:** Alembic
- **Infrastructure:** Docker + Docker Compose for local dev; Docker Swarm for deployment

## Intended Data Model

- **`Dictionary`** — `ancient_word` (PK), `modern_definition`. **CSV-only** (sourced from `dict_โบราณ.csv`); the API never writes LLM-fabricated data here — `add_new_word_map` upserts only the user-provided `ancient_word` + `modern_definition`.
  > The `modern_word`, `status`, `error` columns still exist in the schema (dropping is destructive) but are **dormant** — extraction no longer runs, so `modern_word` is no longer written via the LLM; upsert sets `status='done'`. Existing `modern_word` values can be nullified in a follow-up migration.
  > CSV columns are `Word`, `Definition`, `References (แม่คำ/ลูกคำ)` (UTF-8 with BOM); mapping is `Word`→`ancient_word`, `Definition`→`modern_definition`, `References` dropped.
- **`Document`** — `id`, `json_data` (raw), `modernized_content` (read-only LLM output), `embed_text` (human override of the embed input; NULL ⇒ fall back to `modernized_content`), `embedding` (vector column), `tsvector` (full-text search column). Sourced from ~3,138 JSON files via batch ingestion/bulk upsert.

## Intended API Surface

- `POST /add_new_word_map` — insert/update a Dictionary mapping using `on_conflict_do_update` (upsert keyed on `ancient_word`). **CSV-only — no longer calls the LLM**; stores only the user-provided `ancient_word` + `modern_definition` (`status='done'`).
- `GET /documents_by_word?word=<w>` — drill-down for Human-In-The-Loop review: every modernized document whose raw text contains `word`, returning raw text · LLM output (`modernized_content`) · `embed_text` · reconstructed dictionary context (CSV `modern_definition` only). Paginated (`limit`/`offset`).
- `POST /reembed/{doc_id}` body `{ embed_text }` — persist a human-edited `embed_text` and embed it in place (200 `{id, ok:true}`; empty text⇒400; upstream embed error⇒502 `{id, ok:false, error}`; 404 if missing).
- `GET /search` (Lexical + Fuzzy) — weighted scoring between `tsvector` rank and `word_similarity` (pg_trgm). Supports `limit`/`offset` pagination.
- `GET /search` (Lexical + Fuzzy + Vector) — hybrid search combining all three signals via **Reciprocal Rank Fusion (RRF)**. Supports pagination.

## Key Algorithms to Get Right

- **Modernization + embedding pipeline (the one retained LLM step):** fetch document → query Dictionary for historical terms → send text + dictionary context (**CSV `modern_definition` only**) to the LLM endpoint → send modernized text to the **BGE-M3** embedding endpoint → write back `modernized_content` and `embedding`. This is the only LLM step in the system; it is made reviewable via the HITL loop below.
- **Human-In-The-Loop review loop:** `GET /documents_by_word` surfaces per document the raw text · the LLM output (`modernized_content`) · the dictionary context the LLM was given (reconstructed read-only from CSV); a human edits `embed_text` and `POST /reembed` embeds it in place. `embed_text` (NULL ⇒ fall back to `modernized_content`) is what the vector index actually holds, so a bad embedding is correctable without re-running the LLM.
- **Hybrid scoring:** lexical/fuzzy path uses weighted `tsvector` + `word_similarity`; the full hybrid path fuses lexical, fuzzy, and vector result lists with **RRF** (each list contributes `1 / (k + rank)`). When implementing, confirm the RRF `k` constant and per-signal weights are intentional, not arbitrary defaults.

## Configuration

All config is env-driven via `.env` (gitignored; copy from `.env.example`). The database is fully env-controlled: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT` are the **single source of truth** — they init the Postgres container on first boot *and* `DATABASE_URL` is derived from them in code (`postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB`), so there's never a second var to drift. External endpoints: `EMBEDDING_ENDPOINT` (BGE-M3), `LLM_ENDPOINT` (modernization). Persist DB storage via a Docker volume in `docker-compose.yml`.
