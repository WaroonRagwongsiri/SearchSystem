"""
Dictionary modern-word extraction (batch CLI).

For each dictionary entry whose `modern_word` is still NULL, ask the LLM (Qwen) to
read the raw scholarly `modern_definition` and extract the clean modern Thai
equivalent, then write it back to `modern_word`. The raw definition is kept.

The prompt/cleaning/validation logic lives in dict_extract.py (shared with the
on-add extraction in main.py); this module is the threaded batch runner.

Resumable: rows where modern_word IS NULL are processed; finished rows are skipped,
so an interrupted run continues (a previously failed row has modern_word NULL, so a
batch run also retries it). Run on the host venv (db at localhost:5432; LLM via .env).

  python backend/modernize_dictionary.py            # all unfinished words
  PIPELINE_LIMIT=5 python backend/modernize_dictionary.py   # smoke test (5 words)
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import create_engine, text

from config import DATABASE_URL  # importing config runs load_dotenv()
from dict_extract import extract_modern_word

LLM_CHAT = os.environ["LLM_ENDPOINT"].rstrip("/") + "/v1/chat/completions"
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct")
LIMIT = int(os.environ.get("PIPELINE_LIMIT", "0"))  # 0 = no limit
WORKERS = int(os.environ.get("PIPELINE_WORKERS", "16"))
FETCH_BATCH = 500

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=WORKERS + 4, max_overflow=0)

_tls = threading.local()


def client() -> httpx.Client:
    # ponytail: thread-local — httpx.Client is not thread-safe and the pool fans out across threads.
    c = getattr(_tls, "client", None)
    if c is None:
        c = httpx.Client(timeout=60)
        _tls.client = c
    return c


def run() -> int:
    done = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        while True:
            with engine.connect() as c:
                rows = c.execute(
                    text(
                        "SELECT ancient_word, modern_definition FROM dictionary "
                        "WHERE modern_word IS NULL LIMIT :n"
                    ),
                    {"n": LIMIT if LIMIT and LIMIT < FETCH_BATCH else FETCH_BATCH},
                ).all()
            if not rows:
                break
            results = list(
                pool.map(
                    lambda r: (r[0],) + extract_modern_word(
                        r[0], r[1], client=client(), chat_url=LLM_CHAT, model=LLM_MODEL
                    ),
                    rows,
                )
            )
            ok = [{"w": w, "m": m} for (w, m, _err) in results if m]
            errs = [(w, err) for (w, m, err) in results if not m]
            if ok:
                with engine.begin() as c:
                    c.execute(
                        text(
                            "UPDATE dictionary SET modern_word = :m, status = 'done', error = NULL "
                            "WHERE ancient_word = :w"
                        ),
                        ok,
                    )
            if errs:
                with engine.begin() as c:
                    c.execute(
                        text(
                            "UPDATE dictionary SET status = 'failed', error = :err "
                            "WHERE ancient_word = :w"
                        ),
                        [{"w": w, "err": e} for (w, e) in errs],
                    )
                print(f"  {len(errs)} errors this batch, e.g. {errs[0]}", flush=True)
            done += len(ok)
            print(f"extracted {done}  ({done / (time.time() - start):.1f}/s)", flush=True)
            if LIMIT and done >= LIMIT:
                break
    print(f"extraction done: {done}", flush=True)
    return done


def _self_check() -> None:
    """ponytail: one runnable check — coverage + a few samples after a run."""
    with engine.connect() as c:
        total = c.execute(text("SELECT count(*) FROM dictionary")).scalar_one()
        filled = c.execute(text("SELECT count(*) FROM dictionary WHERE modern_word IS NOT NULL")).scalar_one()
        print(f"\ncoverage: {filled}/{total} words have a modern_word", flush=True)
        for w, m in c.execute(
            text("SELECT ancient_word, modern_word FROM dictionary WHERE modern_word IS NOT NULL ORDER BY random() LIMIT 8")
        ).all():
            print(f"  {w}  ->  {m}", flush=True)
    assert filled > 0, "no rows filled — extraction produced nothing"


if __name__ == "__main__":
    print(f"model: LLM={LLM_MODEL} @ {LLM_CHAT}", flush=True)
    print(f"workers={WORKERS} limit={LIMIT or 'none'}", flush=True)
    t0 = time.time()
    run()
    print(f"complete in {time.time() - t0:.0f}s", flush=True)
    _self_check()
