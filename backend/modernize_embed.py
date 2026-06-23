"""
Modernization + embedding pipeline (PLAN §3).

Phase 1 — modernize: for each doc, rewrite the historical `description` into modern Thai
          via the LLM (Qwen), with relevant dictionary terms as context.
Phase 2 — embed:    batch-embed each modernized text with BGE-M3 (1024-d).

Resumable: rows where modernized_content / embedding is already set are skipped, so a
interrupted run continues. Run on the host venv (db at localhost:5432; model endpoints via .env).

  python backend/modernize_embed.py            # full corpus
  PIPELINE_LIMIT=5 python backend/modernize_embed.py   # smoke test (5 docs)
"""
import os
import sys
import threading
import time

import httpx
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import create_engine, text

from config import DATABASE_URL  # importing config runs load_dotenv()

LLM_CHAT = os.environ["LLM_ENDPOINT"].rstrip("/") + "/v1/chat/completions"
EMBED_URL = os.environ["EMBEDDING_ENDPOINT"].rstrip("/") + "/v1/embeddings"
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-m3")
LIMIT = int(os.environ.get("PIPELINE_LIMIT", "0"))  # 0 = no limit
WORKERS = int(os.environ.get("PIPELINE_WORKERS", "16"))
FETCH_BATCH = 500
EMBED_BATCH = 64

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=WORKERS + 4, max_overflow=0)

# Load dictionary once; modernization prompts include only entries whose ancient_word is in the text.
with engine.connect() as _c:
    DICT = [(r[0], r[1]) for r in _c.execute(text("SELECT ancient_word, modern_definition FROM dictionary")).all()]
print(f"loaded {len(DICT)} dictionary entries", flush=True)

SYSTEM = (
    "You rewrite historical Thai into modern Thai. "
    "Output ONLY the modernized Thai text. No preamble, no quotes, no explanation."
)


def context_for(desc: str) -> str:
    hits = [(w, d) for (w, d) in DICT if w and w in desc]
    if not hits:
        return "(none)"
    return "; ".join(f"{w} = {d}" for w, d in hits[:40])


_tls = threading.local()


def client() -> httpx.Client:
    c = getattr(_tls, "client", None)
    if c is None:
        c = httpx.Client(timeout=60)
        _tls.client = c
    return c


def modernize(doc_id: str, desc: str) -> tuple[str, str | None, str | None]:
    """Return (id, modernized_text_or_None, error_or_None)."""
    try:
        r = client().post(
            LLM_CHAT,
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Dictionary (use where relevant): {context_for(desc)}\n\nHistorical text: {desc}\n\nModern Thai:"},
                ],
                "temperature": 0.2,
                "max_tokens": 512,
            },
        )
        r.raise_for_status()
        mod = r.json()["choices"][0]["message"]["content"].strip()
        return (doc_id, mod or None, None)
    except Exception as e:  # trust boundary: one bad doc must not kill the run
        return (doc_id, None, str(e)[:200])


def run_modernize() -> int:
    done = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        while True:
            with engine.connect() as c:
                rows = c.execute(
                    text(
                        "SELECT id, json_data->>'description' AS description FROM documents "
                        "WHERE modernized_content IS NULL AND coalesce(json_data->>'description','') <> '' "
                        "LIMIT :n"
                    ),
                    {"n": FETCH_BATCH},
                ).all()
            if not rows:
                break
            results = list(pool.map(lambda r: modernize(r[0], r[1]), rows))
            ok = [{"id": mid, "m": mod} for (mid, mod, _err) in results if mod]
            errs = [(mid, err) for (mid, mod, err) in results if not mod]
            if ok:
                with engine.begin() as c:
                    c.execute(text("UPDATE documents SET modernized_content = :m WHERE id = :id"), ok)
            done += len(ok)
            if errs:
                print(f"  {len(errs)} errors this batch, e.g. {errs[0]}", flush=True)
            print(f"modernized {done}  ({done / (time.time() - start):.1f}/s)", flush=True)
            if LIMIT and done >= LIMIT:
                break
    print(f"modernize phase done: {done}", flush=True)
    return done


def run_embed() -> int:
    done = 0
    start = time.time()
    while True:
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT id, modernized_content FROM documents "
                    "WHERE embedding IS NULL AND modernized_content IS NOT NULL LIMIT :n"
                ),
                {"n": EMBED_BATCH},
            ).all()
        if not rows:
            break
        try:
            r = client().post(EMBED_URL, json={"model": EMBED_MODEL, "input": [r[1] for r in rows]}, timeout=120)
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            params = [{"id": rows[i][0], "e": "[" + ",".join(f"{x:.7f}" for x in data[i]["embedding"]) + "]"} for i in range(len(rows))]
            with engine.begin() as c:
                c.execute(text("UPDATE documents SET embedding = CAST(:e AS vector) WHERE id = :id"), params)
            done += len(rows)
            print(f"embedded {done}  ({done / (time.time() - start):.1f}/s)", flush=True)
        except Exception as e:
            print(f"  embed batch error ({len(rows)} rows): {str(e)[:160]}", flush=True)
            time.sleep(2)
        if LIMIT and done >= LIMIT:
            break
    print(f"embed phase done: {done}", flush=True)
    return done


if __name__ == "__main__":
    print(f"models: LLM={LLM_MODEL} @ {LLM_CHAT}", flush=True)
    print(f"        EMB={EMBED_MODEL} @ {EMBED_URL}", flush=True)
    print(f"workers={WORKERS} limit={LIMIT or 'none'}", flush=True)
    t0 = time.time()
    run_modernize()
    run_embed()
    print(f"pipeline complete in {time.time() - t0:.0f}s", flush=True)
