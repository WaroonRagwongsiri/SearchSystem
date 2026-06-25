import os

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from dict_extract import extract_modern_word
from db import Base, SessionLocal, engine
from models import Dictionary  # noqa: F401  (registers model on Base.metadata)

Base.metadata.create_all(engine)

app = FastAPI(title="PocSearch")
# ponytail: allow all origins — local dev POC, no auth/cookies. Tighten to the real frontend origin(s) in prod.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- search config (deliberate, not arbitrary — see CLAUDE.md "algorithms to get right") ---
EMBED_URL = os.environ.get("EMBEDDING_ENDPOINT", "").rstrip("/") + "/v1/embeddings"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
RRF_K = 60            # standard RRF constant
CANDIDATES = 100      # per-signal candidate pool before fusion
# per-signal weights: lexical (tsvector) dominant, fuzzy (trigram) secondary, vector least — per ranking spec.
# Note: tsvector('simple') is coarse for unsegmented Thai; these weights favor it per request — tune if lexical underperforms.
W_LEX, W_FUZZY, W_VEC = 0.6, 0.3, 0.1

# Score floor for the lexical/fuzzy combined score. The loose trigram candidate filter
# (word_similarity > 0.1) admits a long tail of near-misses scoring ~0.08; real hits land
# ~0.20+. 0.15 sits in that gap and drops the noise (e.g. ยกเลิก → 0 results, honestly).
# RRF (hybrid) scores live on a ~100× smaller scale, so it defaults OFF there; override via ?min_score.
MIN_SCORE_LEX = 0.15

# --- modern-word extraction config (on-add extraction; graceful if LLM unset) ---
_LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "").rstrip("/")
LLM_CHAT = _LLM_ENDPOINT + "/v1/chat/completions" if _LLM_ENDPOINT else ""  # "" → add stays 'pending'
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class WordMap(BaseModel):
    ancient_word: str
    modern_definition: str


@app.post("/add_new_word_map")
def add_new_word_map(wm: WordMap, db: Session = Depends(get_db)):
    """Upsert a historical→modern mapping, then extract the modern word synchronously.

    The row is written as status='pending' first (re-extract every save — the definition
    may have changed, so modern_word/error are reset); if LLM_ENDPOINT is configured the
    extraction runs inline and the row flips to done/failed before the response returns.
    If LLM_ENDPOINT is unset it stays 'pending', deferred to a modernize_dictionary.py run.
    """
    stmt = pg_insert(Dictionary).values(
        ancient_word=wm.ancient_word,
        modern_definition=wm.modern_definition,
        modern_word=None,
        status="pending",
        error=None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ancient_word"],
        set_={
            "modern_definition": stmt.excluded.modern_definition,
            "modern_word": None,
            "status": "pending",
            "error": None,
        },
    )
    db.execute(stmt)
    db.commit()

    status = "pending"
    modern_word, error = None, None
    if LLM_CHAT:  # synchronous extraction — ~1–2s; the UI shows the pending→done/failed flip
        with httpx.Client(timeout=60) as c:  # ponytail: short-lived client — sync endpoint runs in a threadpool, no shared-client thread-safety
            modern_word, error = extract_modern_word(
                wm.ancient_word, wm.modern_definition, client=c, chat_url=LLM_CHAT, model=LLM_MODEL
            )
        status = "failed" if error else "done"
        if error:
            db.execute(
                text("UPDATE dictionary SET status = 'failed', error = :e WHERE ancient_word = :w"),
                {"e": error, "w": wm.ancient_word},
            )
        else:
            db.execute(
                text(
                    "UPDATE dictionary SET modern_word = :m, status = 'done', error = NULL "
                    "WHERE ancient_word = :w"
                ),
                {"m": modern_word, "w": wm.ancient_word},
            )
        db.commit()

    return {
        "ancient_word": wm.ancient_word,
        "modern_definition": wm.modern_definition,
        "modern_word": modern_word,
        "status": status,
        "error": error,
    }


