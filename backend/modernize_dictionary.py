"""
Dictionary modern-word extraction.

For each dictionary entry whose `modern_word` is still NULL, ask the LLM (Qwen) to
read the raw scholarly `modern_definition` and extract the clean modern Thai
equivalent, then write it back to `modern_word`. The raw definition is kept.

Resumable: rows where modern_word IS NULL are processed; finished rows are skipped,
so an interrupted run continues. Run on the host venv (db at localhost:5432; LLM via .env).

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

LLM_CHAT = os.environ["LLM_ENDPOINT"].rstrip("/") + "/v1/chat/completions"
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-14B-Instruct")
LIMIT = int(os.environ.get("PIPELINE_LIMIT", "0"))  # 0 = no limit
WORKERS = int(os.environ.get("PIPELINE_WORKERS", "16"))
FETCH_BATCH = 500
DEF_MAX = 2000  # cap definition chars sent to the model (rare entries are long)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=WORKERS + 4, max_overflow=0)

SYSTEM = (
    "You extract the single best modern Thai equivalent of a historical Thai dictionary word. "
    "Read the entry and output ONLY one modern Thai word — no quotes, no list, no commas, "
    "no part-of-speech, no explanation, no trailing punctuation. "
    "Rules: if the entry gives an explicit modern form (after 'ดู', 'ปัจจุบันเรียกว่า', "
    "or as the headword gloss), output that single form; "
    "modernize old spelling to current Thai orthography (e.g. เฑียร->เทียร, ฑ->น); "
    "do not reorder or rearrange syllables of the word; "
    "do not invent a meaning — if uncertain or no modern form is determinable, "
    "output the word unchanged."
)

# Few-shot from real entries in this dictionary.
FEW_SHOT = """Examples (ancient word -> one modern equivalent):
สรวป -> สรุป
ขยุม ๑ -> ขยม
กงเวียน -> วงเวียน
กฎมณเฑียรบาล -> กฎมนเทียรบาล
กราล -> กราน
โกรด -> โกรก
กฎ -> กฎ"""


def _clean(s: str) -> str:
    # Tolerate the model wrapping output in quotes / a trailing period / stray markers.
    s = s.strip().strip("“。\"'").strip()
    if s.endswith("."):
        s = s[:-1]
    return s.strip()


def _valid_thai(s: str) -> bool:
    """True if s is a plausible modern Thai word: non-empty, <=40 chars, Thai-only.
    Rejects the model's failure mode of emitting English meta-commentary or CJK on
    hard entries — garbage here would poison the document-modernization prompt."""
    if not s or len(s) > 40:
        return False
    return all(("฀" <= ch <= "๿") or ch in " ,." for ch in s)


_tls = threading.local()


def client() -> httpx.Client:
    c = getattr(_tls, "client", None)
    if c is None:
        c = httpx.Client(timeout=60)
        _tls.client = c
    return c


def extract(ancient: str, definition: str) -> tuple[str, str | None, str | None]:
    """Return (ancient_word, modern_word_or_None, error_or_None)."""
    try:
        r = client().post(
            LLM_CHAT,
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": (
                        f"{FEW_SHOT}\n\n"
                        f"Word: {ancient}\n"
                        f"Entry: {definition[:DEF_MAX]}\n"
                        f"Modern equivalent:"
                    )},
                ],
                "temperature": 0,
                "max_tokens": 48,
            },
        )
        r.raise_for_status()
        mod = _clean(r.json()["choices"][0]["message"]["content"])
        # Reject garbage (non-Thai / over-long); fall back to the word itself —
        # identity is always safe, a hallucinated equivalent is not.
        if not _valid_thai(mod):
            mod = ancient
        return (ancient, mod, None)
    except Exception as e:  # one bad row must not kill the run
        return (ancient, None, str(e)[:200])


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
            results = list(pool.map(lambda r: extract(r[0], r[1]), rows))
            ok = [{"w": w, "m": m} for (w, m, _err) in results if m]
            errs = [(w, err) for (w, m, err) in results if not m]
            if ok:
                with engine.begin() as c:
                    c.execute(
                        text("UPDATE dictionary SET modern_word = :m WHERE ancient_word = :w"),
                        ok,
                    )
            done += len(ok)
            if errs:
                print(f"  {len(errs)} errors this batch, e.g. {errs[0]}", flush=True)
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
