import os

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from db import Base, SessionLocal, engine
from models import Dictionary  # noqa: F401  (registers model on Base.metadata)

Base.metadata.create_all(engine)

app = FastAPI(title="PocSearch")
# ponytail: allow all origins — local dev POC, no auth/cookies. Tighten to the real frontend origin(s) in prod.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- search config (deliberate, not arbitrary — see CLAUDE.md "algorithms to get right") ---
EMBED_URL = os.environ.get("EMBEDDING_ENDPOINT", "").rstrip("/") + "/v1/embeddings"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "baai/bge-m3")  # lowercase on this gateway (BAAI/ is rejected)
_API_KEY = os.environ.get("MODEL_API_KEY", "").strip()
AUTH = {"Authorization": f"Bearer {_API_KEY}"} if _API_KEY else {}  # gateway requires Bearer; empty ⇒ unauth endpoint
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
    """Upsert a historical→modern mapping. CSV-only: stores exactly what the user
    provides (ancient_word + modern_definition). No LLM round-trip — the dictionary must
    not contain model-fabricated data; the modernize step is the one retained LLM step
    and is reviewable via /documents_by_word + /reembed.

    ponytail: modern_word / status / error columns stay in the schema (dropping is
    destructive) but are dormant now — we stop writing modern_word via extraction. On
    upsert we touch only modern_definition + status ('done'); existing modern_word
    values are left in place (nullify in a follow-up migration for a clean slate).
    """
    stmt = pg_insert(Dictionary).values(
        ancient_word=wm.ancient_word,
        modern_definition=wm.modern_definition,
        status="done",
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ancient_word"],
        set_={
            "modern_definition": stmt.excluded.modern_definition,
            "status": "done",
        },
    )
    db.execute(stmt)
    db.commit()
    return {
        "ancient_word": wm.ancient_word,
        "modern_definition": wm.modern_definition,
        "status": "done",
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
    r = httpx.post(EMBED_URL, headers=AUTH, json={"model": EMBED_MODEL, "input": [q]}, timeout=30)
    r.raise_for_status()
    return r.json()["data"][0]["embedding"]


def _dict_context(db: Session, desc: str) -> str:
    """Reconstruct (read-only) the dictionary context the modernize step was prompted with:
    CSV-sourced modern_definition only (NOT the dormant modern_word). Mirrors
    modernize_embed.context_for — same natural order, capped at 40 — so it answers
    'what did the LLM get for this text?'."""
    rows = db.execute(
        text(
            "SELECT ancient_word, modern_definition FROM dictionary "
            "WHERE strpos(:desc, ancient_word) > 0 LIMIT 40"
        ),
        {"desc": desc},
    ).all()
    if not rows:
        return "(none)"
    return "; ".join(f"{w} = {d}" for w, d in rows)


@app.get("/documents_by_word")
def documents_by_word(word: str, limit: int = 25, offset: int = 0, db: Session = Depends(get_db)):
    """Drill-down: every modernized document whose raw text contains `word`.

    Surfaces the modernize step for Human-In-The-Loop review — raw text, the LLM output
    (modernized_content), the human override (embed_text), and the dictionary context the
    LLM was given (reconstructed read-only from CSV data).
    """
    if not word.strip():
        return {"word": word, "total": 0, "results": []}
    where = "modernized_content IS NOT NULL AND strpos(raw_content, :word) > 0"
    total = db.execute(
        text(f"SELECT count(*) FROM documents WHERE {where}"), {"word": word}
    ).scalar_one()
    rows = db.execute(
        text(
            "SELECT id, json_data->>'subject' AS subject, json_data->>'description' AS description, "
            "modernized_content, embed_text FROM documents "
            f"WHERE {where} ORDER BY id LIMIT :limit OFFSET :offset"
        ),
        {"word": word, "limit": limit, "offset": offset},
    ).all()
    results = [
        {
            "id": r[0],
            "subject": r[1],
            "description": r[2],
            "modernized_content": r[3],
            "embed_text": r[4],
            "dict_context": _dict_context(db, r[2] or ""),
        }
        for r in rows
    ]
    return {"word": word, "total": total, "results": results}


class ReembedBody(BaseModel):
    embed_text: str


@app.post("/reembed/{doc_id}")
def reembed(doc_id: str, body: ReembedBody, db: Session = Depends(get_db)):
    """Persist a human-edited embed_text and embed it in place (HITL re-embed).

    200 {id, ok:true}; empty text ⇒ 400; upstream embed error ⇒ 502 {id, ok:false, error};
    404 if the document is missing.
    """
    if not body.embed_text.strip():
        raise HTTPException(status_code=400, detail="embed_text must not be empty")
    if not db.execute(text("SELECT 1 FROM documents WHERE id = :id"), {"id": doc_id}).first():
        raise HTTPException(status_code=404, detail="document not found")
    try:
        vec = _embed_query(body.embed_text)
    except Exception as e:
        return JSONResponse(
            status_code=502, content={"id": doc_id, "ok": False, "error": str(e)[:200]}
        )
    db.execute(
        text("UPDATE documents SET embed_text = :e, embedding = CAST(:v AS vector) WHERE id = :id"),
        {
            "e": body.embed_text,
            "v": "[" + ",".join(f"{x:.7f}" for x in vec) + "]",
            "id": doc_id,
        },
    )
    db.commit()
    return {"id": doc_id, "ok": True}


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