@app.get("/dictionary")
def dictionary(limit: int = 25, offset: int = 0, db: Session = Depends(get_db)):
    """List dictionary rows (ordered by ancient_word) + per-status counts."""
    rows = db.execute(
        text(
            "SELECT ancient_word, modern_definition, modern_word, status, error "
            "FROM dictionary ORDER BY ancient_word LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    ).all()
    counts = {
        r[0]: r[1]
        for r in db.execute(
            text("SELECT coalesce(status, 'pending') AS s, count(*) FROM dictionary GROUP BY s")
        ).all()
    }
    return {
        "results": [
            {
                "ancient_word": r[0],
                "modern_definition": r[1],
                "modern_word": r[2],
                "status": r[3] or "pending",
                "error": r[4],
            }
            for r in rows
        ],
        "total": sum(counts.values()),
        "counts": {
            "pending": counts.get("pending", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
        },
    }


def _embed_query(q: str) -> list[float]:
    r = httpx.post(EMBED_URL, json={"model": EMBED_MODEL, "input": [q]}, timeout=30)
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def _lexfuzzy(db: Session, q: str, limit: int, offset: int, min_score: float):
    # weighted tsvector rank + trigram word_similarity over the RAW text (PLAN §4 lexical+fuzzy)
    where = "raw_content <> '' AND word_similarity(:q, raw_content) > 0.1"
    score_expr = (
        "( :w_lex * (ts_rank(search_tsvector, plainto_tsquery('simple', :q)) / "
        "(ts_rank(search_tsvector, plainto_tsquery('simple', :q)) + 1.0)) "
        "+ :w_fuzzy * word_similarity(:q, raw_content) )"
    )
    inner = (
        f"SELECT id, json_data->>'subject' AS subject, json_data->>'description' AS description, "
        f"{score_expr} AS score FROM documents WHERE {where}"
    )
    params = {"q": q, "w_lex": W_LEX, "w_fuzzy": W_FUZZY, "ms": min_score}
    total = db.execute(text(f"SELECT count(*) FROM ({inner}) t WHERE score >= :ms"), params).scalar_one()
    rows = db.execute(
        text(
            f"SELECT id, subject, description, score FROM ({inner}) t "
            "WHERE score >= :ms ORDER BY score DESC LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": limit, "offset": offset},
    ).all()
    return (
        [{"id": r[0], "score": round(float(r[3]), 4), "subject": r[1], "description": r[2]} for r in rows],
        total,
    )


def _hybrid(db: Session, q: str, limit: int, offset: int, min_score: float):
    vec = "[" + ",".join(f"{x:.7f}" for x in _embed_query(q)) + "]"
    trgm = db.execute(
        text(
            "SELECT id, word_similarity(:q, raw_content) s FROM documents "
            "WHERE raw_content <> '' AND word_similarity(:q, raw_content) > 0.1 "
            "ORDER BY s DESC LIMIT :c"
        ),
        {"q": q, "c": CANDIDATES},
    ).all()
    ts = db.execute(
        text(
            "SELECT id, ts_rank(search_tsvector, plainto_tsquery('simple', :q)) s FROM documents "
            "WHERE search_tsvector @@ plainto_tsquery('simple', :q) ORDER BY s DESC LIMIT :c"
        ),
        {"q": q, "c": CANDIDATES},
    ).all()
    vec_rows = db.execute(
        text(
            "SELECT id, 1 - (embedding <=> CAST(:v AS vector)) s FROM documents "
            "WHERE embedding IS NOT NULL ORDER BY embedding <=> CAST(:v AS vector) LIMIT :c"
        ),
        {"v": vec, "c": CANDIDATES},
    ).all()

    # gather per-doc ranks from each signal's list
    seen: dict[str, dict] = {}
    for rank, r in enumerate(trgm):
        seen.setdefault(r[0], {})["trgm"] = rank
    for rank, r in enumerate(ts):
        seen.setdefault(r[0], {})["ts"] = rank
    for rank, r in enumerate(vec_rows):
        seen.setdefault(r[0], {})["vec"] = rank
    # weighted RRF: lexical > fuzzy > vector (per ranking spec). Vector embeddings come
    # from modernized text (modernize→embed); lexical/fuzzy rank the RAW text.
    weights = {"ts": W_LEX, "trgm": W_FUZZY, "vec": W_VEC}
    fused = sorted(
        ((did, sum(weights[sig] / (RRF_K + rk) for sig, rk in sigs.items())) for did, sigs in seen.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    if min_score > 0:  # RRF scores are ~100× smaller than lexical — default 0 = off (see MIN_SCORE_LEX)
        fused = [x for x in fused if x[1] >= min_score]
    page = fused[offset : offset + limit]
    content = {}
    if page:
        ids = [d[0] for d in page]
        content = {
            r[0]: {"subject": r[1], "description": r[2]}
            for r in db.execute(
                text(
                    "SELECT id, json_data->>'subject' AS subject, json_data->>'description' AS description "
                    "FROM documents WHERE id = ANY(:ids)"
                ),
                {"ids": ids},
            ).all()
        }
    return (
        [
            {"id": did, "score": round(score, 4), **content.get(did, {"subject": None, "description": None})}
            for did, score in page
        ],
        len(fused),  # ponytail: hybrid total is bounded by the per-signal candidate pool (CANDIDATES×3), not all matches — true 2000/N paging only in vector=false mode.
    )


@app.get("/search")
def search(
    q: str,
    limit: int = 10,
    offset: int = 0,
    vector: bool = True,
    min_score: float | None = None,
    db: Session = Depends(get_db),
):
    """Hybrid search. vector=true (default) → RRF over lexical+fuzzy+vector; vector=false → weighted lexical+fuzzy.

    min_score drops results below a relevance floor before paging (keeps totals honest).
    Defaults: lexical/fuzzy = MIN_SCORE_LEX (cuts trigram noise); RRF = 0 (different scale)."""
    mode = "lex+fuzzy+vector (RRF)" if vector else "lex+fuzzy (weighted)"
    if not q.strip():
        return {"results": [], "total": 0, "mode": mode}
    if vector:
        eff = min_score if min_score is not None else 0.0
        results, total = _hybrid(db, q, limit, offset, eff)
    else:
        eff = min_score if min_score is not None else MIN_SCORE_LEX
        results, total = _lexfuzzy(db, q, limit, offset, eff)
    return {"results": results, "total": total, "mode": mode}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    return {
        "documents": db.execute(text("SELECT count(*) FROM documents")).scalar_one(),
        "modernized": db.execute(text("SELECT count(*) FROM documents WHERE modernized_content IS NOT NULL")).scalar_one(),
        "embedded": db.execute(text("SELECT count(*) FROM documents WHERE embedding IS NOT NULL")).scalar_one(),
        "dictionary": db.execute(text("SELECT count(*) FROM dictionary")).scalar_one(),
    }


@app.get("/document/{doc_id}")
def document(doc_id: str, db: Session = Depends(get_db)):
    """Return the full RAW source record for one document (the link target from search results)."""
    row = db.execute(text("SELECT json_data FROM documents WHERE id = :id"), {"id": doc_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="document not found")
    return {"id": doc_id, "raw": row[0]}
