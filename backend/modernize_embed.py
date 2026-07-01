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
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen3.6-35B-A3B")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "baai/bge-m3")  # lowercase on this gateway (BAAI/ is rejected)
_API_KEY = os.environ.get("MODEL_API_KEY", "").strip()
_HEADERS = {"Authorization": f"Bearer {_API_KEY}"} if _API_KEY else {}  # gateway requires Bearer; empty ⇒ unauth endpoint
LIMIT = int(os.environ.get("PIPELINE_LIMIT", "0"))  # 0 = no limit
WORKERS = int(os.environ.get("PIPELINE_WORKERS", "16"))
FETCH_BATCH = 500
EMBED_BATCH = 64

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=WORKERS + 4, max_overflow=0)

# Load dictionary once; modernization prompts include only entries whose ancient_word is in the text.
# ponytail: dictionary context is CSV-sourced (modern_definition only); modern_word is abandoned —
# it was LLM-fabricated and must not enter the modernize prompt. Matches backend/main._dict_context.
with engine.connect() as _c:
    DICT = [
        (r[0], r[1])
        for r in _c.execute(
            text("SELECT ancient_word, modern_definition FROM dictionary")
        ).all()
    ]
print(f"loaded {len(DICT)} dictionary entries", flush=True)

SYSTEM = (
    "You modernize the SPELLING of historical Thai text. Apply ONLY these changes: "
    "substitute obsolete letter forms to current Thai orthography "
    "(e.g. เฑียร->เทียร, ฑ->น, ฎ->ด, ฏ->ต) and archaic spellings explicitly listed in the dictionary. "
    "DO NOT paraphrase, reword, reorder, expand, or drop anything. "
    "DO NOT 'correct' what you think is a typo — archaic-looking strings inside PERSONAL NAMES "
    "(after นาย/หลวง/ขุน/พระ etc.) and PLACE NAMES are proper nouns, NOT misspellings; "
    "keep them EXACTLY as written. "
    "If no spelling from the dictionary applies, output the text UNCHANGED. "
    "Output ONLY the result text, no preamble, no quotes, no explanation."
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
        c = httpx.Client(timeout=60, headers=_HEADERS)
        _tls.client = c
    return c


def modernize(doc_id: str, text: str) -> tuple[str, str | None, str | None]:
    """Return (id, modernized_text_or_None, error_or_None).

    Qwen3.6-35B-A3B is a *thinking* model: it emits a long `reasoning_content`
    (internal monologue) before the final answer in `content`. We read ONLY
    `content` — never reasoning_content, that's scratchpad, not the answer —
    and budget max_tokens so thinking finishes and the answer lands in content.
    If content is empty (thinking ran to the cap before answering), that's a
    truncation, not a modernization; return it as an error so the row retries
    rather than storing a blank or a reasoning trace.
    """
    try:
        r = client().post(
            LLM_CHAT,
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Dictionary (use where relevant): {context_for(text)}\n\nHistorical text: {text}\n\nModern Thai:"},
                ],
                "temperature": 0.2,
                "max_tokens": 4096,
            },
        )
        r.raise_for_status()
        mod = (r.json()["choices"][0]["message"].get("content") or "").strip()
        if not mod:
            return (doc_id, None, "empty content (thinking truncated before answer)")
        return (doc_id, mod, None)
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
            # coalesce(embed_text, modernized_content): honor a human /reembed override when
            # re-running the bulk pipeline; NULL ⇒ fall back to the LLM's modernized_content.
            rows = c.execute(
                text(
                    "SELECT id, coalesce(embed_text, modernized_content) AS text FROM documents "
                    "WHERE embedding IS NULL AND coalesce(embed_text, modernized_content) IS NOT NULL "
                    "LIMIT :n"
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
